"""Sections are learned one at a time, in order.

The tension this resolves: gating everything to the current section would stop
earlier cards ever coming back, which defeats spaced repetition. So gating
applies to what is *introduced*, not to what is reviewed.
"""

from datetime import UTC, datetime, timedelta

import pytest

from helix_spaced.deck import load_dir, sections
from helix_spaced.scheduler import Trainer
from helix_spaced.scoring import Attempt
from helix_spaced.store import Store


def clean() -> Attempt:
    return Attempt(solved=True, elapsed_ms=1000, hints=0, wrong_attempts=0,
                   keystrokes=1, extra_keys=0)


def failed() -> Attempt:
    return Attempt(solved=False, elapsed_ms=1000, hints=0, wrong_attempts=0,
                   keystrokes=1, extra_keys=0)


@pytest.fixture
def cards():
    return load_dir()


@pytest.fixture
def trainer(cards, tmp_path):
    store = Store(tmp_path / "c.db")
    yield Trainer(cards, store)
    store.close()


def master(trainer, section):
    for card in section.cards:
        for _ in range(3):
            trainer.review(card.id, clean())


# -- shape of the curriculum ---------------------------------------------


def test_every_card_belongs_to_exactly_one_section(cards):
    secs = sections(cards)
    seen = [c.id for s in secs for c in s.cards]
    assert len(seen) == len(set(seen)) == len(cards)


def test_sections_are_uniquely_ordered(cards):
    orders = [s.order for s in sections(cards)]
    assert orders == sorted(orders)
    assert len(orders) == len(set(orders))


def test_movement_comes_before_the_advanced_material(cards):
    order = {s.name: s.order for s in sections(cards)}
    assert order["moving"] < order["selecting"] < order["editing"]
    assert order["editing"] < order["pairs"] < order["surround"]
    assert order["moving"] < order["codenav"]
    assert order["moving"] < order["macros"]


def test_the_m_keys_are_grouped_together(cards):
    """The thing that prompted this: learn the match-mode keys as a block."""
    by_section = {}
    for c in cards:
        for key in c.answers:
            if key.startswith("m") and len(key) > 1:
                by_section.setdefault(c.section, set()).add(key[:2])
    assert by_section["pairs"], "pairs section holds the mi/ma pair objects"
    assert by_section["surround"] >= {"ms", "md", "mr"}


# -- gating ---------------------------------------------------------------


def test_only_the_first_section_is_unlocked_at_the_start(trainer):
    first = trainer.sections[0]
    assert trainer.current_section().order == first.order
    assert {c.id for c in trainer.unlocked()} == {c.id for c in first.cards}


def test_a_locked_section_is_never_drawn(trainer):
    first = trainer.sections[0]
    drawn = {trainer.next_card().section for _ in range(80)}
    assert drawn == {first.name}


def test_finishing_a_section_unlocks_the_next(trainer):
    first, second = trainer.sections[0], trainer.sections[1]
    master(trainer, first)
    assert trainer.current_section().order == second.order
    assert trainer.sections_mastered() == 1
    unlocked = {c.section for c in trainer.unlocked()}
    assert unlocked == {first.name, second.name}


def test_you_cannot_skip_ahead(trainer):
    """Mastering nothing keeps you on section one however many cards you draw."""
    for _ in range(50):
        card = trainer.next_card()
        trainer.review(card.id, clean())
    assert trainer.current_section().order <= 2


def test_an_earlier_section_returns_for_review_once_due(trainer):
    """Gating what is introduced, not what is reviewed -- otherwise a mastered
    section would never be seen again and would rot."""
    first, second = trainer.sections[0], trainer.sections[1]
    master(trainer, first)
    soon = {trainer.next_card().section for _ in range(40)}
    assert soon == {second.name}, "nothing from section 1 is due yet"

    later = datetime.now(UTC) + timedelta(days=400)
    much_later = {trainer.next_card(now=later).section for _ in range(80)}
    assert first.name in much_later, "section 1 must come back when due"
    assert much_later <= {first.name, second.name}, "still nothing locked"


def test_progress_is_reported_per_section(trainer):
    first = trainer.sections[0]
    assert trainer.section_progress(first) == (0, len(first.cards))
    for _ in range(3):
        trainer.review(first.cards[0].id, clean())
    assert trainer.section_progress(first) == (1, len(first.cards))


def test_a_lapse_in_an_early_section_pulls_you_back(trainer):
    """Sections mastered and current position can disagree after a lapse."""
    master(trainer, trainer.sections[0])
    master(trainer, trainer.sections[1])
    assert trainer.sections_mastered() == 2
    assert trainer.current_section().order == 3

    trainer.review(trainer.sections[0].cards[0].id, failed())
    assert trainer.current_section().order == 1, "back to the section that slipped"
    assert trainer.sections_mastered() == 1


def test_the_whole_curriculum_can_be_finished(trainer):
    for section in trainer.sections:
        master(trainer, section)
    assert trainer.current_section() is None
    assert trainer.sections_mastered() == len(trainer.sections)
    assert trainer.next_card() is not None, "finished means review-only, not empty"


def test_due_count_ignores_locked_sections(trainer):
    assert trainer.due_now() == len(trainer.sections[0].cards)
    assert trainer.due_now() < len(trainer.cards)
