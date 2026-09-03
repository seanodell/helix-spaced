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

from .scoring import Attempt, Grade, grade, update_ewma
from .store import Store

NEW_CARD_WEIGHT = 1.5
PENALTY_EXPONENT = 3.0
OVERDUE_BONUS_PER_DAY = 0.15
MAX_OVERDUE_BONUS = 1.5


class Trainer:
    def __init__(self, cards: list, store: Store, rng: random.Random | None = None):
        self.cards = {c.id: c for c in cards}
        self.store = store
        self.scheduler = Scheduler()
        self.rng = rng or random.Random()
        for c in cards:
            store.ensure(c.id, c.deck)

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
        """Draw the next card: due ones first, weighted toward the hard ones."""
        now = now or datetime.now(UTC)
        rows = self.store.all_cards()
        exclude = exclude or set()
        pool = [c for c in self.due_pool(now) if c not in exclude]
        if not pool:
            pool = [c for c in self.cards if c not in exclude]
        if not pool:
            return None
        weights = [self.weight(cid, rows.get(cid), now) for cid in pool]
        return self.cards[self.rng.choices(pool, weights=weights, k=1)[0]]

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
        self.store.save_card(card_id, self.cards[card_id].deck, updated.to_dict(),
                             ewma, g.rating == Rating.Again, updated.due)
        self.store.log(card_id, attempt, int(g.rating), g.penalty, keys)
        return g
