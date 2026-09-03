"""Keystroke-graded cards.

Code navigation needs a language server and a second file, so there is no buffer
state for real hx to report and none for the emulator to compare. Those cards
are graded on the keys pressed instead -- which means the accepted answers have
to be exactly right, since nothing else is checking them.

The bindings here were read out of the installed Helix's own Goto infobox, and
`C-o`/`C-i` were confirmed by probing a real hx.
"""

import pytest

from helix_spaced.deck import KEYS, STATE, load_dir, normalise
from helix_spaced.emu.engine import Engine
from helix_spaced.keymap import RESERVED_NOTATION, from_textual

CARDS = {c.id: c for c in load_dir()}
KEY_CARDS = [c for c in CARDS.values() if c.kind == KEYS]


KEYSTROKE_DECKS = {"navigation", "files"}


def test_only_editor_level_decks_are_keystroke_graded():
    """Keystroke grading is the fallback for commands with no buffer state --
    everything that touches text must be graded on the resulting state."""
    assert KEY_CARDS, "expected keystroke cards"
    assert {c.deck for c in KEY_CARDS} == KEYSTROKE_DECKS


def test_state_cards_are_still_the_majority():
    state = [c for c in CARDS.values() if c.kind == STATE]
    assert len(state) > len(KEY_CARDS)


@pytest.mark.parametrize("card", KEY_CARDS, ids=lambda c: c.id)
def test_its_own_answer_is_accepted(card):
    assert card.check(card.keys)
    for alt in card.accept:
        assert card.check(alt), f"{alt!r} should be accepted"


@pytest.mark.parametrize("card", KEY_CARDS, ids=lambda c: c.id)
def test_a_different_answer_is_rejected(card):
    assert not card.check("zzz")
    assert not card.check("")


@pytest.mark.parametrize("card", KEY_CARDS, ids=lambda c: c.id)
def test_the_keys_are_inert_in_the_emulator(card):
    """A navigation card must not accidentally edit the buffer."""
    e = Engine(card.text)
    if card.start:
        e.feed(card.start)
    before = e.text
    e.feed(card.keys)
    assert e.text == before
    assert e.state.mode == "normal"


def test_answers_are_unique_across_the_navigation_deck():
    """Two cards resolving to the same keys would be unanswerable."""
    seen: dict[tuple, str] = {}
    for c in KEY_CARDS:
        for answer in c.answers:
            key = normalise(answer)
            assert key not in seen, f"{c.id} collides with {seen.get(key)} on {answer!r}"
            seen[key] = c.id


# -- the bindings themselves ----------------------------------------------


@pytest.mark.parametrize(("card_id", "expected"), [
    ("files:close-buffer", ":bc<ret>"),
    ("files:write", ":w<ret>"),
    ("files:quit", ":q<ret>"),
    ("files:buffer-picker", "<space>b"),
    ("files:file-picker", "<space>f"),
    ("nav:goto-definition", "gd"),
    ("nav:goto-declaration", "gD"),
    ("nav:goto-type-definition", "gy"),
    ("nav:goto-implementation", "gi"),
    ("nav:goto-references", "gr"),
    ("nav:goto-file", "gf"),
    ("nav:jump-back", "<C-o>"),
    ("nav:jump-forward", "<C-i>"),
    ("nav:save-jump", "<C-s>"),
    ("nav:last-accessed-file", "ga"),
    ("nav:last-modified-file", "gm"),
    ("nav:last-modification", "g."),
    ("nav:next-buffer", "gn"),
    ("nav:prev-buffer", "gp"),
    ("nav:label-jump", "gw"),
    ("nav:window-top", "gt"),
    ("nav:window-center", "gc"),
    ("nav:window-bottom", "gb"),
])
def test_binding_matches_the_helix_goto_menu(card_id, expected):
    assert CARDS[card_id].keys == expected


def test_tab_is_accepted_for_jump_forward():
    """Terminals send the same byte for Ctrl-I and Tab, so both must answer."""
    card = CARDS["nav:jump-forward"]
    assert card.check(from_textual("tab", "\t"))
    assert card.check(from_textual("ctrl+i", None) or "<C-i>")


def test_navigation_answers_are_literal_keys():
    """A first-time learner sees exactly what to press."""
    for c in KEY_CARDS:
        assert c.check(c.answer)
        assert c.answer.strip()


def test_reserved_trainer_keys_are_not_required_by_any_card():
    """A card can never ask for a key the trainer swallows."""
    reserved = set(RESERVED_NOTATION)
    for c in CARDS.values():
        for answer in c.answers:
            assert not (set(normalise(answer)) & reserved), f"{c.id} needs a reserved key"


def test_closing_a_buffer_accepts_every_verified_alias():
    """Helix's own help gives buffer-close the aliases bc and bclose."""
    card = CARDS["files:close-buffer"]
    for alias in (":bc<ret>", ":bclose<ret>", ":buffer-close<ret>"):
        assert card.check(alias), alias
    assert not card.check(":bufferclose<ret>")


def test_closing_a_buffer_is_not_the_same_card_as_quitting():
    """`:q` closes the view and exits when it is the last one; `:bc` does not."""
    assert CARDS["files:close-buffer"].keys != CARDS["files:quit"].keys
    assert not CARDS["files:close-buffer"].check(":q<ret>")


def test_space_menu_answers_show_the_space_key():
    for c in KEY_CARDS:
        if c.keys.startswith("<space>"):
            assert c.answer.startswith("<space>"), c.id


def test_par_is_never_set_by_an_unreachable_answer():
    """`<C-c>` also toggles comments in Helix, but Ctrl-C quits the trainer.
    A par taken from a key you cannot press penalises a correct answer."""
    for c in CARDS.values():
        shortest = min(c.typeable, key=lambda a: len(normalise(a)))
        assert not (set(normalise(shortest)) & RESERVED_NOTATION), c.id
        assert c.par == len(normalise(shortest))
