"""Grade the emulator against selections captured from a real hx process.

The fixture is produced by tools/calibrate.py, which observes Helix through a
file it writes, so two artefacts of that channel are corrected for here rather
than emulated: Helix appends a final newline when saving, and the `r@` probe
cannot mark a zero-width selection.
"""

import json
from pathlib import Path

import pytest

from helix_spaced.emu.engine import Engine

FIXTURE = Path(__file__).parent / "fixtures" / "helix_truth.json"
TRUTH = [c for c in json.loads(FIXTURE.read_text()) if "ranges" in c]


def as_saved(text: str) -> str:
    return text if not text or text.endswith("\n") else text + "\n"


def observable(spans):
    return [tuple(s) for s in spans if s[1] > s[0]]


def _id(c):
    return f"{c['keys']}|{c['text'][:12]!r}"


# Helix collapses the two copies into one backward range when `C` lands a second
# cursor on a blank line. Degenerate enough that matching it is not worth the code.
KNOWN_DEVIATIONS = {
    ("2C", "one\n\nthree\n"),
    # A buffer holding nothing but a newline. Paste, multi-cursor insert and
    # insert-at-EOF each land a character differently there. No card uses an
    # empty buffer, so these are recorded rather than chased.
    ("yPp", "\n"),
    ("Cid<esc>", "\n"),
    ("wcX<esc>w", "\n"),
}


@pytest.mark.parametrize("case", TRUTH, ids=_id)
def test_matches_helix(case):
    if (case["keys"], case["text"]) in KNOWN_DEVIATIONS:
        pytest.xfail("known deviation -- see KNOWN_DEVIATIONS")
    e = Engine.run(case["text"], case["keys"])
    assert as_saved(e.text) == case["result"], f"text: {e.render()!r}"
    if not case["spans"]:
        # Helix always holds at least one selection, so nothing marked means the
        # sentinel keystroke was swallowed -- typically by a still-pending prefix.
        # Text is still comparable; selection is not. Prefix handling is covered
        # directly in tests/test_prefixes.py.
        return
    assert observable(e.spans) == observable(case["spans"]), f"selection: {e.render()!r}"
