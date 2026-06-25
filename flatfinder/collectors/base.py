"""Shared collector utilities."""
import re


def extract_balanced(html: str, marker: str):
    """Return the JSON object/array literal that starts right after `marker`."""
    i = html.find(marker)
    if i < 0:
        return None
    j = i + len(marker)
    while j < len(html) and html[j] not in "[{":
        j += 1
    if j >= len(html):
        return None
    open_ch = html[j]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for k in range(j, len(html)):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return html[j:k + 1]
    return None


POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
OUTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b")


def guess_postcode(text: str) -> str:
    m = POSTCODE_RE.search(text or "")
    if m:
        return m.group(1).upper().replace("  ", " ")
    m = OUTCODE_RE.search(text or "")
    return m.group(1).upper() if m else ""
