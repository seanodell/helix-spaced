"""Prove each card is right, not just self-consistent.

test_conformance.py grades the emulator against Helix on a fixed corpus.
This grades the *deck*: for every card, the state real Helix reaches by running
`start + keys` must be the state the trainer accepts as the answer. Without it,
`validate` is circular -- it only checks a card's solution against the emulator's
own idea of that solution.

Regenerate with `mise run verify-deck` (needs hx installed).
"""

import json
from pathlib import Path

import pytest

from helix_spaced.deck import STATE, load_dir

FIXTURE = Path(__file__).parent / "fixtures" / "deck_truth.json"
# Keystroke-graded cards drive a language server or a second file, so real hx
# has no state to report; they are covered by tests/test_keys_cards.py instead.
CARDS = {c.id: c for c in load_dir() if c.kind == STATE}

if FIXTURE.exists():
    TRUTH = [t for t in json.loads(FIXTURE.read_text()) if "ranges" in t]
else:
    TRUTH = []


def as_saved(text: str) -> str:
    return text if not text or text.endswith("\n") else text + "\n"


def observable(spans):
    return [tuple(s) for s in spans if s[1] > s[0]]


@pytest.mark.skipif(not FIXTURE.exists(), reason="run `mise run verify-deck` first")
def test_every_card_was_probed():
    assert {t["id"] for t in TRUTH} == set(CARDS)


@pytest.mark.skipif(not FIXTURE.exists(), reason="run `mise run verify-deck` first")
@pytest.mark.parametrize("truth", TRUTH, ids=lambda t: t["id"])
def test_card_solution_matches_real_helix(truth):
    card = CARDS[truth["id"]]
    got = card.expected()
    assert as_saved(got.text) == truth["result"], (
        f"{card.id}: emulator text {got.render()!r} != helix {truth['result']!r}")
    assert observable(got.spans) == observable(truth["spans"]), (
        f"{card.id}: emulator selection {got.render()!r}")
