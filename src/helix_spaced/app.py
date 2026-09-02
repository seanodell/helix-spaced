"""Textual TUI.

A card starts the moment it appears, so every key belongs to Helix while one is
running. The controls are therefore the same letter throughout -- you just hold
ctrl while a card is live, and drop it once the card is graded.
"""

from collections import deque

from fsrs import Rating
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Static

from .deck import KEYS, load_dir
from .emu.engine import Engine
from .keymap import from_textual
from .scheduler import Trainer
from .session import Session
from .store import Store

ACTIVE, GRADED = "active", "graded"

NEXT, HINT, RESTART, GIVE_UP, QUIT = "next", "hint", "restart", "give_up", "quit"

# One letter per action. Hold ctrl while a card is running; press it bare once
# the card is graded and the trainer owns the keyboard again.
ACTIONS = {"n": NEXT, "t": HINT, "r": RESTART, "g": GIVE_UP, "q": QUIT}

HELP = {
    ACTIVE: [("t", "hint"), ("r", "restart"), ("g", "give up"),
             ("n", "skip"), ("q", "quit")],
    GRADED: [("n", "next"), ("q", "quit")],
}

RATING_STYLE = {
    Rating.Again: ("bold white on red", "AGAIN"),
    Rating.Hard: ("bold black on yellow", "HARD"),
    Rating.Good: ("bold white on green", "GOOD"),
    Rating.Easy: ("bold black on bright_cyan", "EASY"),
}


def render_buffer(engine: Engine) -> Text:
    """Buffer with selections highlighted; line ends shown so newline selections are visible."""
    spans = [s for s in engine.spans if s[1] > s[0]]
    points = {s[0] for s in engine.spans if s[1] == s[0]}
    out = Text()
    for i, ch in enumerate(engine.text):
        if i in points:
            out.append("▏", style="bold")
        selected = any(a <= i < b for a, b in spans)
        if ch == "\n":
            out.append("¬", style="reverse dim" if selected else "dim")
            out.append("\n")
        else:
            out.append(ch, style="reverse" if selected else "")
    if len(engine.text) in points:
        out.append("▏", style="bold")
    return out


def render_help(phase: str) -> Text:
    """Same letters in both phases; only the ctrl prefix comes and goes."""
    prefix = "^" if phase == ACTIVE else " "
    out = Text()
    for i, (key, label) in enumerate(HELP[phase]):
        if i:
            out.append("   ")
        out.append(f" {prefix}{key} ", style="reverse")
        out.append(f" {label}", style="dim")
    return out


def resolve(key: str, phase: str) -> str | None:
    """Map a key event to a trainer action, or None if it belongs to the buffer."""
    if key == "ctrl+c":
        return QUIT
    if key.startswith("ctrl+"):
        return ACTIONS.get(key[len("ctrl+"):])
    if phase == GRADED:
        if key in ("enter", "space"):
            return NEXT
        return ACTIONS.get(key)
    return None


class TrainerApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #prompt { padding: 1 2; background: $panel; color: $text; text-style: bold; }
    #buffer { padding: 1 2; height: auto; min-height: 6; }
    #typed  { padding: 0 2; height: 1; color: $text-muted; }
    #status { padding: 1 2; height: auto; }
    #note   { padding: 0 2; height: auto; }
    #hint   { padding: 0 2; height: auto; color: $warning; text-style: italic; }
    #help   { padding: 1 2; height: auto; }
    """

    def __init__(self, trainer: Trainer, limit: int | None = None):
        super().__init__()
        self.trainer = trainer
        self.limit = limit
        self.session: Session | None = None
        self.phase = ACTIVE
        self.done = 0
        self.recent: deque[str] = deque(maxlen=5)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="prompt")
            yield Static(id="buffer")
            yield Static(id="typed")
            yield Static(id="note")
            yield Static(id="status")
            yield Static(id="hint")
            yield Static(id="help")

    def on_mount(self) -> None:
        self.set_interval(0.1, self.tick)
        self.next_card()

    def tick(self) -> None:
        if self.session and self.session.running and self.is_running:
            self.refresh_status()

    def write(self, widget_id: str, content) -> None:
        """Update a panel, tolerating a screen that is being torn down."""
        try:
            self.query_one(widget_id, Static).update(content)
        except NoMatches:
            pass

    # -- flow ---------------------------------------------------------------

    def next_card(self) -> None:
        if self.limit is not None and self.done >= self.limit:
            self.exit(message=f"Done: {self.done} cards")
            return
        card = self.trainer.next_card(exclude=set(self.recent))
        if card is None:
            self.exit(message="No cards available")
            return
        self.session = Session(card)
        self.session.begin()
        self.set_phase(ACTIVE)
        self.write("#prompt", card.prompt)
        self.write("#hint", "")
        self.write("#note", Text(
            "navigation command - the buffer will not change", style="dim italic")
            if card.kind == KEYS else "")
        self.redraw()

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.write("#help", render_help(phase))

    def redraw(self) -> None:
        assert self.session
        self.write("#buffer", render_buffer(self.session.engine))
        self.write("#typed", Text(self.session.typed or " ", style="dim"))
        self.refresh_status()

    def refresh_status(self) -> None:
        if not self.session or self.phase == GRADED:
            return
        s = self.session
        bits = [f"{s.elapsed_ms / 1000:5.1f}s",
                f"due {len(self.trainer.due_pool())}", f"done {self.done}"]
        if s.hints:
            bits.append(f"hints {s.hints}")
        if s.wrong:
            bits.append(f"restarts {s.wrong}")
        self.write("#status", Text("   ".join(bits), style="dim"))

    def finish(self) -> None:
        assert self.session
        s = self.session
        g = self.trainer.review(s.card.id, s.attempt(), s.typed)
        self.set_phase(GRADED)
        self.done += 1
        self.recent.append(s.card.id)

        style, label = RATING_STYLE[g.rating]
        out = Text()
        out.append(f" {label} ", style=style)
        out.append(f"  {g.reason}  ")
        out.append(f"{s.elapsed_ms / 1000:.1f}s", style="dim")
        if not s.solved:
            out.append("\n\nSolution: ", style="dim")
            out.append(s.card.keys, style="bold")
        self.write("#status", out)

    def hint(self) -> None:
        """Hints get their own panel; #status is rewritten by the timer every tick."""
        assert self.session
        text = self.session.take_hint()
        self.write("#hint", Text(f"Hint: {text}"))

    # -- input --------------------------------------------------------------

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        if not self.session:
            return
        action = resolve(event.key, self.phase)
        if action is not None:
            self.run_action_key(action)
        elif self.phase == ACTIVE:
            self.buffer_key(event)

    def run_action_key(self, action: str) -> None:
        assert self.session
        if action == QUIT:
            self.exit(message=f"Done: {self.done} cards")
        elif action == NEXT:
            self.next_card()
        elif action == HINT and self.phase == ACTIVE:
            self.hint()
        elif action == RESTART and self.phase == ACTIVE:
            self.session.reset()
            self.redraw()
        elif action == GIVE_UP and self.phase == ACTIVE:
            self.session.give_up()
            self.finish()

    def buffer_key(self, event) -> None:
        assert self.session
        key = from_textual(event.key, event.character)
        if key is None:
            return
        solved = self.session.press(key)
        self.redraw()
        if solved:
            self.finish()


def run(limit: int | None = None) -> None:
    cards = load_dir()
    store = Store()
    TrainerApp(Trainer(cards, store), limit=limit).run()
    store.close()
