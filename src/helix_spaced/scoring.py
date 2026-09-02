"""Turn one attempt into an FSRS rating plus a difficulty signal.

`hints` counts how many times the answer was revealed. The field keeps its name
because the review log is append-only and older rows use it.

Two things come out of an attempt. The rating drives FSRS scheduling (when the
card comes back at all). The penalty is a separate 0..1 difficulty signal that
biases which of the *currently due* cards get asked first, so hard cards recur
within a session without corrupting the spacing model.
"""

from dataclasses import dataclass

from fsrs import Rating

# Revealing the answer shows the literal keystrokes, not a nudge, so it costs
# more than the old hint did.
ANSWER_PENALTY = 0.6
WRONG_KEY_PENALTY = 0.12
SLOW_FACTOR = 2.0
FAST_FACTOR = 0.6
PENALTY_EWMA_ALPHA = 0.3


@dataclass(frozen=True, slots=True)
class Attempt:
    solved: bool
    elapsed_ms: int
    hints: int
    wrong_attempts: int
    keystrokes: int


@dataclass(frozen=True, slots=True)
class Grade:
    rating: Rating
    penalty: float
    reason: str


def grade(attempt: Attempt, baseline_ms: int | None) -> Grade:
    """baseline_ms is the rolling median time for this card, or None if unseen."""
    if not attempt.solved:
        return Grade(Rating.Again, 1.0, "wrong")

    penalty = min(1.0, attempt.hints * ANSWER_PENALTY
                  + attempt.wrong_attempts * WRONG_KEY_PENALTY)
    slow = baseline_ms is not None and attempt.elapsed_ms > baseline_ms * SLOW_FACTOR
    fast = baseline_ms is not None and attempt.elapsed_ms < baseline_ms * FAST_FACTOR

    if slow:
        penalty = min(1.0, penalty + 0.25)

    if attempt.hints:
        return Grade(Rating.Hard, penalty, "answer shown")
    if attempt.wrong_attempts:
        return Grade(Rating.Hard, penalty, "recovered after a wrong try")
    if slow:
        return Grade(Rating.Hard, penalty, "slow")
    if fast:
        return Grade(Rating.Easy, penalty, "clean and fast")
    return Grade(Rating.Good, penalty, "clean")


def update_ewma(previous: float | None, penalty: float) -> float:
    if previous is None:
        return penalty
    return previous * (1 - PENALTY_EWMA_ALPHA) + penalty * PENALTY_EWMA_ALPHA
