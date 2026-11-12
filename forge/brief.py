"""Facts from the design brief alone, for tasks that come without facts.json.

The hidden parts ship only description.md, the eight views and context.png. Everything
after loading works on `task.facts`, so this module rebuilds the part of facts.json that
the brief supports:

    bounding_box_mm, volume_mm3, through_holes_genus, solids     from the "Envelope" line
    cylindrical_holes_and_bores                                  from the feature bullets

    facts_from_brief(text, views=None)     the facts dict, by rules only (no model)
    bores_from_brief(text, size)           the bore list on its own
    refine_with_model(llm, text, facts)    optional: one model call, checked against the brief
    compare_bores(mine, real)              match rate against a real facts.json (for tests)

Not derivable and never written: surface_area_mm2, faces, face_types. A bore is listed
only if the brief gives its diameter, its axis and where its axis runs; a guess here is a
cylinder cut into the part, so precision counts more than recall. A bore the brief only
names is still in the silhouettes, which the no-model pass uses anyway.
"""
from __future__ import annotations

import itertools
import json
import math
import re

NUM = r"\d+(?:\.\d+)?"
SOURCE = "brief"

_WORDS = {"no": 0, "zero": 0, "one": 1, "a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "sixteen": 16}


def normalise(text: str) -> str:
    """One spelling for the characters the briefs vary: hyphens, minus, times, spaces, cubed."""
    for ch in "‐‑‒–—−":
        text = text.replace(ch, "-")
    for ch in "    ":
        text = text.replace(ch, " ")
    text = text.replace("×", "x").replace("³", "^3").replace("≈", "~").replace("⌀", "Ø")
    return text.replace("**", "").replace("`", "")


# --- the envelope line ---------------------------------------------------------------------

def parse_envelope(text: str) -> dict:
    """{"bounding_box_mm", "volume_mm3", "through_holes_genus"}: whichever the brief states."""
    t = normalise(text)
    lines = t.splitlines()
    first = [ln for ln in lines if re.search(r"envelope", ln, re.I)] + [ln for ln in lines if re.search(r"bounding", ln, re.I)]
    out: dict = {}
    triple = rf"({NUM})\s*(?:mm)?\s*[x*]\s*({NUM})\s*(?:mm)?\s*[x*]\s*({NUM})\s*mm(?:\s*\(\s*([XYZ])\s*[x*,]\s*([XYZ])\s*[x*,]\s*([XYZ])\s*\))?"
    for ln in first + lines:
        m = re.search(triple, ln, re.I)
        if m:
            vals = [float(m.group(i)) for i in (1, 2, 3)]
            order = [g.lower() for g in m.groups()[3:]] if m.group(4) else ["x", "y", "z"]
            if sorted(order) == ["x", "y", "z"] and min(vals) > 0:
                out["bounding_box_mm"] = {k: v for k, v in sorted(zip(order, vals))}
                break
    for ln in first + lines:
        m = re.search(rf"volume\D{{0,24}}?({NUM}(?:,\d{{3}})*)\s*(cm|mm|m)\s*\^?\s*3", ln, re.I)
        if m:
            scale = {"cm": 1000.0, "mm": 1.0, "m": 1e9}[m.group(2).lower()]
            out["volume_mm3"] = round(float(m.group(1).replace(",", "")) * scale, 3)
            break
    count = r"(\d+|no|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    for ln in first + lines:
        m = re.search(count + r"\s+through[- ]?(?:passage|hole|opening)s?\b", ln, re.I)
        if m and not (ln not in first and not re.search(r"\b(total|in all|overall|only)\b", ln, re.I)):
            word = m.group(1).lower()
            out["through_holes_genus"] = int(word) if word.isdigit() else _WORDS[word]
            break
    return out


def box_from_views(views, text: str) -> dict:
    """Last resort when the brief states no envelope: the proportions of the part from its front
    and top views (each fits the bounding box into the image), scaled so the longest side is the
    largest millimetre figure in the brief, or 100 mm."""
    ratio = {"x": 1.0, "y": 1.0, "z": 1.0}
    try:
        import numpy as np

        from .vision import image_mask

        def extent(stem):
            path = next((v for v in views or [] if v.stem == stem), None)
            if path is None:
                return None
            mask = image_mask(path)
            cols, rows = np.where(mask.any(axis=0))[0], np.where(mask.any(axis=1))[0]
            return (float(np.ptp(cols) + 1), float(np.ptp(rows) + 1)) if len(cols) and len(rows) else None

        front, top = extent("view_0_front"), extent("view_4_top")       # (X, Z) and (X, Y) in pixels
        if front:
            ratio["z"] = front[1] / front[0]
        if top:
            ratio["y"] = top[1] / top[0]
        elif (left := extent("view_2_left")) and front:                    # (Y, Z)
            ratio["y"] = ratio["z"] * left[0] / left[1]
    except Exception:
        pass
    sizes = [float(n) for n in re.findall(rf"({NUM})\s*mm\b", normalise(text))]
    longest = max(sizes) if sizes else 100.0
    k = longest / max(ratio.values())
    return {a: round(max(v * k, 0.01), 2) for a, v in ratio.items()}


# --- bores from the feature bullets --------------------------------------------------------------

_DIA = re.compile(
    rf"(?:Ø\s*|\bd\s*=\s*|\b(?:dia|diam)\.?\s+|\bdiameter\s+(?:of\s+)?(?:~\s*)?|\binner bore\s+(?:of\s+)?)(?P<a>{NUM})(?:\s*mm)?"
    rf"|(?P<b>{NUM})\s*(?:mm)?[\s-]*(?:in\s+)?(?:diameter|dia\b)(?!\s*(?:of\s+)?~?\s*\d)", re.I)
_HOLE = r"through-?holes?|holes?|bores?|counterbored?|counterbores|recess(?:es)?|openings?|pockets?|concave|drilled|slot|window"
_SOLID = (r"boss(?:es)?|shaft|journals?|pins?|stem|discs?|ribs?|pads?|lobes?|outer|convex|flanges?|collars?|hub|rim|"
          r"section|sleeve|rounds?|rounded|fillets?|chamfers?|cap|dome|cone|conical|base|wire|coil|tube|plate|solid|"
          r"band|surface|ring|pitch|overall|bolt circle|head")
_KIND = re.compile(rf"\b(?:(?P<hole>{_HOLE})|(?P<solid>{_SOLID}))\b", re.I)
_AXIS_VEC = re.compile(rf"ax[ie]s\s+(?:direction|vector)?\s*~?\s*\(\s*([-+]?{NUM})\s*,\s*([-+]?{NUM})\s*,\s*([-+]?{NUM})\s*\)", re.I)
_AXIS = re.compile(
    r"ax[ie]s\s+(?:is\s+|are\s+|runs?\s+)?(?:along|in|parallel to|on|about)?\s*(?:the\s+)?([XYZ])\b(?!\s*[-/=]\s*[XYZ\d])"
    r"|\b([XYZ])[- ]ax[ie]s\b|\balong\s+(?:the\s+)?([XYZ])\b(?!\s*[-/=])|\bvertical\s+([XYZ])\b|\bhorizontal\s+\(?([XYZ])\)?(?=\s)"
    r"|\bcoaxial\s+with\s+(?:the\s+)?([XYZ])\b")
_RANGE = re.compile(rf"\b([XYZxyz])\s*=?\s*~?\s*({NUM})\s*(?:mm\s*)?(?:to|-)\s*(?:[XYZxyz]\s*=?\s*)?~?\s*({NUM})")
_LIST = rf"{NUM}(?:\s*mm)?(?:(?:\s+[a-z-]+)?\s*(?:/|&|\band\b)\s*~?\s*{NUM}(?:\s*mm)?(?!\s*(?:deep|long|thick|diameter|dia\b)))*"
_LABEL = re.compile(rf"\b([XYZ])\s*(?:pairs?\s*|positions?\s*|cent(?:re|er)s?\s*)?(?:=|~)\s*~?\s*\(?\s*({_LIST})")
_LABEL_PAIRS = re.compile(rf"\b([XYZ])\s+pairs?\s*((?:\(\s*{NUM}\s*&\s*{NUM}\s*\)\s*,?\s*(?:and\s*)?)+)")
_TUPLE_LABEL = re.compile(r"\(\s*([XYZ])\s*,\s*([XYZ])\s*(?:,\s*([XYZ])\s*)?\)")
_TUPLE = re.compile(rf"\(\s*({NUM})\s*,\s*({NUM})\s*(?:,\s*({NUM})\s*)?\)")
_LENGTH = [re.compile(p, re.I) for p in (
    rf"(?:depth|deep|length|long)\s*(?:of\s+)?(?:is\s+)?~?\s*({NUM})",
    rf"({NUM})\s*mm[\s-]*(?:deep|long)\b",
    rf"through\s+the\s+(?:full\s+)?({NUM})\s*mm",
    rf"^\s*\(\s*~?\s*({NUM})\s*(?:mm)?\s*(?:deep|long)?\s*\)",
    rf"\bshallow\s+\(\s*({NUM})\s*mm\s*\)",
    rf"\b(?:through|holes?|bores?)\s*\(\s*~?\s*({NUM})\s*mm\s*\)",
)]
_THROUGH = re.compile(r"\bthrough\b|\bthrough-|full\s+(?:\d[\d.]*\s*(?:mm\s+)?)?(?:width|length|height|thickness|extent|depth)|all the way", re.I)
_NOT_THROUGH = re.compile(r"(?:not|n't|without|never)\s+(?:\w+\s+){0,2}through|\bblind\b", re.I)
_COAXIAL = re.compile(r"coaxial|concentric|same axis", re.I)
_FACE_WORD = {"bottom": ("Z", 0), "top": ("Z", 1), "front": ("Y", 0), "back": ("Y", 1), "rear": ("Y", 1),
              "left": ("X", 0), "right": ("X", 1)}


def _bullets(text: str) -> list[tuple[str, list[str]]]:
    """[(bullet, [sub-bullets])] of the brief. A line that continues a bullet is joined to it."""
    out: list[tuple[str, list[str]]] = []
    last = None            # "top" or "child": where a continuation line goes
    for line in text.splitlines():
        m = re.match(r"^(\s*)[-*•]\s+(.*)$", line)
        if m and not m.group(1):
            out.append((m.group(2).strip(), []))
            last = "top"
        elif m and out:
            out[-1][1].append(m.group(2).strip())
            last = "child"
        elif line.strip() and out and last and line[:1] in " \t":
            if last == "top":
                out[-1] = (out[-1][0] + " " + line.strip(), out[-1][1])
            else:
                out[-1][1][-1] += " " + line.strip()
        else:
            last = None
    return out


def _spans(s: str, pattern: str) -> list[tuple[int, int]]:
    """(start, end) of the pieces of `s` between matches of `pattern`."""
    cuts = [0] + [m.end() for m in re.finditer(pattern, s)] + [len(s)]
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]


def _span_of(spans, pos: int) -> tuple[int, int]:
    return next(((a, b) for a, b in spans if a <= pos < b), spans[-1] if spans else (0, 0))


def _axis_in(s: str):
    """The first axis named in `s`: 'X' / 'Y' / 'Z', or a direction written as '(a, b, c)'."""
    vec, m = _AXIS_VEC.search(s), _AXIS.search(s)
    if vec and (not m or vec.start() <= m.start()):
        v = [float(g) for g in vec.groups()]
        if any(abs(c) > 1e-6 for c in v):
            big = [i for i, c in enumerate(v) if abs(c) > 0.999 * math.sqrt(sum(c * c for c in v))]
            return "XYZ"[big[0]] if big else "(" + ", ".join(f"{c:.2f}" for c in v) + ")"
    return next(g for g in m.groups() if g) if m else None


def _length_in(s: str) -> float | None:
    best = None
    for rx in _LENGTH:
        m = rx.search(s)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), float(m.group(1)))
    return best[1] if best else None


def _terms(s: str, axis: str | None) -> tuple[list[tuple[tuple, list[tuple]]], dict]:
    """Coordinates stated in `s`, in order: [(labels, [values])], e.g. (("X",), [(9.5,)]) or
    (("Y", "Z"), [(210.21, 387.12), (131.18, 466.15)]). Also {axis letter: (lo, hi)} ranges."""
    s = _AXIS_VEC.sub(lambda m: " " * len(m.group(0)), s)
    found: list[tuple[int, tuple, list[tuple]]] = []
    ranges: dict = {}

    def blank(m):
        return " " * len(m.group(0))

    for m in _RANGE.finditer(s):
        lo, hi = float(m.group(2)), float(m.group(3))
        if hi > lo:
            ranges.setdefault(m.group(1).upper(), (lo, hi))
    s = _RANGE.sub(lambda m: blank(m) if float(m.group(3)) > float(m.group(2)) else m.group(0), s)
    for m in _LABEL_PAIRS.finditer(s):
        found.append((m.start(), (m.group(1),), [(float(n),) for n in re.findall(NUM, m.group(2))]))
    s = _LABEL_PAIRS.sub(blank, s)
    labels = None
    marks = [(m.start(), "label", m) for m in _TUPLE_LABEL.finditer(s)] + [(m.start(), "tuple", m) for m in _TUPLE.finditer(s)]
    transverse = tuple(a for a in "XYZ" if a != axis) if axis in ("X", "Y", "Z") else None
    for pos, kind, m in sorted(marks, key=lambda x: x[0]):
        if kind == "label":
            labels = tuple(g for g in m.groups() if g)
            continue
        vals = tuple(float(g) for g in m.groups() if g is not None)
        lab = labels if labels and len(labels) == len(vals) else ("X", "Y", "Z") if len(vals) == 3 else transverse
        if lab is None:
            continue
        if found and found[-1][1] == lab and found[-1][0] < 0:
            found[-1][2].append(vals)
        else:
            found.append((-pos - 1, lab, [vals]))        # negative marks "a tuple list still open"
    found = [(abs(p) - (1 if p < 0 else 0), lab, vals) for p, lab, vals in found]
    s = _TUPLE.sub(blank, s)
    for m in _LABEL.finditer(s):
        if m.group(1) == axis and not re.search(r"cent(?:re|er)(?:s|d|ed)?\s+(?:at\s+|on\s+)?\(?\s*$", s[:m.start()], re.I):
            continue        # "from the hub face (Z = 0)": a place along the bore, not its midpoint
        found.append((m.start(), (m.group(1),), [(float(n),) for n in re.findall(NUM, m.group(2))]))
    return [(lab, vals) for _, lab, vals in sorted(found, key=lambda x: x[0])], ranges


def _points(terms: list[tuple[tuple, list[tuple]]]) -> list[dict]:
    """Partial centres {axis letter: mm} from the coordinate terms of one piece of text.
    "X = 1, Z = 2 and X = 3, Z = 4" is two points; "Z = 2, X = 1 / 3" is the grid of both."""
    if not terms:
        return []

    def grid(group):
        merged: dict[tuple, list[tuple]] = {}
        for lab, vals in group:
            merged.setdefault(lab, [])
            merged[lab] += [v for v in vals if v not in merged[lab]]
        pts = []
        for combo in itertools.product(*merged.values()):
            p: dict = {}
            for lab, vals in zip(merged.keys(), combo):
                p.update(dict(zip(lab, vals)))
            pts.append(p)
        return pts

    groups, seen = [[]], set()
    for lab, vals in terms:
        if seen & set(lab):
            groups.append([])
            seen = set()
        groups[-1].append((lab, vals))
        seen |= set(lab)
    sets = [frozenset(a for lab, _ in g for a in lab) for g in groups]
    if len(groups) > 1 and len(set(sets)) == 1 and len(sets[0]) >= 2:
        pts = [p for g in groups for p in grid(g)]
    else:
        pts = grid(terms)
    out = []
    for p in pts:
        if p not in out:
            out.append(p)
    return out


def _face_hints(s: str, size) -> dict:
    """{axis letter: 0 or 1}: the bounding-box face (min or max) that `s` says a feature is on."""
    out: dict = {}
    for m in re.finditer(r"([+-])\s?([XYZ])\b(?!\s*[-/]\s*[XYZ])\s*(?:\([^)]*\)\s*)?(?:[a-z]+\s+){0,2}(?:face|side|end|edge)\b", s):
        out.setdefault(m.group(2), 1 if m.group(1) == "+" else 0)
    for m in re.finditer(r"\b(min|minimum|max|maximum)[- ]([XYZ])\b", s, re.I):
        out.setdefault(m.group(2), 1 if m.group(1).lower().startswith("max") else 0)
    for m in re.finditer(rf"\b([XYZ])\s*=\s*({NUM})\s*(?:mm\s*)?(?:[a-z]+\s+)?(?:face|side|end|edge)\b", s):
        k, v = "XYZ".index(m.group(1)), float(m.group(2))
        if v < 1e-6 or abs(v - size[k]) < 0.002 * size[k] + 0.02:
            out.setdefault(m.group(1), 0 if v < 1e-6 else 1)
    for m in re.finditer(r"\b(bottom|top|front|back|rear|left|right)\s+(?:\([^)]*\)\s*)?face\b", s, re.I):
        axis, side = _FACE_WORD[m.group(1).lower()]
        out.setdefault(axis, side)
    return out


def _kind(s: str, start: int, end: int, sentence: tuple[int, int]) -> str | None:
    """'hole' or 'solid' for the diameter at s[start:end]: the word right after it, else the
    nearest word before it in the sentence."""
    after = s[end:sentence[1]]
    m = re.match(r"\s*(?:mm\s*)?(?:\(([^)]*)\)\s*)?((?:[A-Za-z-]+\s*){0,3})", after)
    if m:
        for piece in ((m.group(2) or ""), (m.group(1) or "")):
            hits = list(_KIND.finditer(piece))
            if hits:
                return "hole" if any(h.group("hole") for h in hits) and not hits[0].group("solid") else \
                    ("hole" if hits[-1].group("hole") else "solid")
    hits = list(_KIND.finditer(s[sentence[0]:start]))
    if hits:
        return "hole" if hits[-1].group("hole") else "solid"
    return None


class _Mention:
    def __init__(self, **kw):
        self.dia = self.kind = self.axis = self.length = None
        self.through = False
        self.points: list[dict] = []
        self.ranges: dict = {}
        self.hints: dict = {}
        self.coaxial = False
        self.share = None          # another mention whose centres this one takes
        self.count = None
        self.label = None
        self.__dict__.update(kw)


def _count_before(s: str) -> int | None:
    m = re.search(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\b\s*(?:x\s*)?(?:[a-z-]+\s+){0,5}$", s.rstrip() + " ", re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else _WORDS.get(w)


def _parse_bullet(s: str, size, parent: _Mention | None = None) -> list[_Mention]:
    """Every diameter named in one bullet, with what the text around it says about it."""
    sentences = _spans(s, r"(?<=[.])\s+(?=[A-Z(])")
    clauses = _spans(s, r"(?<=[.;])\s+(?=[A-Za-z(])")
    found = [(m.start(), m.end(), float(m.group("a") or m.group("b"))) for m in _DIA.finditer(s)]
    if not found and parent is not None:
        found = [(0, 0, parent.dia)]          # a sub-bullet that only places its parent's bores
    prefix = s[:found[0][0]] if found else s
    out: list[_Mention] = []
    for i, (a, b, dia) in enumerate(found):
        nxt = found[i + 1][0] if i + 1 < len(found) else len(s)
        prev = found[i - 1][1] if i else 0
        sent, clause = _span_of(sentences, a), _span_of(clauses, a)
        post_clause, post_ext = s[b:min(nxt, clause[1])], s[b:nxt]
        pre_clause = s[max(prev, clause[0]):a]
        virtual = a == b
        kind = parent.kind if virtual else "hole" if "bore" in s[a:b].lower() else _kind(s, a, b, sent)
        if kind is None and any(o.kind == "hole" and abs(o.dia - dia) < 1e-6 for o in out):
            kind = "hole"
        if kind is None and parent is not None and abs(dia - parent.dia) < 1e-6:
            kind = parent.kind
        me = _Mention(dia=dia, kind=kind, pos=a, sent=sent)
        # axis: after the diameter, before it in the clause, an earlier diameter of the sentence,
        # the bullet's opening words, the rest of the bullet, the parent bullet
        me.axis = _axis_in(post_clause) or _axis_in(pre_clause)
        if me.axis is None:
            earlier = [o for o in out if o.sent == sent and o.axis]
            me.axis = earlier[-1].axis if earlier else (_axis_in(prefix) or _axis_in(post_ext) or _axis_in(s))
        if me.axis is None and parent is not None:
            me.axis = parent.axis
        label = re.match(r"\s*([A-Za-z][A-Za-z ]{2,24}?)\s*[:,]", s)
        me.label = label.group(1).strip().lower() if label else None
        # length and through
        near = post_clause if not virtual else s
        me.length = _length_in(near)
        if me.length is None and not virtual and nxt == len(s) or (me.length is None and i == 0 and len(found) == 1):
            me.length = _length_in(post_ext)
        if me.length is None:
            me.length = _length_in(pre_clause)
        both = pre_clause + " " + post_clause
        me.through = bool(_THROUGH.search(_NOT_THROUGH.sub(" ", both))) and not re.search(r"\bblind\b", both, re.I)
        if not me.through and not _NOT_THROUGH.search(both) and (i == 0 or me.length is None):
            me.through = bool(_THROUGH.search(_NOT_THROUGH.sub(" ", prefix)))
        if not me.through and not _NOT_THROUGH.search(post_ext) and me.length is None and len(found) == 1:
            me.through = bool(_THROUGH.search(_NOT_THROUGH.sub(" ", post_ext)))
        me.coaxial = bool(_COAXIAL.search(both))
        me.count = _count_before(pre_clause) if not virtual else None
        # where: the clause, then the rest of the bullet up to the next diameter
        ax = me.axis if me.axis in ("X", "Y", "Z") else None
        need = {c for c in "XYZ" if c != ax} if ax else set("XYZ")
        terms, me.ranges = _terms(post_clause if not virtual else s, ax)
        pts = _points(terms)
        if not pts or not all(need <= set(p) for p in pts):
            terms2, ranges2 = _terms(post_ext if not virtual else s, ax)
            pts2 = _points(terms2)
            if pts2 and all(need <= set(p) for p in pts2) or (not pts and pts2):
                pts = pts2
            me.ranges = {**ranges2, **me.ranges}
        me.points = pts
        me.hints = {**_face_hints(pre_clause, size), **_face_hints(post_clause, size)}
        out.append(me)
    # centres shared inside a sentence: "Ø65 (9 mm) and Ø68.5 (2 mm) counterbore at ...",
    # "a Ø11 hole at (...), counterbored Ø13", and the bullet's opening words
    head_axis = _axis_in(prefix)
    head_pts = _points(_terms(prefix, head_axis if head_axis in ("X", "Y", "Z") else None)[0]) if found else []
    for i, me in enumerate(out):
        ax = me.axis if me.axis in ("X", "Y", "Z") else None
        need = {c for c in "XYZ" if c != ax} if ax else set("XYZ")
        if me.points and all(need <= set(p) for p in me.points):
            continue
        later = [o for o in out[i + 1:] if o.sent == me.sent and o.points and all(need <= set(p) for p in o.points)]
        earlier = [o for o in out[:i] if o.sent == me.sent and o.points and all(need <= set(p) for p in o.points)]
        between = s[me.pos:later[0].pos] if later else ""
        if later and not re.search(r"[;.]\s", between) and later[0].axis == me.axis and not me.points:
            me.share = later[0]
        elif earlier and earlier[-1].axis == me.axis and not me.points:
            me.share = earlier[-1]
        elif head_pts and all(need <= set(p) for p in head_pts):
            me.points = [{**p, **q} for p in head_pts for q in (me.points or [{}])]
        elif parent is not None and parent.points and me.points:
            me.points = [{**q, **p} for p in me.points for q in parent.points]
        elif parent is not None and parent.points and not me.points and all(need <= set(p) for p in parent.points):
            me.points = [dict(p) for p in parent.points]
    if parent is not None:
        for me in out:
            if abs(me.dia - parent.dia) < 1e-6:
                me.length = me.length if me.length is not None else parent.length
                me.through = me.through or parent.through
                me.hints = {**parent.hints, **me.hints}
                me.ranges = {**parent.ranges, **me.ranges}
                if me.points and parent.points and len(parent.points) == 1:
                    me.points = [{**parent.points[0], **p} for p in me.points]
    return out


def _unit(axis) -> tuple[float, float, float] | None:
    if axis in ("X", "Y", "Z"):
        return tuple(1.0 if c == axis else 0.0 for c in "XYZ")
    nums = [float(n) for n in re.findall(r"[-+]?\d+(?:\.\d+)?", str(axis))]
    norm = math.sqrt(sum(n * n for n in nums)) if len(nums) == 3 else 0.0
    return tuple(n / norm for n in nums) if norm > 1e-9 else None


def _chord(centre, direction, size) -> tuple[float, float]:
    """Distance from `centre` to the bounding box along +direction and along -direction."""
    ahead = behind = math.inf
    for p, d, s in zip(centre, direction, size):
        if d > 1e-9:
            ahead, behind = min(ahead, (s - p) / d), min(behind, p / d)
        elif d < -1e-9:
            ahead, behind = min(ahead, -p / d), min(behind, (p - s) / d)
    return max(ahead, 0.0), max(behind, 0.0)


def bores_from_brief(text: str, size) -> list[dict]:
    """The bores the brief places exactly, in the schema of facts.json
    (diameter, axis, count, lengths, centres = bore midpoints from the bounding-box min corner)."""
    size = [float(v) for v in size]
    mentions: list[_Mention] = []
    labelled_axis: dict[str, str] = {}
    for top, children in _bullets(normalise(text)):
        tops = _parse_bullet(top, size)
        mentions += tops
        lead = next((m for m in tops if m.kind == "hole"), tops[0] if tops else None)
        for child in children:
            subs = _parse_bullet(child, size, lead)
            for m in subs:        # "Upper bank, axis direction (...)" names an axis a later bullet reuses
                own = _axis_in(child)
                if own and m.label:
                    labelled_axis.setdefault(m.label, own)
                elif m.label in labelled_axis and (lead is None or m.axis == lead.axis):
                    m.axis = labelled_axis[m.label]
            mentions += subs

    def complete(m: _Mention) -> list[dict]:
        ax = m.axis if m.axis in ("X", "Y", "Z") else None
        need = {c for c in "XYZ" if c != ax} if ax else set("XYZ")
        pts = []
        for p in m.points:
            p = dict(p)
            for c in need - set(p):                     # "on the -Y face": the missing coordinate is that face
                if c in m.hints and len(need - set(p)) == 1 and m.kind == "hole":
                    p[c] = size["XYZ".index(c)] * m.hints[c]
            if need <= set(p) and all(-0.01 * max(size) <= p[c] <= size["XYZ".index(c)] * 1.01 + 0.01 for c in p):
                pts.append(p)
        return pts

    # the line each cylinder lies on, for "coaxial with ..." and for parts with one axis only
    lines: list[tuple[str, tuple]] = []
    resolved: list[tuple[_Mention, list[dict]]] = []
    for m in mentions:
        pts = complete(m) if m.axis else []
        if not pts and m.share is not None:
            src = next((p for o, p in resolved if o is m.share), None) or complete(m.share)
            pts = [dict(p) for p in src]
        if not pts and m.axis and m.coaxial:
            same = [(o, p) for o, p in resolved if p and o.axis == m.axis]
            named = [(o, p) for o, p in same if any(abs(o.dia - n.dia) < 1e-6 for n in mentions
                                                    if n is not m and n.sent == m.sent and abs(n.pos - m.pos) < 160)]
            src = (named or same)[-1:] if (named or same) else []
            pts = [dict(p) for p in src[0][1]] if src else []
            if pts and m.axis in ("X", "Y", "Z") and not (m.length is not None and src[0][0].length == m.length):
                for p in pts:
                    p.pop(m.axis, None)
        resolved.append((m, pts))
        if m.axis in ("X", "Y", "Z"):
            for p in pts:
                key = (m.axis, tuple(p[c] for c in "XYZ" if c != m.axis))
                if not any(k[0] == key[0] and max(abs(u - v) for u, v in zip(k[1], key[1])) < 0.06 for k in lines):
                    lines.append(key)
    if len(lines) == 1:                       # a turned part: every cylinder along that axis is on it
        ax, (u, v) = lines[0]
        a, b = [c for c in "XYZ" if c != ax]
        resolved = [(m, pts or ([{a: u, b: v}] if m.axis == ax and m.kind == "hole" and not m.points else []))
                    for m, pts in resolved]

    flat_text = normalise(text)
    planes = {}
    for k, a in enumerate("XYZ"):       # planes normal to each axis that the brief names, and the box faces
        named = {float(v) for v in re.findall(rf"\b{a}\s*=\s*({NUM})", flat_text)}
        planes[a] = sorted({v for v in named if v <= size[k] + 0.011} | {0.0, size[k]})
    bores: list[dict] = []
    for m, pts in resolved:
        if m.kind != "hole" or not m.axis or not pts or not (0 < m.dia <= 1.5 * max(size)):
            continue
        direction = _unit(m.axis)
        if direction is None:
            continue
        if m.count and m.count > 1 and len(pts) == 1:
            continue                           # "six coaxial bores", "two overlapping bores" at one place: not placed
        for p in pts:
            if m.axis in ("X", "Y", "Z"):
                k = "XYZ".index(m.axis)
                length, mid = m.length, p.get(m.axis)
                known = mid is not None and length is not None
                if m.axis in m.ranges and m.ranges[m.axis][1] <= size[k] * 1.01 + 0.01:
                    lo, hi = m.ranges[m.axis]
                    length, mid = (hi - lo if length is None or abs(length - (hi - lo)) < 0.02 * (hi - lo) + 0.05 else length), (lo + hi) / 2
                    known = True
                if length is None and m.through:
                    length, mid = size[k], size[k] / 2
                if length is None or length <= 0:
                    continue
                length = min(length, size[k])
                if mid is None and length < size[k] - 0.05:
                    # "through the 14.0 mm plate", and elsewhere "front face at Y = 0, rear face at Y = 14":
                    # if exactly one pair of planes the brief names along this axis is that far apart, the
                    # bore runs between them
                    pairs = [(lo, hi) for lo in planes[m.axis] for hi in planes[m.axis]
                             if abs(hi - lo - length) <= 0.011 and hi > lo]
                    if len(pairs) == 1 and m.axis not in m.hints:
                        mid, known = sum(pairs[0]) / 2, True
                if mid is None:
                    side = m.hints.get(m.axis)
                    mid = size[k] / 2 if side is None else (length / 2 if side == 0 else size[k] - length / 2)
                centre = [p[c] if c != m.axis else mid for c in "XYZ"]
            else:
                centre = [p[c] for c in "XYZ"]
                ahead, behind = _chord(centre, direction, size)
                length = m.length if m.length else (ahead + behind if m.through else None)
                if length is None:
                    continue
                known = bool(m.length)
            bores.append({"diameter": m.dia, "axis": m.axis, "length": round(length, 3),
                          "centre": [round(c, 3) for c in centre], "ends": "stated" if known else "assumed"})
    return group_bores(bores)


def group_bores(bores: list[dict]) -> list[dict]:
    """[{diameter, axis, length, centre}] -> facts.json groups, duplicates dropped."""
    groups: dict[tuple, dict] = {}
    for b in bores:
        ends = b.get("ends", "stated")
        d = _unit(b["axis"]) or (0.0, 0.0, 0.0)

        def off_line(c):        # distance of centre c from this bore's axis line
            delta = [p - q for p, q in zip(c, b["centre"])]
            along = sum(p * q for p, q in zip(delta, d))
            return math.sqrt(max(sum(p * p for p in delta) - along * along, 0.0)), abs(along)

        clash = False
        for k, g in groups.items():
            if k[:2] != (round(b["diameter"], 3), b["axis"]):
                continue
            for i, c in enumerate(g["centres"]):
                across, along = off_line(c)
                if across < 0.5 and (along < 0.5 or "assumed" in (ends, k[2])):
                    clash = True          # the same bore named twice: the one with stated ends stays
                    if k[2] == "assumed" and ends == "stated":
                        del g["centres"][i], g["lengths"][i]
                        clash = False
                    break
        if clash:
            continue
        g = groups.setdefault((round(b["diameter"], 3), b["axis"], ends),
                              {"diameter": b["diameter"], "axis": b["axis"], "count": 0, "lengths": [], "centres": [], "ends": ends})
        g["centres"].append(b["centre"])
        g["lengths"].append(b["length"])
    out = []
    for g in groups.values():
        if not g["centres"]:
            continue
        g["count"] = len(g["centres"])
        if len(set(g["lengths"])) == 1:
            g["lengths"] = g["lengths"][:1]
        out.append(g)
    return sorted(out, key=lambda g: -g["diameter"])


# --- the facts ---------------------------------------------------------------------------

def facts_from_brief(text: str, views=None) -> dict:
    """facts.json rebuilt from the brief. Always has a bounding box (so every task gets a
    solid): the stated envelope, else the views' proportions scaled by the brief, else 100 mm."""
    env = parse_envelope(text or "")
    notes = []
    box = env.get("bounding_box_mm")
    if not box:
        box = box_from_views(views, text or "")
        notes.append("no envelope in the brief: bounding box estimated from the views")
    facts: dict = {"bounding_box_mm": box}
    if env.get("volume_mm3"):
        facts["volume_mm3"] = env["volume_mm3"]
    else:
        notes.append("no volume in the brief")
    facts["solids"] = 1
    try:
        bores = bores_from_brief(text or "", [box["x"], box["y"], box["z"]])
    except Exception as exc:        # a brief written another way must not cost the part
        bores = []
        notes.append(f"bore parser failed: {type(exc).__name__}: {exc}")
    if "through_holes_genus" in env:
        facts["through_holes_genus"] = env["through_holes_genus"]
    else:
        facts["through_holes_genus"] = 0
        notes.append("no through-passage count in the brief: 0 assumed")
    facts["cylindrical_holes_and_bores"] = bores
    facts["_source"] = SOURCE
    facts["_note"] = "parsed from description.md (no facts.json); positions in mm from the bounding-box min corner"
    if notes:
        facts["_warnings"] = notes
    return facts


# --- optional: one model call ------------------------------------------------------------------

BRIEF_SYSTEM = """\
You extract cylindrical holes and bores from a design brief of one mechanical part.
Frame: millimetres, origin at the minimum corner of the part's bounding box, axes X Y Z.
Reply with one JSON object and nothing else:
{"bores": [{"diameter": 6.75, "axis": "Y", "length": 14.0, "through": true,
            "centres": [[9.5, 7.0, 6.35], [9.5, 7.0, 44.45]]}]}
Rules:
- Only holes, bores, counterbores and cylindrical recesses (material removed). Never bosses,
  shafts, pins, outer diameters, fillets or rounds.
- "axis" is "X", "Y" or "Z", or a direction "(a, b, c)" if the brief gives one.
- "centres" are the MIDPOINTS of each bore, three numbers each. The two coordinates across
  the axis must be stated in the brief (or follow from "coaxial with" a feature whose
  position is stated). The coordinate along the axis is the middle of the bore's length:
  for a bore through the whole part use half the envelope on that axis; for a blind hole of
  depth d entering at a face use d/2 from that face.
- "length" is the bore's length or depth in mm; for a through bore with no stated length use
  the envelope on that axis.
- Leave a bore out if the brief does not say where it is. Do not invent numbers: every
  diameter and every across-axis coordinate must appear in the brief.
- One entry per group of equal bores (same diameter, axis and length)."""


def parse_model_bores(reply: str) -> list[dict]:
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for g in data.get("bores", []) if isinstance(data, dict) else []:
        try:
            centres = [[float(v) for v in c] for c in g.get("centres", []) if len(c) == 3]
            out.append({"diameter": float(g["diameter"]), "axis": str(g["axis"]).strip(), "length": float(g["length"]),
                        "centres": centres})
        except Exception:
            continue
    return out


def _stated(value: float, numbers: set[float]) -> bool:
    return any(abs(value - n) <= 0.006 + 1e-4 * abs(n) for n in numbers)


def refine_with_model(llm, text: str, facts: dict, timeout: float = 60.0) -> dict:
    """Add bores a model reads out of the brief to facts parsed by rules. The rules win where
    both place a bore (same diameter and axis line). A model bore is taken only if its
    diameter and both across-axis coordinates are numbers written in the brief (or half of the
    envelope), it lies inside the box and its length fits. Returns new facts; never raises."""
    try:
        box = facts["bounding_box_mm"]
        size = [float(box["x"]), float(box["y"]), float(box["z"])]
        reply = llm.complete(BRIEF_SYSTEM, [{"type": "text", "text": "DESIGN BRIEF:\n" + text.strip()}], timeout=timeout)
        numbers = {float(n) for n in re.findall(NUM, normalise(text))}
        numbers |= {s / 2 for s in size} | {0.0} | set(size)
        have = [(g["diameter"], g["axis"], c) for g in facts.get("cylindrical_holes_and_bores", []) for c in g["centres"]]
        flat = [{"diameter": g["diameter"], "axis": g["axis"], "length": (g["lengths"][i] if len(g["lengths"]) == len(g["centres"]) else max(g["lengths"])),
                 "centre": c} for g in facts.get("cylindrical_holes_and_bores", []) for i, c in enumerate(g["centres"])]
        added = 0
        for g in parse_model_bores(reply):
            direction = _unit(g["axis"])
            if direction is None or not _stated(g["diameter"], numbers) or not (0 < g["diameter"] <= 1.5 * max(size)):
                continue
            letter = g["axis"] if g["axis"] in ("X", "Y", "Z") else None
            for c in g["centres"]:
                across = [k for k in range(3) if letter is None or "XYZ"[k] != letter]
                if not all(_stated(c[k], numbers) for k in across):
                    continue
                if not all(-0.01 <= c[k] <= size[k] + 0.01 for k in range(3)):
                    continue
                if letter and (g["length"] <= 0 or g["length"] > size["XYZ".index(letter)] * 1.01 + 0.01):
                    continue
                if any(abs(d - g["diameter"]) < 0.01 and a == g["axis"] and
                       all(abs(c[k] - h[k]) < 0.5 for k in across) for d, a, h in have):
                    continue
                flat.append({"diameter": g["diameter"], "axis": g["axis"], "length": g["length"], "centre": [round(v, 3) for v in c]})
                have.append((g["diameter"], g["axis"], c))
                added += 1
        if not added:
            return facts
        out = dict(facts)
        out["cylindrical_holes_and_bores"] = group_bores(flat)
        out["_note"] = facts.get("_note", "") + f"; {added} bore(s) added by the model"
        return out
    except Exception as exc:
        print(f"brief: model extraction skipped ({type(exc).__name__}: {exc})", flush=True)
        return facts


# --- comparing with a real facts.json ---------------------------------------------------------------

def _flat(groups: list[dict]) -> list[dict]:
    out = []
    for g in groups or []:
        for i, c in enumerate(g.get("centres") or []):
            lengths = g.get("lengths") or [0.0]
            out.append({"diameter": g["diameter"], "axis": g["axis"], "centre": c,
                        "length": lengths[i] if len(lengths) == len(g["centres"]) else max(lengths)})
    return out


def compare_bores(mine: list[dict], real: list[dict], tol: float = 1.0) -> dict:
    """How the parsed bores match the real ones. A bore matches on diameter (0.05 mm), axis
    direction and its axis line (the two across-axis coordinates within `tol`); `centre` also
    asks for the midpoint within `tol`, `length` for the length within `tol`."""
    a, b = _flat(mine), _flat(real)
    used: set[int] = set()
    line = centre = length = 0
    for m in a:
        dm = _unit(m["axis"])
        for j, r in enumerate(b):
            dr = _unit(r["axis"])
            if j in used or dm is None or dr is None or abs(m["diameter"] - r["diameter"]) > 0.05:
                continue
            if abs(sum(p * q for p, q in zip(dm, dr))) < 0.995:
                continue
            delta = [p - q for p, q in zip(m["centre"], r["centre"])]
            along = sum(p * q for p, q in zip(delta, dr))
            across = math.sqrt(max(sum(p * p for p in delta) - along * along, 0.0))
            if across <= tol:
                used.add(j)
                line += 1
                centre += abs(along) <= tol
                length += abs(m["length"] - r["length"]) <= tol
                break
    return {"parsed": len(a), "real": len(b), "matched": line, "centre": centre, "length": length,
            "false": len(a) - line, "missed": len(b) - line}
