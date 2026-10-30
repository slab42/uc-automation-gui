"""Router config compare: split a config into voice sections, diff against a template, build the HTML report.

Copied from cube/compare_router_config.py (the CLI scripts are reference only).
"""

from datetime import datetime
from difflib import SequenceMatcher
from html import escape

COMMAND = "show running-config"


class ConfigParser:
    """Parse Cisco router configs into hierarchical sections."""

    @staticmethod
    def parse_sections(config_text):
        """Parse config into sections based on top-level commands."""
        sections = {}
        current_section = None
        current_lines = []

        for line in config_text.split('\n'):
            stripped = line.strip()

            if not stripped or stripped.startswith('!'):
                continue

            if line and not line[0].isspace():
                if current_section:
                    sections[current_section] = current_lines
                current_section = stripped
                current_lines = [stripped]
            elif current_section:
                current_lines.append(line.rstrip())

        if current_section:
            sections[current_section] = current_lines

        return sections

    @staticmethod
    def extract_voice_sections(config_text):
        """Extract only voice-related sections from config."""
        voice_keywords = [
            'voice', 'dial-peer', 'call-manager', 'ephone',
            'telephony-service', 'gateway', 'h323', 'mgcp',
            'sccp', 'sip', 'isdn', 'primary-rate', 'bri',
            'ds0', 'voice-port', 'connection', 'pots',
            'fax', 'codec', 'class provider'
        ]

        sections = ConfigParser.parse_sections(config_text)
        voice_sections = {}

        for section_name, lines in sections.items():
            section_lower = section_name.lower()
            if any(keyword in section_lower for keyword in voice_keywords):
                voice_sections[section_name] = lines

        return voice_sections

    @staticmethod
    def normalize_lines(lines):
        """Normalize lines for comparison (strip trailing whitespace)."""
        return [line.rstrip() for line in lines if line.strip()]


class ConfigComparator:
    """Compare template config to router config."""

    def __init__(self, template_sections):
        """Store the template sections to compare router configs against."""
        self.template_sections = template_sections

    def compare(self, router_sections):
        """Compare router config to template. Returns dict with variances."""
        results = {
            'missing_sections': [],
            'extra_sections': [],
            'section_diffs': {}
        }

        for template_section in self.template_sections:
            if template_section not in router_sections:
                results['missing_sections'].append(template_section)
            else:
                template_lines = ConfigParser.normalize_lines(
                    self.template_sections[template_section]
                )
                router_lines = ConfigParser.normalize_lines(
                    router_sections[template_section]
                )

                if template_lines != router_lines:
                    diff = self._compute_diff(template_lines, router_lines)
                    results['section_diffs'][template_section] = diff

        for router_section in router_sections:
            if router_section not in self.template_sections:
                results['extra_sections'].append(router_section)

        return results

    @staticmethod
    def _compute_diff(template_lines, router_lines):
        """Compute line-by-line diff between template and router config."""
        sm = SequenceMatcher(None, template_lines, router_lines)
        diff = {
            'template_only': [],
            'router_only': [],
            'shared': []
        }

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'delete':
                diff['template_only'].extend(template_lines[i1:i2])
            elif tag == 'insert':
                diff['router_only'].extend(router_lines[j1:j2])
            elif tag == 'equal':
                diff['shared'].extend(template_lines[i1:i2])

        return diff


def build_html_report(hostname, template_sections, comparison_result):
    """Generate HTML report for config comparison."""
    has_variances = (
        comparison_result['missing_sections'] or
        comparison_result['extra_sections'] or
        comparison_result['section_diffs']
    )

    status_color = '#dc3545' if has_variances else '#28a745'
    status_text = 'VARIANCES FOUND' if has_variances else 'COMPLIANT'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Config Comparison Report - {escape(hostname)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .header {{ background-color: {status_color}; color: white; padding: 20px; border-radius: 5px; }}
        .header h1 {{ margin: 0; }}
        .status {{ font-size: 24px; font-weight: bold; }}
        .timestamp {{ font-size: 12px; margin-top: 10px; }}
        .section {{ background-color: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .section-title {{ background-color: #007bff; color: white; padding: 10px; border-radius: 3px; font-weight: bold; }}
        .variance-type {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 10px; margin: 10px 0; border-radius: 3px; }}
        .missing {{ background-color: #f8d7da; border-left: 4px solid #dc3545; }}
        .extra {{ background-color: #d1ecf1; border-left: 4px solid #17a2b8; }}
        .compliant {{ background-color: #d4edda; border-left: 4px solid #28a745; }}
        .code {{ background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 3px; padding: 10px; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; }}
        .line {{ margin: 3px 0; }}
        .template-only {{ color: #dc3545; }}
        .router-only {{ color: #17a2b8; }}
        .shared {{ color: #28a745; }}
        .label {{ font-weight: bold; font-size: 12px; text-transform: uppercase; }}
        .summary {{ background-color: #e7f3ff; border-left: 4px solid #2196F3; padding: 15px; border-radius: 3px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Router Configuration Comparison Report</h1>
        <div class="status">{status_text}</div>
        <div>Router: {escape(hostname)}</div>
        <div class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>

    <div class="section">
        <div class="summary">
            <div><strong>Template Sections Checked:</strong> {len(template_sections)}</div>
            <div><strong>Missing Sections:</strong> {len(comparison_result['missing_sections'])}</div>
            <div><strong>Extra Sections:</strong> {len(comparison_result['extra_sections'])}</div>
            <div><strong>Sections with Differences:</strong> {len(comparison_result['section_diffs'])}</div>
        </div>
    </div>
"""

    if comparison_result['missing_sections']:
        html += '<div class="section">'
        html += '<div class="section-title">Missing Sections (in template but not in router config)</div>'
        for section in sorted(comparison_result['missing_sections']):
            html += f'<div class="variance-type missing">{escape(section)}</div>'
        html += '</div>'

    if comparison_result['extra_sections']:
        html += '<div class="section">'
        html += '<div class="section-title">Extra Sections (in router config but not in template)</div>'
        for section in sorted(comparison_result['extra_sections']):
            html += f'<div class="variance-type extra">{escape(section)}</div>'
        html += '</div>'

    if comparison_result['section_diffs']:
        for section_name in sorted(comparison_result['section_diffs'].keys()):
            diff = comparison_result['section_diffs'][section_name]
            html += '<div class="section">'
            html += f'<div class="section-title">{escape(section_name)}</div>'

            html += '<div style="margin-top: 10px;">'

            if diff['template_only']:
                html += '<div class="variance-type missing"><span class="label">In Template Only (Missing from Router)</span>'
                html += '<div class="code">'
                for line in diff['template_only']:
                    html += f'<div class="line template-only">- {escape(line)}</div>'
                html += '</div></div>'

            if diff['router_only']:
                html += '<div class="variance-type extra"><span class="label">In Router Only (Extra in Router)</span>'
                html += '<div class="code">'
                for line in diff['router_only']:
                    html += f'<div class="line router-only">+ {escape(line)}</div>'
                html += '</div></div>'

            html += '</div></div>'

    if not has_variances:
        html += '<div class="section"><div class="variance-type compliant"><strong>✓ Configuration is compliant with template</strong></div></div>'

    html += """
</body>
</html>
"""

    return html


def parse_template(text: str) -> dict[str, list[str]]:
    return ConfigParser.extract_voice_sections(text)


def has_variances(result: dict) -> bool:
    return bool(result["missing_sections"] or result["extra_sections"] or result["section_diffs"])


def compare_config(template_sections: dict, running_config: str) -> dict:
    return ConfigComparator(template_sections).compare(ConfigParser.extract_voice_sections(running_config))
