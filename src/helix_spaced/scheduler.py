"""FSRS scheduling plus difficulty-weighted selection.

FSRS alone decides *when* a card is due, which spreads work evenly and would ask
an easy card as often as a hard one once both come due. The weighted draw below
sits on top: among cards that are due (and among new cards), the ones with a
high penalty EWMA are far likelier to be drawn next. Spacing stays correct;
attention goes where it is earned.
"""

import json
import random
from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler

from .deck import Section, sections
from .scoring import Attempt, Grade, grade, is_mastered, update_ewma
from .store import Store

NEW_CARD_WEIGHT = 1.5
PENALTY_EXPONENT = 3.0
OVERDUE_BONUS_PER_DAY = 0.15
MAX_OVERDUE_BONUS = 1.5


class Trainer:
    def __init__(self, cards: list, store: Store, rng: random.Random | None = None):
        self.cards = {c.id: c for c in cards}
        self.sections = sections(cards)
        self.store = store
        self.scheduler = Scheduler()
        self.rng = rng or random.Random()
        for c in cards:
            store.ensure(c.id, c.section or c.deck)

    # -- curriculum --------------------------------------------------------

    def current_section(self) -> Section | None:
        """The first section still holding an unmastered card. None once the whole
        curriculum is mastered, at which point everything is just review."""
        done = self.store.mastered_ids()
        for section in self.sections:
            if any(c.id not in done for c in section.cards):
                return section
        return None

    def sections_mastered(self) -> int:
        done = self.store.mastered_ids()
        return sum(1 for s in self.sections
                   if all(c.id in done for c in s.cards))

    def section_progress(self, section: Section) -> tuple[int, int]:
        done = self.store.mastered_ids()
        return sum(1 for c in section.cards if c.id in done), len(section.cards)

    def due_now(self, now: datetime | None = None) -> int:
        """Due cards you can actually be shown -- locked sections do not count."""
        unlocked = {c.id for c in self.unlocked()}
        return sum(1 for c in self.due_pool(now) if c in unlocked)

    def unlocked(self) -> list:
        """Cards from every section up to and including the current one. Later
        sections stay locked; earlier ones stay in rotation so the spacing model
        can still bring them back."""
        current = self.current_section()
        limit = current.order if current else self.sections[-1].order
        return [c for c in self.cards.values() if c.order <= limit]

    # -- selection ---------------------------------------------------------

    def weight(self, card_id: str, row, now: datetime) -> float:
        if row is None or row["due"] is None:
            return NEW_CARD_WEIGHT
        penalty = row["penalty_ewma"] if row["penalty_ewma"] is not None else 0.5
        due = datetime.fromisoformat(row["due"])
        overdue_days = max(0.0, (now - due).total_seconds() / 86400)
        difficulty = 1.0 + PENALTY_EXPONENT * penalty
        overdue = min(MAX_OVERDUE_BONUS, overdue_days * OVERDUE_BONUS_PER_DAY)
        return max(0.01, difficulty + overdue)

    def due_pool(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(UTC)
        rows = self.store.all_cards()
        pool = []
        for cid in self.cards:
            row = rows.get(cid)
            if row is None or row["due"] is None or datetime.fromisoformat(row["due"]) <= now:
                pool.append(cid)
        return pool

    def next_card(self, now: datetime | None = None, exclude: set[str] | None = None):
        """Draw the next card.

        New material is gated to the current section, but cards from earlier
        sections stay in rotation once they come due -- gating what is *introduced*
        rather than what is reviewed, or a mastered section would rot.
        """
        now = now or datetime.now(UTC)
        rows = self.store.all_cards()
        exclude = exclude or set()
        unlocked = {c.id for c in self.unlocked()}
        current = self.current_section()
        mastered = self.store.mastered_ids()

        due = [c for c in self.due_pool(now) if c in unlocked and c not in exclude]
        if not due and current:
            # nothing due: push on with whatever this section has left to learn
            due = [c.id for c in current.cards
                   if c.id not in mastered and c.id not in exclude]
        if not due:
            due = [c for c in unlocked if c not in exclude]
        if not due:
            return None
        weights = [self.weight(cid, rows.get(cid), now) for cid in due]
        return self.cards[self.rng.choices(due, weights=weights, k=1)[0]]

    # -- review ------------------------------------------------------------

    def dry_grade(self, card_id: str, attempt: Attempt) -> Grade:
        """Grade an attempt for feedback without recording it. Used by a practice
        redo: an immediate re-test is not a real review, and letting one count
        would both corrupt the spacing and make Easy farmable."""
        return grade(attempt, self.store.reference_time(card_id))

    def review(self, card_id: str, attempt: Attempt, keys: str = "") -> Grade:
        row = self.store.card(card_id)
        baseline = self.store.reference_time(card_id)
        g = grade(attempt, baseline)

        fsrs_card = Card.from_dict(json.loads(row["fsrs"])) if row and row["fsrs"] else Card()
        updated, _ = self.scheduler.review_card(
            fsrs_card, g.rating, review_datetime=datetime.now(UTC),
            review_duration=attempt.elapsed_ms)

        prev = row["penalty_ewma"] if row else None
        ewma = update_ewma(prev, g.penalty)
        streak = (row["clean_streak"] if row else 0) + 1 if g.clean else 0
        self.store.save_card(card_id, self.cards[card_id].deck, updated.to_dict(),
                             ewma, g.rating == Rating.Again, updated.due, streak)
        self.store.log(card_id, attempt, int(g.rating), g.penalty, keys)
        return g

    def mastered(self, card_id: str) -> bool:
        row = self.store.card(card_id)
        if row is None:
            return False
        return is_mastered(row["penalty_ewma"], row["clean_streak"])

    def mastered_count(self) -> int:
        return len(self.store.mastered_ids() & set(self.cards))
