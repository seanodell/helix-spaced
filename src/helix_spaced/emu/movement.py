"""Port of helix-core word/char/line movement.

The word motions follow helix-core/src/movement.rs: `word_move` rewrites the
incoming range into a one-grapheme block cursor pointing in the motion's
direction, then `range_to_target` walks characters until it crosses a boundary
that satisfies the target predicate. The `head == head_start` case is what makes
`w` drop its anchor at the start of the run it lands in rather than dragging it
from the previous position.
"""

from .chars import is_line_ending, is_long_word_boundary, is_word_boundary
from .ranges import Range

NEXT_WORD_START = "next_word_start"
NEXT_WORD_END = "next_word_end"
PREV_WORD_START = "prev_word_start"
PREV_WORD_END = "prev_word_end"
NEXT_LONG_WORD_START = "next_long_word_start"
NEXT_LONG_WORD_END = "next_long_word_end"
PREV_LONG_WORD_START = "prev_long_word_start"
PREV_LONG_WORD_END = "prev_long_word_end"

_PREV = {PREV_WORD_START, PREV_WORD_END, PREV_LONG_WORD_START, PREV_LONG_WORD_END}
_LONG = {NEXT_LONG_WORD_START, NEXT_LONG_WORD_END, PREV_LONG_WORD_START, PREV_LONG_WORD_END}
_STARTS = {NEXT_WORD_START, NEXT_LONG_WORD_START}


def _reached(target: str, prev_ch: str, next_ch: str) -> bool:
    boundary = is_long_word_boundary if target in _LONG else is_word_boundary
    if not boundary(prev_ch, next_ch):
        return False
    if target in _STARTS:
        return is_line_ending(next_ch) or not next_ch.isspace()
    return (not prev_ch.isspace()) or is_line_ending(next_ch)


def _range_to_target(text: str, target: str, origin: Range) -> Range:
    is_prev = target in _PREV
    step = -1 if is_prev else 1

    def at(i: int) -> str | None:
        """Character consumed when advancing from position i in the motion direction."""
        j = i - 1 if is_prev else i
        return text[j] if 0 <= j < len(text) else None

    def behind(i: int) -> str | None:
        j = i if is_prev else i - 1
        return text[j] if 0 <= j < len(text) else None

    if at(origin.head) is None:
        return origin

    anchor, head = origin.anchor, origin.head
    prev_ch = behind(head)

    while True:
        ch = at(head)
        if ch is not None and is_line_ending(ch):
            prev_ch = ch
            head += step
        else:
            break
    if prev_ch is not None and is_line_ending(prev_ch):
        anchor = head

    head_start = head
    while True:
        next_ch = at(head)
        if next_ch is None:
            break
        if prev_ch is not None and _reached(target, prev_ch, next_ch):
            if head == head_start:
                anchor = head
            else:
                break
        prev_ch = next_ch
        head += step

    return Range(anchor, head)


def word_move(text: str, range_: Range, count: int, target: str) -> Range:
    is_prev = target in _PREV
    if (not is_prev and range_.head == len(text)) or (is_prev and range_.head == 0):
        return range_

    if is_prev:
        start = Range(range_.head, max(range_.head - 1, 0)) if range_.anchor < range_.head \
            else Range(range_.head + 1, range_.head)
    else:
        start = Range(max(range_.head - 1, 0), range_.head) if range_.anchor < range_.head \
            else Range(range_.head, range_.head + 1)

    r = start
    for _ in range(count):
        nxt = _range_to_target(text, target, r)
        if nxt == r:
            break
        r = nxt
    return r


def line_starts(text: str) -> list[int]:
    out = [0]
    for i, c in enumerate(text):
        if c == "\n":
            out.append(i + 1)
    return out


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos)


def line_bounds(text: str, line: int) -> tuple[int, int]:
    """(start, end) of `line`, end exclusive of the trailing newline."""
    starts = line_starts(text)
    line = max(0, min(line, len(starts) - 1))
    start = starts[line]
    end = text.find("\n", start)
    return start, len(text) if end == -1 else end


def move_horizontally(text: str, r: Range, count: int, direction: int, extend: bool) -> Range:
    pos = max(0, min(r.cursor + count * direction, len(text)))
    return r.put_cursor(len(text), pos, extend)


def move_vertically(text: str, r: Range, count: int, direction: int, extend: bool,
                    goal: int | None) -> tuple[Range, int]:
    cur = r.cursor
    line = line_of(text, cur)
    lstart, _ = line_bounds(text, line)
    col = goal if goal is not None else cur - lstart
    target = line + count * direction
    if target < 0 or target >= len(line_starts(text)):
        return r, col
    if extend and target > last_content_line(text):
        return r, col
    ts, te = line_bounds(text, target)
    return r.put_cursor(len(text), min(ts + col, te), extend), col


def last_content_line(text: str) -> int:
    """Index of the last line, skipping a trailing empty line -- Helix's `ge`."""
    n = len(line_starts(text))
    if n > 1 and line_bounds(text, n - 1) == (len(text), len(text)):
        return n - 2
    return n - 1


def detect_indent(text: str) -> str:
    """Helix auto-detects the buffer's indent unit; tab when nothing is indented."""
    widths: dict[int, int] = {}
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        if stripped and stripped != line:
            w = len(line) - len(stripped)
            widths[w] = widths.get(w, 0) + 1
        elif line.startswith("\t"):
            return "\t"
    if not widths:
        return "\t"
    smallest = min(widths)
    return " " * smallest
