"""`helix-spaced keys` -- show what the terminal actually sends.

An Alt key that does nothing is usually the terminal, not the trainer: on macOS
Option types accented characters unless it is configured to send Meta. This
prints the raw Textual name beside the Helix notation it translates to, so the
difference is visible.
"""

from collections import deque

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from .keymap import from_textual

WANTED = ["<A-C>", "<A-J>", "<A-;>", "<A-d>", "<A-s>", "<A-`>", "<C-c>", "<C-w>"]


class KeyCheck(App):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #head { padding: 1 2; background: $panel; text-style: bold; }
    #log  { padding: 1 2; height: 1fr; }
    #foot { padding: 1 2; color: $text-muted; }
    """

    def __init__(self):
        super().__init__()
        self.seen: deque = deque(maxlen=12)
        self.found: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Static("Press keys to see what your terminal sends", id="head")
        yield Static(id="log")
        yield Static(id="foot")

    def on_mount(self) -> None:
        self.render_log()

    def render_log(self) -> None:
        out = Text()
        for name, char, helix in self.seen:
            out.append(f"{name:<24}", style="bold")
            out.append(f"{char!r:<8}", style="dim")
            if helix:
                out.append(f"-> {helix}\n", style="green")
            else:
                out.append("-> ignored\n", style="red")
        self.query_one("#log", Static).update(out)

        foot = Text("Alt keys the deck needs: ", style="dim")
        for k in WANTED:
            foot.append(f" {k} ", style="green" if k in self.found else "dim")
        foot.append("\n\nA key that shows no name at all is being eaten by the "
                    "terminal:\nturn on Option-as-Meta. A key that arrives without "
                    "its Alt\n(Alt-; showing as ';') needs a terminal with the "
                    "kitty keyboard\nprotocol - Ghostty, kitty, WezTerm, foot.",
                    style="dim")
        foot.append("\n\nCtrl-Q to quit", style="dim")
        self.query_one("#foot", Static).update(foot)

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        if event.key == "ctrl+q":
            self.exit()
            return
        helix = from_textual(event.key, event.character)
        if helix in WANTED:
            self.found.add(helix)
        self.seen.append((event.key, event.character, helix))
        self.render_log()


def run() -> None:
    KeyCheck().run()
