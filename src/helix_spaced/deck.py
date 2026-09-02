"""Card loading and answer checking.

A card is graded on the resulting editor state, not on the keys pressed, so any
route to the right buffer and selection counts. `accept` only exists for cards
where several end states are legitimately correct.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .emu.engine import Engine
from .emu.keys import notation, parse

DECK_DIR = Path(__file__).resolve().parent.parent.parent / "decks"


def _state_of(engine: Engine):
    """Selection direction is meaningful in Helix, so compare ranges, not spans."""
    return engine.text, tuple((r.anchor, r.head) for r in engine.ranges)


STATE = "state"
KEYS = "keys"


def normalise(seq: str) -> tuple[str, ...]:
    return tuple(k.spec for k in parse(seq))


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    deck: str
    prompt: str
    text: str
    keys: str
    start: str = ""
    accept: tuple[str, ...] = field(default_factory=tuple)
    kind: str = STATE

    @property
    def answers(self) -> tuple[str, ...]:
        return (self.keys, *self.accept)

    @property
    def par(self) -> int:
        """Keystrokes in the shortest accepted answer. Anything above this is
        fumbling, so `accept` is also how a deck blesses a longer valid route."""
        return min(len(normalise(a)) for a in self.answers)

    @property
    def answer(self) -> str:
        """What to type, with every keystroke visible. Derived from `keys`, so it
        cannot drift from the solution the card is graded against, and it parses
        back to the same keys -- `T ` shows as `T<space>`."""
        return notation(self.keys)

    @property
    def solution(self) -> str:
        return self.keys

    def initial(self) -> Engine:
        e = Engine(self.text)
        if self.start:
            e.feed(self.start)
        return e

    def expected(self) -> Engine:
        e = self.initial()
        e.feed(self.keys)
        return e

    def check(self, attempt_keys: str) -> bool:
        """State cards are graded on where the editor ends up, so any route
        counts. Cards whose commands need a language server or a second file
        leave no state to compare, so those are graded on the keystrokes."""
        if self.kind == KEYS:
            return normalise(attempt_keys) in {normalise(a) for a in self.answers}
        try:
            got = self.initial().feed(attempt_keys)
        except Exception:  # noqa: BLE001 - any malformed key sequence is simply a wrong answer
            return False
        for t in self.answers:
            if _state_of(got) == _state_of(self.initial().feed(t)):
                return True
        return False


def load_dir(path: Path | None = None) -> list[Card]:
    path = path or DECK_DIR
    cards: list[Card] = []
    for f in sorted(path.glob("*.toml")):
        cards.extend(load_file(f))
    return cards


def load_file(path: Path) -> list[Card]:
    data = tomllib.loads(path.read_text())
    deck = data.get("deck", path.stem)
    out = []
    for i, c in enumerate(data.get("card", [])):
        cid = c.get("id") or f"{deck}:{i:03d}"
        out.append(Card(
            id=cid, deck=deck, prompt=c["prompt"], text=c["text"], keys=c["keys"],
            start=c.get("start", ""),
            accept=tuple(c.get("accept", ())), kind=c.get("kind", data.get("kind", STATE))))
    return out


def validate(cards: list[Card]) -> list[str]:
    """Every card's own solution must solve it, and ids must be unique."""
    problems, seen = [], set()
    for c in cards:
        if c.id in seen:
            problems.append(f"{c.id}: duplicate id")
        seen.add(c.id)
        if c.kind not in (STATE, KEYS):
            problems.append(f"{c.id}: unknown kind {c.kind!r}")
            continue
        if c.kind == KEYS:
            if not c.keys:
                problems.append(f"{c.id}: no keys to match")
            if not c.check(c.keys):
                problems.append(f"{c.id}: solution does not satisfy its own check")
            for alt in c.accept:
                if not c.check(alt):
                    problems.append(f"{c.id}: accepted answer {alt!r} is rejected")
            continue
        try:
            before = c.initial()
            after = c.expected()
        except Exception as e:  # noqa: BLE001 - report any breakage as a deck problem
            problems.append(f"{c.id}: solution raised {type(e).__name__}: {e}")
            continue
        if _state_of(after) == _state_of(before):
            problems.append(f"{c.id}: solution {c.keys!r} changes nothing")
        if not c.check(c.keys):
            problems.append(f"{c.id}: solution does not satisfy its own check")
    return problems
