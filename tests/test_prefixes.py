"""Prefix keys must swallow their own sequence.

The bug this guards: `m` was unimplemented, so it was dropped and the following
`a` was read as *append*, silently putting the user in insert mode. Any Helix
sub-menu key can do this, so each one is checked -- including the ones the
emulator does not implement, which must still consume their sequence.

These cannot be covered by the hx probe: a pending prefix swallows the probe's
own sentinel keystroke, so nothing is observable.
"""

import pytest

from helix_spaced.emu.engine import PREFIXES, Engine

TEXT = "call(alpha, beta) end\n"

# Sequences that are *meant* to edit, so "buffer unchanged" does not apply:
# `r<char>` replaces, and `<space>c` toggles comments.
EDITING_SEQUENCES = {("r", "a"), ("r", "i"), ("r", "o"), ("r", "c"), (" ", "c")}


def test_the_reported_bug_ma_does_not_enter_insert_mode():
    e = Engine.run(TEXT, "ma")
    assert e.state.mode == "normal"
    assert e.text == TEXT


@pytest.mark.parametrize("prefix", sorted(PREFIXES))
def test_a_prefix_never_leaks_its_next_key_as_a_command(prefix):
    """`<prefix>a` must not append and `<prefix>i` must not insert, whether or
    not the emulator implements that sequence."""
    for follow in ("a", "i", "o", "c"):
        e = Engine.run(TEXT, prefix + follow)
        assert e.state.mode == "normal", f"{prefix + follow} entered insert mode"
        if (prefix, follow) not in EDITING_SEQUENCES:
            assert e.text == TEXT, f"{prefix + follow} changed the buffer"


@pytest.mark.parametrize("prefix", sorted(PREFIXES))
def test_an_unfinished_prefix_leaves_the_buffer_untouched(prefix):
    e = Engine.run(TEXT, prefix)
    assert e.text == TEXT
    assert e.state.mode == "normal"


@pytest.mark.parametrize("keys", ["zz", "[b", "]b", " w", "Zz"])
def test_unimplemented_prefixes_are_inert_not_destructive(keys):
    e = Engine.run(TEXT, keys)
    assert e.text == TEXT
    assert e.state.mode == "normal"


# -- sequences release the keyboard when complete -------------------------


def test_a_completed_sequence_lets_the_next_key_act_normally():
    e = Engine.run(TEXT, "wwmi(d")
    assert e.text == "call() end\n"


def test_surround_replace_consumes_exactly_two_object_keys():
    """`mr({` is four keys; the fifth must be a fresh command."""
    e = Engine.run(TEXT, "wwmr({")
    assert e.text == "call{alpha, beta} end\n"
    e = Engine.run(TEXT, "wwmr({x")
    assert e.spans == [(0, len(e.text))], "the key after mr({ should select the line"


def test_an_unimplemented_sequence_still_releases_the_keyboard():
    """`zz` is not implemented, but `d` after it must still delete."""
    e = Engine.run(TEXT, "wzzd")
    assert e.text == "(alpha, beta) end\n"
