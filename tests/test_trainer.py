import random
from datetime import UTC, datetime, timedelta

import pytest
from fsrs import Rating

from helix_spaced.deck import load_dir, validate
from helix_spaced.emu.keys import parse
from helix_spaced.scheduler import Trainer
from helix_spaced.scoring import Attempt, grade
from helix_spaced.session import Session
from helix_spaced.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def cards():
    return load_dir()


def test_every_card_is_solvable(cards):
    assert validate(cards) == []


def test_deck_covers_each_category(cards):
    decks = {c.deck for c in cards}
    assert {"motions", "selection", "edits"} <= decks


def test_solving_a_card_by_typing_its_keys(cards):
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    s.begin()
    solved = False
    for k in parse(card.keys):
        solved = s.press(k.spec)
    assert solved and s.solved and s.hints == 0 and s.wrong == 0


def test_alternate_solution_is_accepted(cards):
    card = next(c for c in cards if c.id == "selection:xx")
    assert card.check("2x") and card.check("xx")


def test_wrong_keys_do_not_solve(cards):
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    s.begin()
    assert not s.press("b")
    assert not s.solved


def test_restart_counts_against_the_score(cards):
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    s.begin()
    s.press("b")
    s.reset()
    assert s.wrong == 1 and s.typed == ""
    assert s.press("w")


def test_a_session_ignores_keys_until_begun(cards):
    """The app calls begin() as soon as a card appears; the guard is belt and braces."""
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    assert not s.press("w")
    assert s.typed == "" and s.elapsed_ms == 0 and not s.solved
    s.begin()
    assert s.press("w")


# -- grading -------------------------------------------------------------


def a(**kw):
    base = {"solved": True, "elapsed_ms": 1000, "hints": 0,
            "wrong_attempts": 0, "keystrokes": 1}
    return Attempt(**{**base, **kw})


def test_unsolved_is_always_again():
    assert grade(a(solved=False), 1000).rating is Rating.Again


def test_hint_caps_the_rating_at_hard():
    assert grade(a(hints=1, elapsed_ms=100), 1000).rating is Rating.Hard


def test_wrong_attempt_caps_the_rating_at_hard():
    assert grade(a(wrong_attempts=1, elapsed_ms=100), 1000).rating is Rating.Hard


def test_slow_but_clean_is_hard():
    assert grade(a(elapsed_ms=5000), 1000).rating is Rating.Hard


def test_fast_and_clean_is_easy():
    assert grade(a(elapsed_ms=400), 1000).rating is Rating.Easy


def test_normal_and_clean_is_good():
    assert grade(a(elapsed_ms=1000), 1000).rating is Rating.Good


def test_the_answer_is_always_the_graded_solution(cards):
    """Derived from `keys`, so a revealed answer cannot drift from what passes.
    It is shown in visible notation, and typing exactly that must still solve it."""
    for c in cards:
        assert c.check(c.answer), f"{c.id}: revealed answer {c.answer!r} does not solve it"


def test_no_answer_contains_an_invisible_keystroke(cards):
    """A bare space in an answer reads as nothing at all -- `T ` must show as
    `T<space>`, or a learner sees `T` and wonders why it does not work."""
    for c in cards:
        assert not any(ch in c.answer for ch in " \t\n"), \
            f"{c.id}: answer {c.answer!r} has an invisible keystroke"


def test_answers_round_trip_through_notation(cards):
    from helix_spaced.emu.keys import parse
    for c in cards:
        assert parse(c.answer) == parse(c.keys)


def test_penalty_grows_with_hints_and_errors():
    assert grade(a(), 1000).penalty == 0
    assert grade(a(hints=1), 1000).penalty > grade(a(wrong_attempts=1), 1000).penalty
    assert grade(a(solved=False), 1000).penalty == 1.0


def test_first_sighting_has_no_speed_baseline():
    assert grade(a(elapsed_ms=99999), None).rating is Rating.Good


# -- scheduling ----------------------------------------------------------


def test_review_persists_state_and_history(cards, store):
    t = Trainer(cards, store)
    card = cards[0]
    t.review(card.id, a(elapsed_ms=800))
    row = store.card(card.id)
    assert row["reviews"] == 1 and row["fsrs"] and row["due"]
    assert store.stats()["reviews"] == 1


def test_failure_records_a_lapse(cards, store):
    t = Trainer(cards, store)
    t.review(cards[0].id, a(solved=False))
    assert store.card(cards[0].id)["lapses"] == 1


def test_hard_cards_are_drawn_far_more_often(cards, store):
    """The whole point: due cards are not equally likely once difficulty is known."""
    t = Trainer(cards[:6], store, rng=random.Random(0))
    easy, hard = cards[0], cards[1]
    for _ in range(6):
        t.review(easy.id, a(elapsed_ms=300))
        t.review(hard.id, a(solved=False))

    now = datetime.now(UTC) + timedelta(days=400)
    rows = store.all_cards()
    assert t.weight(hard.id, rows[hard.id], now) > t.weight(easy.id, rows[easy.id], now) * 2

    draws = [t.next_card(now=now).id for _ in range(400)]
    assert draws.count(hard.id) > draws.count(easy.id) * 1.5


def test_unseen_cards_are_all_due(cards, store):
    t = Trainer(cards, store)
    assert len(t.due_pool()) == len(cards)


def test_a_reviewed_card_leaves_the_due_pool(cards, store):
    t = Trainer(cards, store)
    t.review(cards[0].id, a(elapsed_ms=300))
    assert cards[0].id not in t.due_pool()


def test_exclusion_prevents_immediate_repeats(cards, store):
    t = Trainer(cards[:3], store, rng=random.Random(1))
    picked = t.next_card()
    assert t.next_card(exclude={picked.id}).id != picked.id


def test_median_time_tracks_recent_attempts(cards, store):
    t = Trainer(cards, store)
    for ms in (1000, 2000, 3000):
        t.review(cards[0].id, a(elapsed_ms=ms))
    assert store.median_time(cards[0].id) == 2000
