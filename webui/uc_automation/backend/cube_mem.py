"""Router memory status: parse `show platform software status control-processor br`."""

import csv
import io

COMMAND = "show platform software status control-processor br"
DEFAULT_THRESHOLD = 33


def extract_memory_section(output: str) -> str:
    memory: list[str] = []
    in_memory = False
    for line in output.split("\n"):
        if "Memory (kB)" in line:
            in_memory = True
        if in_memory:
            memory.append(line)
            if len(memory) > 1 and line.strip() and not line[0].isspace() and "Memory" not in line:
                memory.pop()
                break
    return "\n".join(memory) if memory else "Memory section not found"


def extract_free_percentage(output: str) -> int:
    """The Free (Pct) value of the RP0/RP1 line, 0 when not found."""
    for line in output.split("\n"):
        if "RP0" in line or "RP1" in line:
            pcts = []
            for part in line.split():
                if part.endswith("%)") and "(" in part:
                    try:
                        pcts.append(int(part.strip("()%")))
                    except ValueError:
                        continue
            if len(pcts) >= 2:
                return pcts[1]
    return 0


def memory_csv(rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["hostname", "router_ip", "status", "free_pct", "detail"])
    for r in rows:
        w.writerow([r["hostname"], r["ip"], r["status"], r["free_pct"], r["memory"]])
    return out.getvalue().encode("utf-8")
