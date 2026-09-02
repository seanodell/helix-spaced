"""Turn one attempt into an FSRS rating plus a difficulty signal.

`hints` counts how many times the answer was revealed. The field keeps its name
because the review log is append-only and older rows use it.

Two things come out of an attempt. The rating drives FSRS scheduling (when the
card comes back at all). The penalty is a separate 0..1 difficulty signal that
biases which of the *currently due* cards get asked first, so hard cards recur
within a session without corrupting the spacing model.

Reaching the right state is not enough: getting there with more keystrokes than
the shortest accepted route counts against you, because the point is precise
muscle memory rather than arrival by wandering.

Time is measured against what you have *proven you can do* on that card -- the
25th percentile of recent solved attempts, not the median. A median reference
drifts up to meet you, so a card that always takes 30 seconds would score clean
forever. It stays self-relative rather than an absolute number of seconds
because the clock includes reading the prompt, and prompts differ in length.
"""

from dataclasses import dataclass

from fsrs import Rating

# Revealing the answer shows the literal keystrokes, not a nudge, so it costs
# more than the old hint did.
ANSWER_PENALTY = 0.6
WRONG_KEY_PENALTY = 0.12
EXTRA_KEY_PENALTY = 0.15
SLOW_FACTOR = 2.0
FAST_FACTOR = 0.6
SLOW_RAMP = 0.2          # penalty per multiple of the reference time beyond SLOW_FACTOR
MAX_SLOW_PENALTY = 0.8
PENALTY_EWMA_ALPHA = 0.3


@dataclass(frozen=True, slots=True)
class Attempt:
    solved: bool
    elapsed_ms: int
    hints: int
    wrong_attempts: int
    keystrokes: int
    extra_keys: int = 0


@dataclass(frozen=True, slots=True)
class Grade:
    rating: Rating
    penalty: float
    reason: str
    costs: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.costs and self.penalty == 0


def costs_of(attempt: Attempt, ratio: float | None) -> tuple[str, ...]:
    """Everything that cost on this attempt, not just the headline reason."""
    out = []
    if attempt.hints:
        out.append("answer revealed")
    if attempt.extra_keys:
        n = attempt.extra_keys
        out.append(f"{n} keystroke{'s' if n > 1 else ''} over par")
    if attempt.wrong_attempts:
        n = attempt.wrong_attempts
        out.append(f"{n} restart{'s' if n > 1 else ''}")
    if ratio is not None and ratio > SLOW_FACTOR:
        out.append(f"slow ({ratio:.1f}x your best)")
    return tuple(out)


def grade(attempt: Attempt, baseline_ms: int | None) -> Grade:
    """baseline_ms is the reference time for this card, or None if unseen."""
    if not attempt.solved:
        return Grade(Rating.Again, 1.0, "wrong", ("not solved",))

    penalty = min(1.0, attempt.hints * ANSWER_PENALTY
                  + attempt.wrong_attempts * WRONG_KEY_PENALTY
                  + attempt.extra_keys * EXTRA_KEY_PENALTY)

    ratio = (attempt.elapsed_ms / baseline_ms) if baseline_ms else None
    slow = ratio is not None and ratio > SLOW_FACTOR
    fast = ratio is not None and ratio < FAST_FACTOR

    if slow:
        # A ramp, not a cliff: 9x your reference should not cost the same as 2.1x.
        over = min((ratio - SLOW_FACTOR) * SLOW_RAMP, MAX_SLOW_PENALTY)
        penalty = min(1.0, penalty + over)

    costs = costs_of(attempt, ratio)
    if costs:
        return Grade(Rating.Hard, penalty, costs[0], costs)
    if fast:
        return Grade(Rating.Easy, penalty, "clean and fast")
    return Grade(Rating.Good, penalty, "clean")


def update_ewma(previous: float | None, penalty: float) -> float:
    if previous is None:
        return penalty
    return previous * (1 - PENALTY_EWMA_ALPHA) + penalty * PENALTY_EWMA_ALPHA
