"""Drive Textual's own parser with the bytes a terminal really sends.

Asserting `from_textual("alt+shift+c", ...)` only proves the translation handles
a name *I* invented. These tests feed the actual escape sequences through
Textual's XTermParser, so the key names come from Textual rather than from a
guess -- the same reason the emulator is graded against a real hx.
"""

import pytest
from textual._xterm_parser import XTermParser
from textual.events import Key

from helix_spaced.deck import load_dir
from helix_spaced.keymap import from_textual

ALT, SHIFT, CTRL = 2, 1, 4


def press(data: str) -> tuple[str, str | None] | None:
    """Key event Textual produces for a raw sequence. The empty feed flushes a
    pending ESC, which the parser otherwise holds waiting for a longer sequence."""
    parser = XTermParser()
    events = [e for chunk in (data, "") for e in parser.feed(chunk) if isinstance(e, Key)]
    return (events[-1].key, events[-1].character) if events else None


def kitty(char: str, mods: int) -> str:
    return f"\x1b[{ord(char)};{1 + mods}u"


def translate(data: str) -> str | None:
    event = press(data)
    return from_textual(*event) if event else None


# -- works on any terminal ------------------------------------------------


@pytest.mark.parametrize(("sequence", "expected"), [
    ("\x1bC", "<A-C>"),       # Alt-Shift-C, the key that started this
    ("\x1bJ", "<A-J>"),
    ("\x1bd", "<A-d>"),
    ("\x1bs", "<A-s>"),
    ("\x03", "<C-c>"),        # toggle comments, not quit
    ("\x17", "<C-w>"),
    ("w", "w"),
    ("\x1b", "<esc>"),
])
def test_legacy_escape_prefix(sequence, expected):
    assert translate(sequence) == expected


def test_ctrl_q_is_swallowed_as_the_quit_key():
    assert translate("\x11") is None


# -- needs the kitty keyboard protocol ------------------------------------


@pytest.mark.parametrize(("char", "mods", "expected"), [
    (";", ALT, "<A-;>"),
    ("`", ALT, "<A-`>"),
    ("c", ALT | SHIFT, "<A-C>"),
    ("d", ALT, "<A-d>"),
    ("c", CTRL, "<C-c>"),
])
def test_kitty_protocol_carries_every_modifier(char, mods, expected):
    assert translate(kitty(char, mods)) == expected


@pytest.mark.parametrize("char", [";", "`"])
def test_alt_punctuation_loses_its_modifier_without_kitty(char):
    """A known terminal limitation, not a bug in the translation: Textual reports
    ESC-; as a plain `semicolon`, so the Alt is gone before we see it. Recorded
    here so a future Textual that fixes it shows up as a failing test."""
    assert translate("\x1b" + char) == char
    assert translate(kitty(char, ALT)) == f"<A-{char}>"


# -- the deck -------------------------------------------------------------


def alt_keys_in_deck() -> set[str]:
    import re
    return {t for c in load_dir() for a in c.answers for t in re.findall(r"<A-(.)>", a)}


@pytest.mark.parametrize("token", sorted(alt_keys_in_deck()))
def test_every_alt_card_is_reachable_under_kitty(token):
    mods = ALT | SHIFT if token.isalpha() and token.isupper() else ALT
    assert translate(kitty(token.lower() if token.isupper() else token, mods)) == f"<A-{token}>"


@pytest.mark.parametrize("token", sorted(alt_keys_in_deck()))
def test_alt_letters_also_work_on_a_legacy_terminal(token):
    if not token.isalpha():
        pytest.skip("punctuation needs the kitty protocol; covered above")
    assert translate("\x1b" + token) == f"<A-{token}>"
