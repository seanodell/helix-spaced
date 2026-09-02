from dataclasses import dataclass, field, replace

from .ranges import Range, normalize


@dataclass(frozen=True, slots=True)
class State:
    text: str
    ranges: tuple[Range, ...] = (Range(0, 1),)
    primary: int = 0
    mode: str = "normal"

    @staticmethod
    def new(text: str, ranges: tuple[Range, ...] | None = None) -> "State":
        rs = ranges or (Range(0, 1).widen(len(text)),)
        return State(text, rs)

    @property
    def cursor(self) -> int:
        return self.ranges[self.primary].cursor

    def with_ranges(self, ranges: list[Range]) -> "State":
        rs, p = normalize([r for r in ranges], self.primary)
        return replace(self, ranges=tuple(rs), primary=min(p, len(rs) - 1))

    def map_ranges(self, fn) -> "State":
        return self.with_ranges([fn(r) for r in self.ranges])

    def selected(self, r: Range) -> str:
        return self.text[r.start:r.end]


@dataclass
class Editor:
    """Mutable shell around State: registers, undo history, pending counts."""

    state: State
    registers: dict[str, list[str]] = field(default_factory=dict)
    history: list[State] = field(default_factory=list)
    future: list[State] = field(default_factory=list)
    goal_column: int | None = None
    last_find: tuple[str, str] | None = None

    @staticmethod
    def new(text: str) -> "Editor":
        return Editor(State.new(text))

    @property
    def text(self) -> str:
        return self.state.text

    @property
    def ranges(self) -> tuple[Range, ...]:
        return self.state.ranges

    def checkpoint(self) -> None:
        self.history.append(self.state)
        self.future.clear()

    def undo(self) -> None:
        if self.history:
            self.future.append(self.state)
            self.state = self.history.pop()

    def redo(self) -> None:
        if self.future:
            self.history.append(self.state)
            self.state = self.future.pop()
