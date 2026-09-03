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


def test_extra_keystrokes_are_counted(cards):
    """Reaching the right state by wandering is not a clean answer."""
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    s.begin()
    for k in ("b", "j", "k", "w"):
        s.press(k)
    assert s.solved
    assert s.attempt().extra_keys == 3


def test_a_clean_answer_has_no_extra_keystrokes(cards):
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    s.begin()
    s.press("w")
    assert s.attempt().extra_keys == 0


def test_a_restart_does_not_wipe_the_keys_already_spent(cards):
    card = next(c for c in cards if c.id == "motions:w")
    s = Session(card)
    s.begin()
    s.press("b")
    s.reset()
    s.press("w")
    assert s.attempt().keystrokes == 2
    assert s.attempt().extra_keys == 1


def test_a_blessed_alternate_route_costs_nothing(cards):
    """`accept` is how a deck says a different route is equally good."""
    card = next(c for c in cards if c.id == "selection:xx")
    s = Session(card)
    s.begin()
    for k in ("2", "x"):
        s.press(k)
    assert s.solved and s.attempt().extra_keys == 0


def test_par_is_the_shortest_accepted_route(cards):
    card = next(c for c in cards if c.id == "selection:xx")
    assert card.par == 2


def test_every_card_has_a_reachable_par(cards):
    for c in cards:
        assert c.par >= 1, c.id


def test_a_blessed_route_costs_nothing_even_when_longer(cards):
    """`<space>c` is two keys and `<C-c>` is one; both are accepted, so neither
    is charged against the other."""
    card = next(c for c in cards if c.id == "edits:comment-block")
    assert card.par == 1
    s = Session(card)
    s.begin()
    for k in (" ", "c"):
        s.press(k)
    assert s.solved and s.attempt().extra_keys == 0


# -- grading -------------------------------------------------------------


def a(**kw):
    base = {"solved": True, "elapsed_ms": 1000, "hints": 0,
            "wrong_attempts": 0, "keystrokes": 1, "extra_keys": 0}
    return Attempt(**{**base, **kw})


def test_unsolved_is_always_again():
    assert grade(a(solved=False), 1000).rating is Rating.Again


def test_hint_caps_the_rating_at_hard():
    assert grade(a(hints=1, elapsed_ms=100), 1000).rating is Rating.Hard


def test_wrong_attempt_caps_the_rating_at_hard():
    assert grade(a(wrong_attempts=1, elapsed_ms=100), 1000).rating is Rating.Hard


def test_slow_but_clean_is_hard():
    assert grade(a(elapsed_ms=5000), 1000).rating is Rating.Hard


def test_the_slow_penalty_ramps_rather_than_cliffs():
    """2.1x used to cost exactly what 9x cost."""
    mild = grade(a(elapsed_ms=2100), 1000).penalty
    bad = grade(a(elapsed_ms=5000), 1000).penalty
    worse = grade(a(elapsed_ms=9000), 1000).penalty
    assert mild < bad < worse


def test_the_slow_penalty_is_capped():
    assert grade(a(elapsed_ms=600000), 1000).penalty <= 1.0


def test_just_under_the_slow_threshold_is_free():
    assert grade(a(elapsed_ms=1900), 1000).rating is Rating.Good
    assert grade(a(elapsed_ms=1900), 1000).penalty == 0


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


def test_extra_keystrokes_cap_the_rating_at_hard():
    assert grade(a(extra_keys=1, elapsed_ms=100), 1000).rating is Rating.Hard


def test_more_wandering_costs_more():
    assert grade(a(extra_keys=5), 1000).penalty > grade(a(extra_keys=1), 1000).penalty


def test_wandering_fast_no_longer_scores_easy():
    """It used to: arriving quickly by luck outscored a careful slower answer."""
    assert grade(a(extra_keys=7, elapsed_ms=100), 1000).rating is Rating.Hard


def test_penalty_grows_with_hints_and_errors():
    assert grade(a(), 1000).penalty == 0
    assert grade(a(hints=1), 1000).penalty > grade(a(wrong_attempts=1), 1000).penalty
    assert grade(a(solved=False), 1000).penalty == 1.0


def test_first_sighting_has_no_speed_baseline():
    assert grade(a(elapsed_ms=99999), None).rating is Rating.Good


# -- mastery -------------------------------------------------------------


def test_the_penalty_actually_reaches_zero(cards, store):
    """An exponential decay only approaches zero, so it is floored to clear."""
    t = Trainer(cards, store)
    cid = cards[0].id
    t.review(cid, a(solved=False))
    for _ in range(7):
        t.review(cid, a())
    assert store.card(cid)["penalty_ewma"] == 0.0


def test_a_card_is_mastered_once_cleared_and_steady(cards, store):
    t = Trainer(cards, store)
    cid = cards[0].id
    t.review(cid, a(solved=False))
    assert not t.mastered(cid)
    for _ in range(7):
        t.review(cid, a())
    assert t.mastered(cid)


def test_a_clean_run_alone_is_not_mastery(cards, store):
    """Zero penalty with a short streak is not enough -- it could be a fluke."""
    t = Trainer(cards, store)
    cid = cards[0].id
    t.review(cid, a())
    assert store.card(cid)["penalty_ewma"] == 0.0
    assert not t.mastered(cid)
    t.review(cid, a())
    assert not t.mastered(cid)
    t.review(cid, a())
    assert t.mastered(cid)


def test_one_slip_costs_mastery(cards, store):
    t = Trainer(cards, store)
    cid = cards[0].id
    for _ in range(3):
        t.review(cid, a())
    assert t.mastered(cid)
    t.review(cid, a(extra_keys=1))
    assert not t.mastered(cid), "a fumble must break the streak"
    assert store.card(cid)["clean_streak"] == 0


def test_regaining_mastery_takes_the_streak_again(cards, store):
    t = Trainer(cards, store)
    cid = cards[0].id
    for _ in range(3):
        t.review(cid, a())
    t.review(cid, a(extra_keys=1))
    for i in range(1, 3):
        t.review(cid, a())
        assert not t.mastered(cid), f"still short at {i}"
    t.review(cid, a())
    assert t.mastered(cid)


def test_a_failure_unmasters_a_card(cards, store):
    t = Trainer(cards, store)
    cid = cards[0].id
    for _ in range(3):
        t.review(cid, a())
    assert t.mastered(cid)
    t.review(cid, a(solved=False))
    assert not t.mastered(cid)
    assert store.card(cid)["penalty_ewma"] > 0


def test_mastered_count_only_counts_loaded_cards(cards, store):
    t = Trainer(cards[:2], store)
    assert t.mastered_count() == 0
    for _ in range(3):
        t.review(cards[0].id, a())
    assert t.mastered_count() == 1


def test_an_unseen_card_is_not_mastered(cards, store):
    t = Trainer(cards, store)
    assert not t.mastered(cards[0].id)


# -- scheduling ----------------------------------------------------------


def test_the_review_log_records_the_excess(cards, store):
    t = Trainer(cards, store)
    t.review(cards[0].id, a(extra_keys=4))
    row = store.db.execute("SELECT extra FROM reviews").fetchone()
    assert row["extra"] == 4


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


def test_reference_time_tracks_your_better_attempts(cards, store):
    """A low percentile, not the median: the bar must not drift up to meet you."""
    t = Trainer(cards, store)
    for ms in (1000, 2000, 3000, 4000, 5000):
        t.review(cards[0].id, a(elapsed_ms=ms))
    assert store.reference_time(cards[0].id) == 2000


def test_slipping_below_your_proven_speed_gets_flagged(cards, store):
    """A median reference drifts up to meet recent slowness and stops flagging;
    a low percentile keeps the bar at what you have already demonstrated."""
    t = Trainer(cards, store)
    for ms in (2000, 3000, 20000, 21000):
        t.review(cards[0].id, a(elapsed_ms=ms))
    ref = store.reference_time(cards[0].id)
    median = 11500
    assert ref == 3000
    assert grade(a(elapsed_ms=22000), median).rating is Rating.Good, "median lets it pass"
    assert grade(a(elapsed_ms=22000), ref).rating is Rating.Hard, "percentile catches it"


def test_a_card_you_have_never_done_fast_cannot_be_called_slow(cards, store):
    """An honest limit: with no fast attempt on record there is no evidence you
    can go faster, and the clock includes reading the prompt, so there is no
    absolute bar to compare against."""
    t = Trainer(cards, store)
    for _ in range(4):
        t.review(cards[0].id, a(elapsed_ms=30000))
    ref = store.reference_time(cards[0].id)
    assert ref == 30000
    assert grade(a(elapsed_ms=30000), ref).rating is Rating.Good
