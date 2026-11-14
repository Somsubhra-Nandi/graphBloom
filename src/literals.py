"""Literal handling shared by ingest and (later) gold-evidence matching.

normalize_literal(raw) returns {"raw", "norm", "approx"}:
  norm   ISO yyyy-mm-dd, yyyy-mm or yyyy (a leading '-' for BC years), or "" if the string is not a date
  approx True when the text marks the date as approximate ("c. 1732", "circa 1250", "1732?")
The raw string is always kept by the caller; `norm` is only for comparison.
"""
import calendar
import re

MONTHS = {}
for i, names in enumerate(
    ["january jan", "february feb", "march mar", "april apr", "may", "june jun", "july jul", "august aug", "september sep sept", "october oct", "november nov", "december dec"], 1
):
    for n in names.split():
        MONTHS[n] = i
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))

_APPROX = re.compile(r"^(circa|ca\.?|c\.?|about|approximately|approx\.?|around|~)(?=\s|\d)\s*", re.I)
_BC = re.compile(r"\s*(bce?|b\.c\.e?\.?|b\.c\.)$", re.I)
_ISO = re.compile(r"^(\d{3,4})-(\d{2})(?:-(\d{2}))?$")
_YEAR = re.compile(r"^(\d{1,4})$")
_DMY = re.compile(rf"^(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+(\d{{1,4}})$", re.I)
_MDY = re.compile(rf"^({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{1,4}})$", re.I)
_MY = re.compile(rf"^({_MON})\.?,?\s+(\d{{1,4}})$", re.I)


def _fmt(year, month=None, day=None, bc=False):
    if month is not None and not 1 <= month <= 12:
        return ""
    if day is not None and not 1 <= day <= calendar.monthrange(year if year else 1, month)[1]:
        return ""
    s = f"{'-' if bc else ''}{year:04d}"
    if month:
        s += f"-{month:02d}"
    if day:
        s += f"-{day:02d}"
    return s


def normalize_literal(raw):
    s = (raw or "").strip()
    approx = False
    m = _APPROX.match(s)
    if m:
        approx, s = True, s[m.end():]
    if s.endswith("?"):
        approx, s = True, s[:-1].strip()
    bc = False
    m = _BC.search(s)
    if m:
        bc, s = True, s[: m.start()].strip()

    norm = ""
    if m := _ISO.match(s):
        norm = _fmt(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, bc)
    elif m := _DMY.match(s):
        norm = _fmt(int(m[3]), MONTHS[m[2].lower()], int(m[1]), bc)
    elif m := _MDY.match(s):
        norm = _fmt(int(m[3]), MONTHS[m[1].lower()], int(m[2]), bc)
    elif m := _MY.match(s):
        norm = _fmt(int(m[2]), MONTHS[m[1].lower()], None, bc)
    elif m := _YEAR.match(s):
        norm = _fmt(int(m[1]), None, None, bc)
    return {"raw": raw, "norm": norm, "approx": approx and bool(norm)}
