"""Read a Cisco UCCX script (.aef) and build an HTML report of it.

An .aef is a Java serialization stream written by the Script Editor (com.cisco.wfframework classes). This reads the
stream directly, without Cisco's classes and without running anything from the file. Classes with a custom
writeObject (most of Cisco's) may or may not write their default fields first, so the reader tries the fields and, when
they do not fit, backs up and reads the class data as plain annotations.

The report lists the steps in stored (editor) order with their properties as stored, the variables, the labels and the
author's comments. Property names and the wiring between steps are not resolved. No Reflex imports.
"""

import html
import struct
from collections import Counter

from .errors import UserError

MAX_BYTES = 25 * 1024 * 1024


class AefError(UserError):
    pass


class _Bad(Exception):
    pass


class Cls:
    def __init__(self):
        self.name, self.flags, self.fields, self.sup = "", 0, [], None


class Obj:
    def __init__(self, cls: Cls):
        self.cls, self.fields, self.ann = cls, {}, []  # ann: [(class name, [content...])]

    @property
    def name(self) -> str:
        return self.cls.name.rsplit(".", 1)[-1]

    def contents(self) -> list:
        return [v for _, a in self.ann for v in a]


class Arr:
    def __init__(self, cls: Cls):
        self.cls, self.items = cls, []


class Block(bytes):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.p, self.h = data, 4, []

    def u(self, fmt: str):
        n = struct.calcsize(fmt)
        if self.p + n > len(self.d):
            raise _Bad("eof")
        v = struct.unpack_from(">" + fmt, self.d, self.p)[0]
        self.p += n
        return v

    def peek(self) -> int:
        return self.d[self.p] if self.p < len(self.d) else -1

    def utf(self, long: bool = False) -> str:
        n = self.u("q" if long else "H")
        if n < 0 or self.p + n > len(self.d):
            raise _Bad("utf")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b.decode("utf-8", "replace")

    def ref(self):
        i = self.u("I") - 0x7E0000
        if not 0 <= i < len(self.h):
            raise _Bad("ref")
        return self.h[i]

    def content(self):
        t = self.u("B")
        if t == 0x70:
            return None
        if t == 0x71:
            return self.ref()
        if t == 0x72:
            return self.classdesc(t)
        if t == 0x73:
            return self.obj()
        if t in (0x74, 0x7C):
            v = self.utf(t == 0x7C)
            self.h.append(v)
            return v
        if t == 0x75:
            return self.arr()
        if t == 0x76:
            c = self.classdesc(self.u("B"))
            self.h.append(c)
            return c
        if t in (0x77, 0x7A):
            n = self.u("B" if t == 0x77 else "I")
            if self.p + n > len(self.d):
                raise _Bad("block")
            b = Block(self.d[self.p:self.p + n])
            self.p += n
            return b
        if t == 0x7E:
            c = self.classdesc(self.u("B"))
            i = len(self.h)
            self.h.append(None)
            self.h[i] = self.content()
            return self.h[i]
        raise _Bad(f"type {t:#x}")

    def classdesc(self, t=None):
        t = self.u("B") if t is None else t
        if t == 0x70:
            return None
        if t == 0x71:
            return self.ref()
        if t != 0x72:
            raise _Bad("class")
        c = Cls()
        c.name = self.utf()
        self.u("q")
        self.h.append(c)
        c.flags = self.u("B")
        for _ in range(self.u("H")):
            tc, nm = chr(self.u("B")), self.utf()
            sig = self.content() if tc in "L[" else None
            c.fields.append((tc, nm, sig))
        while self.peek() != 0x78:
            self.content()
        self.p += 1
        c.sup = self.classdesc()
        return c

    def prim(self, tc: str):
        return {"B": lambda: self.u("b"), "C": lambda: chr(self.u("H")), "D": lambda: self.u("d"),
                "F": lambda: self.u("f"), "I": lambda: self.u("i"), "J": lambda: self.u("q"),
                "S": lambda: self.u("h"), "Z": lambda: bool(self.u("B"))}[tc]()

    def field(self):
        if self.peek() in (0x77, 0x7A, 0x78):  # block data is never a field value
            raise _Bad("block in field")
        return self.content()

    def arr(self):
        c = self.classdesc()
        a = Arr(c)
        self.h.append(a)
        kind = c.name[1]
        for _ in range(self.u("i")):
            a.items.append(self.prim(kind) if kind not in "L[" else self.content())
        return a

    def annotations(self) -> list:
        out = []
        while self.peek() != 0x78:
            out.append(self.content())
        self.p += 1
        return out

    def obj(self):
        c = self.classdesc()
        o = Obj(c)
        self.h.append(o)
        chain, k = [], c
        while k:
            chain.append(k)
            k = k.sup
        for k in reversed(chain):
            if k.flags & 0x04:  # externalizable
                o.ann.append((k.name, self.annotations()))
                continue
            mark, hmark = self.p, len(self.h)
            try:
                fields = {nm: self.prim(tc) if tc not in "L[" else self.field() for tc, nm, _ in k.fields}
                ann = self.annotations() if k.flags & 0x01 else []
            except _Bad:
                if not k.flags & 0x01:
                    raise
                self.p = mark
                del self.h[hmark:]
                fields, ann = {}, self.annotations()
            o.fields.update(fields)
            o.ann.append((k.name, ann))
        return o


def parse(data: bytes) -> Obj:
    """The workflow object of an .aef file."""
    if len(data) > MAX_BYTES:
        raise AefError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if data[:4] != b"\xac\xed\x00\x05":
        raise AefError("This is not a UCCX script (.aef) file.")
    try:
        root = _Reader(data).content()
    except (_Bad, RecursionError):
        raise AefError("This script file could not be read. It may be damaged or from an unsupported version.")
    if not isinstance(root, Obj) or not root.cls.name.endswith("WFWorkflow"):
        raise AefError("This is not a UCCX script (.aef) file.")
    return root


# --- what to pull out ---

def _texts(x, out: list, skip: set) -> None:
    """Every non-empty string below x (char arrays joined), not following the objects in `skip`."""
    if isinstance(x, Obj):
        if id(x) in skip:
            return
        skip.add(id(x))
        for v in x.fields.values():
            _texts(v, out, skip)
        for v in x.contents():
            _texts(v, out, skip)
    elif isinstance(x, Arr):
        if x.cls.name == "[C":
            out.append("".join(x.items))
        else:
            for v in x.items:
                _texts(v, out, skip)
    elif isinstance(x, str) and x:
        out.append(x)


def _dots(text: str) -> bool:
    return set(text) <= {"."}


def read(data: bytes) -> dict:
    """{'file', 'path', 'steps': [(n, type, [properties])], 'variables': [(name, type, value)]}."""
    wf = parse(data)
    top = wf.contents()
    names = [v for v in top if isinstance(v, str)]
    chain = next((v for v in top if isinstance(v, Obj) and v.name == "DoublyLinkedList"), None)
    steps_raw = [v for v in (chain.contents() if chain else []) if isinstance(v, Obj)]
    skip = {id(wf), id(chain)} | {id(s) for s in steps_raw}
    steps = []
    for i, s in enumerate(steps_raw, 1):
        parts = s.contents()
        info = next((v for v in parts if isinstance(v, str)), "")
        bean = next((v for v in parts if isinstance(v, Obj)), None)
        props: list[str] = []
        _texts(bean, props, set(skip))
        steps.append((i, info.rsplit(".", 1)[-1].replace("BeanInfo", "") or "?", list(dict.fromkeys(props))))
    variables = []
    ctx = next((v for v in top if isinstance(v, Obj) and v.name == "WFWorkflowContextDefinition"), None)
    if ctx:
        vec = next((v for v in ctx.contents() if isinstance(v, Obj)), None)  # the first vector is the variable list
        arr = next((v for v in vec.fields.values() if isinstance(v, Arr)), None) if vec else None
        if arr:
            for v in arr.items:
                if not isinstance(v, Obj):
                    continue
                parts = v.contents()
                name = next((x for x in parts if isinstance(x, str)), "")
                kind = next((x.name.rsplit(".", 1)[-1] for x in parts if isinstance(x, Cls)), "?")
                expr = next((x for x in parts if isinstance(x, Obj)), None)
                value = ""
                if expr:
                    strings = [x for x in expr.contents() if isinstance(x, str)]
                    value = strings[-1] if strings else ""
                variables.append((name, kind, value))
    return {"file": names[0] if names else "", "path": names[1] if len(names) > 1 else "",
            "steps": steps, "variables": variables}


_CSS = """body{font:14px system-ui,sans-serif;margin:24px;color:#1d2330}h1{margin:0 0 4px}
h2{margin-top:32px;border-bottom:1px solid #ccd;padding-bottom:4px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #dde;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#eef;position:sticky;top:0}.sep{color:#99a}.lbl td{background:#fff7d6}.goto td{background:#e8f4ff}
.cmt td{color:#667;background:#f6f6f6}.if td{background:#f0ffe8}.pill{display:inline-block;background:#eef;
border-radius:10px;padding:2px 9px;margin:2px}small{color:#667}pre{white-space:pre-wrap;background:#f6f6f6;padding:8px}"""


def report(data: bytes, name: str = "") -> tuple[str, dict[str, int]]:
    """(HTML report, counts) for one .aef. Every value from the file is escaped."""
    info = read(data)
    e = html.escape
    steps, variables = info["steps"], info["variables"]
    kinds = Counter(t for _, t, _ in steps)
    labels = [p[0] for _, t, p in steps if t == "StepLabel" and p]
    gotos = Counter(p[0] for _, t, p in steps if t == "StepGoto" and p)
    comments = [" ".join(p) for _, t, p in steps if t == "StepComment" and p and not all(_dots(x) for x in p)]
    subflows = list(dict.fromkeys(p[0] for _, t, p in steps if t == "StepCallSubflow" and p))
    css = {"StepLabel": "lbl", "StepGoto": "goto", "StepComment": "cmt", "StepIf": "if"}

    def row(n, t, p):
        shown = ' <span class="sep">|</span> '.join(e(x) for x in p if not _dots(x))
        return f'<tr class="{css.get(t, "")}"><td>{n}</td><td>{e(t)}</td><td>{shown}</td></tr>'

    title = e(info["file"] or name or "Script")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>UCCX Script Report - {title}</title>
<style>{_CSS}</style></head><body>
<h1>UCCX Script Report</h1><small>{title}<br>Original path: {e(info["path"])}</small>
<h2>Summary</h2><p>{len(steps)} steps, {len(variables)} variables, {len(labels)} labels.</p>
<p>{"".join(f'<span class="pill">{e(k)}: {v}</span>' for k, v in kinds.most_common())}</p>
{("<p>Subflows called: " + ", ".join(e(x) for x in subflows) + "</p>") if subflows else ""}
<h2>Script Comments</h2>{"".join(f"<pre>{e(c)}</pre>" for c in comments) or "None"}
<h2>Variables</h2><table><tr><th>Name</th><th>Type</th><th>Value</th></tr>
{"".join(f"<tr><td>{e(n)}</td><td>{e(t)}</td><td>{e(v)}</td></tr>" for n, t, v in variables)}</table>
<h2>Steps</h2><p><small>Stored (editor) order. Yellow: labels, blue: gotos, green: conditions. Properties are shown as
stored, without field names.</small></p>
<table><tr><th>#</th><th>Step</th><th>Properties</th></tr>{"".join(row(*s) for s in steps)}</table>
<h2>Labels And Goto Targets</h2><table><tr><th>Label</th><th>Goto Count</th></tr>
{"".join(f"<tr><td>{e(l)}</td><td>{gotos.get(l, 0)}</td></tr>" for l in dict.fromkeys(labels))}</table>
</body></html>"""
    return page, {"steps": len(steps), "variables": len(variables), "labels": len(labels)}
