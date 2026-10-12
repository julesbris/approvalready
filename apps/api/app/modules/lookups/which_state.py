"""Which state an address someone typed is in, from the state they wrote or its postcode.

Address search asks only that state's services when it can tell, and every state we cover
when it can't.
"""

from __future__ import annotations

import re

from app.modules.lookups.spatial import STATES

_NAMES = {name.upper(): code for code, name in STATES.items()}
_WORD = re.compile(r"[A-Za-z]+")
_POSTCODE = re.compile(r"\b(\d{4})\b\s*$")

# Australia Post's postcode ranges for each state (Australian Antarctic Territory, Jervis
# Bay and the other territories' oddities aside).
_RANGES: tuple[tuple[int, int, str], ...] = (
    (200, 299, "ACT"),
    (800, 999, "NT"),
    (1000, 2599, "NSW"),
    (2600, 2618, "ACT"),
    (2619, 2899, "NSW"),
    (2900, 2920, "ACT"),
    (2921, 2999, "NSW"),
    (3000, 3999, "VIC"),
    (4000, 4999, "QLD"),
    (5000, 5999, "SA"),
    (6000, 6999, "WA"),
    (7000, 7999, "TAS"),
    (8000, 8999, "VIC"),
    (9000, 9999, "QLD"),
)


def state_for_postcode(postcode: str) -> str | None:
    number = int(postcode)
    return next((s for low, high, s in _RANGES if low <= number <= high), None)


def state_in_text(text: str) -> str | None:
    """The state named in an address ("... Parramatta NSW 2150", "... Victoria"), else the
    state its trailing postcode belongs to, else None."""
    upper = text.upper()
    words = [w.upper() for w in _WORD.findall(text)]
    for code in STATES:
        if code in words:
            return code
    for name, code in _NAMES.items():
        if name in upper:
            return code
    match = _POSTCODE.search(text.strip())
    if match and not re.fullmatch(r"\d{4}", text.strip()):
        return state_for_postcode(match.group(1))
    return None
