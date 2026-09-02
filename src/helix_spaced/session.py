"""Card-attempt state machine, kept free of any UI so it can be tested headlessly."""

import time
from dataclasses import dataclass, field

from .deck import Card
from .emu.engine import Engine
from .scoring import Attempt


@dataclass
class Session:
    card: Card
    engine: Engine = field(init=False)
    keys: list[str] = field(default_factory=list)
    hints: int = 0
    wrong: int = 0
    gave_up: bool = False
    solved: bool = False
    started: float | None = None
    finished: float | None = None

    def __post_init__(self):
        self.engine = self.card.initial()

    @property
    def typed(self) -> str:
        return "".join(self.keys)

    @property
    def running(self) -> bool:
        return self.started is not None and self.finished is None

    @property
    def elapsed_ms(self) -> int:
        if self.started is None:
            return 0
        end = self.finished if self.finished is not None else time.monotonic()
        return int((end - self.started) * 1000)

    def begin(self) -> None:
        """Start the clock. Keys are only accepted once this has been called."""
        if self.started is None:
            self.started = time.monotonic()

    def press(self, key: str) -> bool:
        """Feed one key. Returns True when the card is now solved."""
        if self.solved or self.gave_up or self.started is None:
            return self.solved
        self.keys.append(key)
        try:
            self.engine.feed(key)
        except Exception:  # noqa: BLE001 - a key the emulator rejects is a wrong answer
            self.wrong += 1
            return False
        if self.card.check(self.typed):
            self.solved = True
            self.finished = time.monotonic()
        return self.solved

    def reset(self) -> None:
        """Start the card over, keeping the clock running; counts against the score."""
        if self.solved:
            return
        self.wrong += 1
        self.keys.clear()
        self.engine = self.card.initial()

    def take_hint(self) -> str:
        self.hints += 1
        return self.card.hint or f"{len(self.card.keys)} keystrokes"

    def give_up(self) -> None:
        self.gave_up = True
        self.begin()
        self.finished = time.monotonic()

    def attempt(self) -> Attempt:
        return Attempt(
            solved=self.solved,
            elapsed_ms=self.elapsed_ms,
            hints=self.hints,
            wrong_attempts=self.wrong,
            keystrokes=len(self.keys),
        )
