"""Translate Textual key events into Helix key notation.

Textual names a modified key in more than one shape depending on the terminal:
Alt-Shift-C arrives as `alt+C` or as `alt+shift+c`, and punctuation arrives by
name (`grave_accent`, `semicolon`). A name this function fails to recognise is
silently swallowed, which reads to the player as a dead key, so it splits the
modifiers off and works from the parts rather than matching whole strings.
"""

SPECIAL = {
    "escape": "<esc>", "enter": "<ret>", "tab": "<tab>", "space": " ",
    "backspace": "<backspace>", "left": "<left>", "right": "<right>",
    "up": "<up>", "down": "<down>", "home": "<home>", "end": "<end>",
}

# Textual spells punctuation out once it carries a modifier.
PUNCTUATION = {
    "semicolon": ";", "colon": ":", "comma": ",", "period": ".", "full_stop": ".",
    "grave_accent": "`", "apostrophe": "'", "quotation_mark": '"',
    "minus": "-", "hyphen": "-", "underscore": "_", "low_line": "_",
    "plus": "+", "equals_sign": "=", "asterisk": "*", "slash": "/",
    "backslash": "\\", "reverse_solidus": "\\",
    "left_square_bracket": "[", "right_square_bracket": "]",
    "left_curly_bracket": "{", "right_curly_bracket": "}",
    "left_parenthesis": "(", "right_parenthesis": ")",
    "less_than_sign": "<", "greater_than_sign": ">",
    "question_mark": "?", "exclamation_mark": "!", "commercial_at": "@", "at": "@",
    "number_sign": "#", "dollar_sign": "$", "percent_sign": "%",
    "ampersand": "&", "circumflex_accent": "^", "tilde": "~",
    "vertical_line": "|",
}

# Reserved by the trainer while a card is running. Helix binds none of these in
# normal mode -- its ctrl keys are b/f/u/d, e/y, i/o, s, a/x, w and c -- so
# reserving them costs no card.
# Ctrl-C is deliberately absent: it is Helix's toggle-comments and the trainer
# lets it through, so Ctrl-Q is the only way out.
CONTROL_KEYS = {"ctrl+q", "ctrl+n", "ctrl+t", "ctrl+r", "ctrl+g"}

# The same reserved keys in Helix notation, for deck-side checks: a card can
# never require one of these, and none may set a card's par.
RESERVED_NOTATION = frozenset({"<C-q>", "<C-n>", "<C-t>", "<C-r>", "<C-g>"})


def from_textual(key: str, character: str | None) -> str | None:
    """Return Helix notation, or None if the key should be ignored."""
    if key in CONTROL_KEYS:
        return None
    if key in SPECIAL:
        return SPECIAL[key]

    *mods, base = key.split("+")
    alt = "alt" in mods or "meta" in mods
    ctrl = "ctrl" in mods
    shift = "shift" in mods

    if not alt and not ctrl:
        if character and character.isprintable() and len(character) == 1:
            return "<lt>" if character == "<" else character
        return None

    ch = PUNCTUATION.get(base, base)
    if len(ch) != 1:
        # Fall back to whatever character the terminal reported, if any.
        if character and len(character) == 1 and character.isprintable():
            ch = character
        else:
            return None
    if shift and ch.isalpha():
        ch = ch.upper()

    return f"<{'A-' if alt else ''}{'C-' if ctrl else ''}{ch}>"
