"""SME Adv & Route Patterns: add an Advertised Pattern and its matching Route Pattern for each number.

Port of `uc-automation/cucm/AdvP_RP_add.py`. The script's constants (pattern type, PSTN rule, strip/prepend, route
partition, route list, descriptions) are the defaults of `DEFAULTS` and are editable on the page's settings window.
Only a connection marked as SME cluster may be used (`require_sme`)."""

import csv
import io
import re

from .cucm_axl import AxlError
from .cucm_connections import CucmConnection
from .cucm_routing import add_advertised_pattern, add_route_pattern, find_route_pattern

PATTERN_TYPES = ["Enterprise Number", "+E.164 Number"]
# AXL hostedRoutePSTNRule value -> label shown on the settings window
PSTN_CHOICES = [
    ("No PSTN", "Don't Use PSTN Failover"),
    ("Use pattern", "Use Pattern as PSTN Failover Number"),
    ("Specify", "Apply Strip Digits and Prepend Digits to Pattern and Use for PSTN Failover"),
]
DEST_TYPES = ["Route List", "Gateway"]

DEFAULTS = {
    "adv_desc": "{Var1} Webex Calling {Pattern}",
    "adv_type": "Enterprise Number",
    "pstn_rule": "No PSTN",
    "pstn_strip": "0",
    "pstn_prepend": "",
    "rp_desc": "{Var1} DID to Webex Calling",
    "rp_partition": "Enterprise_PT",
    "rp_dest_type": "Route List",
    "rp_dest": "WebexCalling",
}

DEFAULT_VARS = ["Department"]  # names of Var1, Var2, ...; only Var1 exists by default
MAX_VARS = 9
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def var_key(i: int) -> str:
    """Name of the i-th variable (0 based): Var1 to Var9."""
    return f"Var{i + 1}"


def var_display(i: int, names: list[str]) -> str:
    """Column title for a variable: its name, or Var1... when the name is blank."""
    return (names[i].strip() if i < len(names) else "") or var_key(i)


# Example values for the Multiple Patterns tab: by a word in the variable's name, else by its position
_SAMPLES_BY_WORD = [(("department", "dept", "team"), ("Sales", "Support")),
                    (("site", "location", "city", "office"), ("Dallas", "Denver")),
                    (("customer", "company", "client", "tenant"), ("Acme", "Contoso")),
                    (("floor", "building"), ("Floor 2", "Floor 3"))]
_SAMPLES_BY_POSITION = [("Sales", "Support"), ("Dallas", "Denver"), ("Acme", "Contoso"), ("Main", "Annex"),
                        ("North", "South"), ("East", "West"), ("Alpha", "Beta"), ("Red", "Blue"), ("One", "Two")]


def sample_value(i: int, names: list[str], row: int) -> str:
    """Example value of variable i for example row 0 or 1."""
    name = (names[i] if i < len(names) else "").lower()
    for words, values in _SAMPLES_BY_WORD:
        if any(w in name for w in words):
            return values[row]
    return _SAMPLES_BY_POSITION[i % len(_SAMPLES_BY_POSITION)][row]


def var_label(i: int, names: list[str]) -> str:
    """Label shown on the page: 'Var1 - Department' (just 'Var1' when the name is blank)."""
    name = names[i].strip() if i < len(names) else ""
    return f"Var{i + 1} - {name}" if name else f"Var{i + 1}"


def _lookup_keys(names: list[str]) -> dict[str, int]:
    """Placeholder text (lower case) -> variable index: {Var1} to {Var9}, any case."""
    return {var_key(i).lower(): i for i in range(len(names))}


def check_regexes(regexes: list[str], names: list[str]) -> str:
    """Error text for the first variable regex that does not compile, or ''."""
    for i, rx_text in enumerate(regexes[:len(names)]):
        if rx_text.strip():
            try:
                re.compile(rx_text)
            except re.error as e:
                return f"{var_display(i, names)} regex: {e}"
    return ""


def check_values(values: list[str], names: list[str], regexes: list[str], where: str = "") -> str:
    """Error text for the first non-empty variable value that does not match its regex (re.search, so anchor
    with ^ and $ to match the whole value), or ''. A variable with no regex accepts anything."""
    for i, value in enumerate(values[:len(names)]):
        pattern = regexes[i].strip() if i < len(regexes) else ""
        if pattern and value.strip() and not re.search(pattern, value.strip()):
            on = f" on {where}" if where else ""
            return f"{var_display(i, names)} '{value.strip()}' does not match the regex {pattern}{on}."
    return ""


def require_sme(conn: CucmConnection | None) -> CucmConnection:
    """The connection, or AxlError when there is none or it is not marked as an SME cluster."""
    if conn is None:
        raise AxlError("Add a CUCM connection first.")
    if not conn.sme:
        raise AxlError(f"{conn.name} is not marked as an SME cluster. Tick 'SME cluster' on Credentials > CUCM.")
    return conn


def format_advertised_pattern(pattern: str) -> str:
    """10 digit numbers get +1, 11 digit numbers starting with 1 get +."""
    value = pattern.strip()
    if value.isdigit() and len(value) == 10:
        return "+1" + value
    if value.isdigit() and len(value) == 11 and value.startswith("1"):
        return "+" + value
    return value


def format_route_pattern(pattern: str) -> str:
    """Numbers already in +1 format get a \\ prefix, 10 digit numbers \\+1, 11 digit numbers starting with 1 \\+."""
    value = pattern.strip()
    if value.startswith("+1"):
        return "\\" + value
    if value.isdigit() and len(value) == 10:
        return "\\+1" + value
    if value.isdigit() and len(value) == 11 and value.startswith("1"):
        return "\\+" + value
    return value


def check_template(template: str, label: str, names: list[str]) -> str:
    """Error text when the template is empty or uses a {placeholder} that is not {Pattern} or a variable."""
    if not template.strip():
        return f"{label} description is required."
    known = _lookup_keys(names)
    for name in _PLACEHOLDER_RE.findall(template):
        if name.strip().lower() != "pattern" and name.strip().lower() not in known:
            return f"{label} description: unknown {{{name}}}. Use {{Pattern}} or one of " \
                   f"{', '.join('{' + var_key(i) + '}' for i in range(len(names)))}."
    return ""


def used_vars(templates: list[str], names: list[str]) -> set[int]:
    """Indexes of the variables the templates refer to."""
    known = _lookup_keys(names)
    return {known[n.strip().lower()] for t in templates for n in _PLACEHOLDER_RE.findall(t)
            if n.strip().lower() in known}


def renumber_template(template: str, removed: int) -> str:
    """Template after variable `removed` (0 based) was deleted: its {VarN} is dropped and later ones move up
    ({Var4} becomes {Var3} when Var3 is deleted). Other text is kept."""
    def fix(m):
        key = m.group(1).strip().lower()
        if not (key.startswith("var") and key[3:].isdigit()):
            return m.group(0)
        n = int(key[3:]) - 1
        if n == removed:
            return ""
        return "{" + var_key(n - 1) + "}" if n > removed else m.group(0)
    return " ".join(_PLACEHOLDER_RE.sub(fix, template).split())


def render_description(template: str, values: list[str], names: list[str], pattern: str) -> str:
    """Fill {Pattern} (last 10 characters of the advertised pattern) and the variables (case-insensitive)."""
    known = _lookup_keys(names)

    def fill(m):
        key = m.group(1).strip().lower()
        if key == "pattern":
            return format_advertised_pattern(pattern)[-10:]
        i = known.get(key)
        return (values[i].strip() if i is not None and i < len(values) else "") if i is not None else m.group(0)

    return " ".join(_PLACEHOLDER_RE.sub(fill, template).split())


def check_settings(s: dict[str, str], names: list[str]) -> str:
    """First problem with the settings, or ''."""
    for key, label in (("adv_desc", "Advertise Pattern"), ("rp_desc", "Route Pattern")):
        if err := check_template(s.get(key, ""), label, names):
            return err
    if s.get("adv_type") not in PATTERN_TYPES:
        return "Choose Enterprise Number or +E164 Number for the Advertised Pattern."
    if s.get("pstn_rule") not in [v for v, _ in PSTN_CHOICES]:
        return "Choose a PSTN failover setting."
    if s["pstn_rule"] == "Specify":
        if not s.get("pstn_strip", "").strip().isdigit():
            return "PSTN Failover Strip Digits must be a number."
    if not s.get("rp_partition", "").strip():
        return "Route Pattern partition is required."
    if s.get("rp_dest_type") not in DEST_TYPES:
        return "Choose Route List or Gateway for the Route Pattern."
    if not s.get("rp_dest", "").strip():
        return f"Route Pattern {s.get('rp_dest_type', 'destination').lower()} name is required."
    return ""


def parse_pattern_csv(data: bytes, names: list[str]) -> list[dict]:
    """Rows {pattern, vars} from CSV bytes (vars: one value per variable). Header row required; the variable
    columns (titled Var1 to Var9 or with the variable's name, any case) are optional."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    if "pattern" not in header:
        raise ValueError("The first row must be a header with a pattern column (then Var1, Var2... as needed).")
    p = header.index("pattern")
    cols = []
    for i in range(len(names)):
        wanted = {var_key(i).lower(), var_display(i, names).lower()}  # Var1 or the name as the column title
        cols.append(next((j for j, h in enumerate(header) if h in wanted), -1))
    out = []
    for r in rows[1:]:
        pattern = r[p].strip() if p < len(r) else ""
        if pattern:
            out.append({"pattern": pattern,
                        "vars": [r[j].strip() if 0 <= j < len(r) else "" for j in cols]})
    return out


def add_pattern_pair(conn: CucmConnection, settings: dict[str, str], names: list[str], pattern: str,
                     values: list[str], adv_anyway: bool | None = None) -> str:
    """Add the Advertised Pattern and the matching Route Pattern. Both are tried; raises AxlError naming each failure.

    `adv_anyway` None: no check. True or False: look for the Route Pattern first. When it exists it is not added and
    its pattern and description are reported; the Advertised Pattern is still added only when `adv_anyway` is True."""
    require_sme(conn)
    adv = format_advertised_pattern(pattern)
    rp = format_route_pattern(pattern)
    dest = {"routeListName": settings["rp_dest"].strip()} if settings["rp_dest_type"] == "Route List" \
        else {"gatewayName": settings["rp_dest"].strip()}
    adv_row = {"pattern": adv, "patternType": settings["adv_type"], "hostedRoutePSTNRule": settings["pstn_rule"],
               "description": render_description(settings["adv_desc"], values, names, pattern)}
    if settings["pstn_rule"] == "Specify":
        adv_row["pstnFailStrip"] = settings["pstn_strip"].strip()
        adv_row["pstnFailPrepend"] = settings["pstn_prepend"].strip()
    rp_row = {"pattern": rp, "routePartitionName": settings["rp_partition"].strip(),
              "description": render_description(settings["rp_desc"], values, names, pattern), **dest}
    part = rp_row["routePartitionName"]
    outcomes, failed = [], False
    existing = find_route_pattern(conn, rp, part) if adv_anyway is not None else None
    if existing:
        found = (f"Route pattern: already exists {rp} in {part}, "
                 f"description \"{existing.get('description', '')}\"")
        if not adv_anyway:
            raise AxlError(f"{found}; Advertised pattern: not added (option off)")
        try:
            add_advertised_pattern(conn, adv_row)
        except AxlError as e:
            raise AxlError(f"Advertised pattern: failed {adv} ({e}); {found}")
        return f"Advertised pattern: added {adv}; {found}"
    for label, fn, row, shown in (("Advertised pattern", add_advertised_pattern, adv_row, adv),
                                  ("Route pattern", add_route_pattern, rp_row, f"{rp} in {part}")):
        try:
            fn(conn, row)
            outcomes.append(f"{label}: added {shown}")
        except AxlError as e:
            failed = True
            outcomes.append(f"{label}: failed {shown} ({e})")
    if failed:
        raise AxlError("; ".join(outcomes))
    return "; ".join(outcomes)
