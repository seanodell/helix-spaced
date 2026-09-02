"""Translate Textual key events into Helix key notation."""

SPECIAL = {
    "escape": "<esc>", "enter": "<ret>", "tab": "<tab>", "space": " ",
    "backspace": "<backspace>", "left": "<left>", "right": "<right>",
    "up": "<up>", "down": "<down>", "home": "<home>", "end": "<end>",
}

# Reserved by the trainer while a card is running. Helix binds none of these in
# normal mode -- its ctrl keys are b/f/u/d, e/y, i/o, s, a/x, w and c -- so
# reserving them costs no card.
CONTROL_KEYS = {"ctrl+q", "ctrl+c", "ctrl+n", "ctrl+t", "ctrl+r", "ctrl+g"}


def from_textual(key: str, character: str | None) -> str | None:
    """Return Helix notation, or None if the key should be ignored."""
    if key in CONTROL_KEYS:
        return None
    if key in SPECIAL:
        return SPECIAL[key]
    for prefix, mod in (("alt+", "A-"), ("ctrl+", "C-")):
        if key.startswith(prefix):
            rest = key[len(prefix):]
            rest = {"semicolon": ";", "comma": ",", "period": ".",
                    "full_stop": ".", "colon": ":"}.get(rest, rest)
            if len(rest) != 1:
                return None
            return f"<{mod}{rest}>"
    if character and character.isprintable() and len(character) == 1:
        return "<lt>" if character == "<" else character
    return None
