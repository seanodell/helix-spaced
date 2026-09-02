"""Helix key notation.

`<gt>`, `<ret>` and friends collapse to the plain character they stand for, so
`>` and `<gt>` are the same key. Keys with no character (`<esc>`, arrows) keep a
symbolic name and report `char is None`, which is what stops insert mode from
typing them into the buffer.
"""

AS_CHAR = {
    "ret": "\n", "tab": "\t", "space": " ",
    "lt": "<", "gt": ">", "minus": "-", "percent": "%",
}

# Keys whose character is invisible when printed, so they are always shown in
# their bracketed form -- a trailing space in an answer is otherwise unreadable.
INVISIBLE = {" ": "space", "\n": "ret", "\t": "tab"}


class Key:
    __slots__ = ("alt", "ctrl", "name", "shift")

    def __init__(self, name: str, alt: bool = False, ctrl: bool = False, shift: bool = False):
        self.name = name
        self.alt = alt
        self.ctrl = ctrl
        self.shift = shift

    @property
    def char(self) -> str | None:
        if self.alt or self.ctrl or len(self.name) != 1:
            return None
        return self.name

    @property
    def spec(self) -> str:
        p = ("S-" if self.shift else "") + ("A-" if self.alt else "") + ("C-" if self.ctrl else "")
        if p or len(self.name) > 1:
            return f"<{p}{self.name}>"
        return self.name

    @property
    def display(self) -> str:
        """Spec, but never an invisible character."""
        if not self.alt and not self.ctrl and self.name in INVISIBLE:
            return f"<{INVISIBLE[self.name]}>"
        return self.spec

    def __eq__(self, other):
        if isinstance(other, str):
            return self.spec == other
        return isinstance(other, Key) and self.spec == other.spec

    def __hash__(self):
        return hash(self.spec)

    def __repr__(self):
        return f"Key({self.spec})"


def _one(tok: str) -> Key:
    body = tok[1:-1]
    alt = ctrl = shift = False
    while len(body) > 2 and body[1] == "-" and body[0] in "ACS":
        alt |= body[0] == "A"
        ctrl |= body[0] == "C"
        shift |= body[0] == "S"
        body = body[2:]
    if body in AS_CHAR:
        body = AS_CHAR[body]
    return Key(body, alt=alt, ctrl=ctrl, shift=shift)


def parse(seq: str) -> list[Key]:
    out, i = [], 0
    while i < len(seq):
        if seq[i] == "<" and ">" in seq[i + 1:]:
            j = seq.index(">", i)
            out.append(_one(seq[i:j + 1]))
            i = j + 1
        else:
            out.append(Key(seq[i]))
            i += 1
    return out


def notation(seq: str) -> str:
    """Re-emit a key sequence so every keystroke is visible.

    `parse(notation(s))` equals `parse(s)`, so what is displayed is exactly what
    can be typed back.
    """
    return "".join(k.display for k in parse(seq))
