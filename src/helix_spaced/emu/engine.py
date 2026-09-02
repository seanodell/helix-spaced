"""Key-driven Helix emulator.

Feed it Helix key notation, read back text + selections. Behaviour is pinned by
tests/fixtures/helix_truth.json, which is generated from a real hx process by
tools/calibrate.py -- that fixture, not this file, is the specification.
"""

import re

from . import movement as mv
from .chars import is_long_word_boundary, is_word_boundary
from .keys import Key, parse
from .ranges import Range
from .state import Editor, State

# Keys that open a sub-menu and must swallow what follows. Helix's `[`/`]`, `z`,
# `Z`, space, register select and window mode are not implemented, but they are
# listed so their sequences are consumed whole instead of leaking keys.
PREFIXES = frozenset({"f", "t", "F", "T", "r", "g", "m",
                      "[", "]", "z", "Z", " ", '"', "<C-w>"})

# Keys that open a prompt. Everything typed after one belongs to the prompt, not
# to normal mode -- without this, `sd<ret>` (search for "d") would run `d` and
# delete the selection.
PROMPT_KEYS = frozenset({"s", "S", "/", "?", ":", "|", "!", "<A-!>", "<A-|>",
                         "<A-k>", "<A-K>"})


def incomplete(seq: list[Key]) -> bool:
    """Whether a pending sequence still needs more keys."""
    head, n = seq[0].spec, len(seq)
    if head == "m":
        if n < 2:
            return True
        second = seq[1].spec
        if second in ("i", "a", "s", "d"):
            return n < 3
        if second == "r":
            return n < 4
        return False
    return n < 2


# Match-mode object keys -> the delimiter pair they stand for.
PAIRS = {
    "(": ("(", ")"), ")": ("(", ")"), "b": ("(", ")"),
    "{": ("{", "}"), "}": ("{", "}"), "B": ("{", "}"),
    "[": ("[", "]"), "]": ("[", "]"),
    "<": ("<", ">"), ">": ("<", ">"),
    '"': ('"', '"'), "'": ("'", "'"), "`": ("`", "`"),
}
OPENERS = {o for o, _ in PAIRS.values()}
CLOSERS = {c for _, c in PAIRS.values()}

# `mib` means "inside the parens", but `msb` surrounds with a literal b -- the
# alias letters are text-object names, not delimiters.
BRACKETS = {k: v for k, v in PAIRS.items() if k in OPENERS | CLOSERS and k not in "\"'`"}


def surround_pair(ch: str) -> tuple[str, str]:
    return BRACKETS.get(ch, (ch, ch))


WORD_TARGETS = {
    "w": mv.NEXT_WORD_START, "b": mv.PREV_WORD_START, "e": mv.NEXT_WORD_END,
    "W": mv.NEXT_LONG_WORD_START, "B": mv.PREV_LONG_WORD_START, "E": mv.NEXT_LONG_WORD_END,
}


class Engine:
    def __init__(self, text: str):
        self.ed = Editor.new(text)
        self.count = 0
        self.pending: list[Key] = []
        self.pending_count = 1
        self.prompt: str | None = None
        self.prompt_buf = ""
        self.extend = False

    # -- public ---------------------------------------------------------

    @staticmethod
    def run(text: str, keys: str) -> "Engine":
        e = Engine(text)
        e.feed(keys)
        return e

    def feed(self, keys: str) -> "Engine":
        for k in parse(keys):
            self.key(k)
        return self

    @property
    def state(self) -> State:
        return self.ed.state

    @property
    def text(self) -> str:
        return self.ed.text

    @property
    def ranges(self):
        return self.ed.ranges

    @property
    def spans(self) -> list[tuple[int, int]]:
        return [(r.start, r.end) for r in self.ed.ranges]

    def render(self) -> str:
        out, prev = "", 0
        for a, b in self.spans:
            out += self.text[prev:a] + "[" + self.text[a:b] + "]"
            prev = b
        return out + self.text[prev:]

    # -- dispatch -------------------------------------------------------

    def key(self, k: Key) -> None:
        if self.prompt is not None:
            return self._prompt_key(k)
        if self.ed.state.mode == "insert":
            return self._insert_key(k)
        if self.pending:
            self.pending.append(k)
            if not incomplete(self.pending):
                seq, self.pending = self.pending, []
                self._sequence(seq, self.pending_count)
            return
        c = k.char
        if c and c.isdigit() and not (c == "0" and self.count == 0):
            self.count = self.count * 10 + int(c)
            return
        n = self.count or 1
        self.count = 0
        if k.spec in PREFIXES:
            self.pending = [k]
            self.pending_count = n
            return
        if k.spec in PROMPT_KEYS:
            self.prompt = k.spec
            self.prompt_buf = ""
            return
        self._normal(k, n)

    # -- prompts -----------------------------------------------------------

    def _prompt_key(self, k: Key) -> None:
        if k.spec == "<esc>":
            self.prompt, self.prompt_buf = None, ""
            return
        if k.spec == "<backspace>":
            self.prompt_buf = self.prompt_buf[:-1]
            return
        if k.spec in ("<ret>", "\n"):
            kind, pattern = self.prompt, self.prompt_buf
            self.prompt, self.prompt_buf = None, ""
            self._run_prompt(kind, pattern)
            return
        if k.char:
            self.prompt_buf += k.char

    def _run_prompt(self, kind: str, pattern: str) -> None:
        if not pattern:
            return
        try:
            rx = re.compile(pattern)
        except re.error:
            return
        if kind == "s":
            return self._select_regex(rx)
        if kind == "S":
            return self._split_regex(rx)
        if kind in ("/", "?"):
            return self._search(rx, forward=kind == "/")
        return None

    def _select_regex(self, rx) -> None:
        out = []
        for r in self.state.ranges:
            for m in rx.finditer(self.text[r.start:r.end]):
                if m.end() > m.start():
                    out.append(Range(r.start + m.start(), r.start + m.end()))
        if out:
            self._set(self.state.with_ranges(out))

    def _split_regex(self, rx) -> None:
        out = []
        for r in self.state.ranges:
            pos = r.start
            for m in rx.finditer(self.text[r.start:r.end]):
                if r.start + m.start() > pos:
                    out.append(Range(pos, r.start + m.start()))
                pos = r.start + m.end()
            if pos < r.end:
                out.append(Range(pos, r.end))
        if out:
            self._set(self.state.with_ranges(out))

    def _search(self, rx, forward: bool) -> None:
        t = self.text
        start = self.state.ranges[self.state.primary].cursor
        hits = [m for m in rx.finditer(t) if m.end() > m.start()]
        if not hits:
            return
        if forward:
            nxt = next((m for m in hits if m.start() > start), hits[0])
        else:
            earlier = [m for m in hits if m.start() < start]
            nxt = earlier[-1] if earlier else hits[-1]
        self._set(self.state.with_ranges([Range(nxt.start(), nxt.end())]))

    # -- multi-key sequences ---------------------------------------------

    def _sequence(self, seq: list[Key], n: int) -> None:
        """Run a completed prefix sequence. Unimplemented ones are no-ops, never
        a partial match -- a swallowed prefix would otherwise turn the next key
        into an unrelated command."""
        head = seq[0].spec
        if head in ("f", "t", "F", "T"):
            if seq[1].char:
                self.ed.last_find = (head, seq[1].char)
                self._find(head, seq[1].char, n)
        elif head == "r":
            if seq[1].char:
                self._replace_char(seq[1].char)
        elif head == "g":
            self._goto(seq[1], n)
        elif head == "m":
            self._match(seq, n)

    # -- normal mode -----------------------------------------------------

    def _normal(self, k: Key, n: int) -> None:
        ed = self.ed
        spec = k.spec

        if spec in ("h", "<left>"):
            return self._motion(lambda r: mv.move_horizontally(self.text, r, n, -1, self.extend))
        if spec in ("l", "<right>"):
            return self._motion(lambda r: mv.move_horizontally(self.text, r, n, 1, self.extend))
        if spec in ("j", "k", "<down>", "<up>"):
            d = 1 if spec in ("j", "<down>") else -1
            return self._vertical(n, d)
        if spec in WORD_TARGETS:
            t = WORD_TARGETS[spec]
            return self._motion(lambda r: self._word(r, n, t))
        if spec == "G":
            return self._goto_line(n)

        if spec == "x":
            return self._extend_line_below(n)
        if spec == "X":
            return self._extend_to_line_bounds()
        if spec == "%":
            return self._set(State.new(self.text, (Range(0, len(self.text)),)))
        if spec == ";":
            return self._map(lambda r: Range(r.cursor, r.cursor).widen(len(self.text)))
        if spec == ",":
            return self._keep_primary()
        if spec == "<A-;>":
            return self._map(lambda r: r.flip())
        if spec == "<A-:>":
            return self._map(lambda r: r if r.forward else r.flip())
        if spec == "v":
            self.extend = not self.extend
            return
        if spec == "C":
            return self._copy_selection(n, 1)
        if spec == "<A-C>":
            return self._copy_selection(n, -1)
        if spec == "<A-,>":
            return self._remove_primary()

        if spec in ("d", "<A-d>"):
            return self._delete(yank=spec == "d")
        if spec in ("c", "<A-c>"):
            self._delete(yank=spec == "c", collapse=True)
            return self._enter_insert()
        if spec == "i":
            return self._enter_insert([Range(r.end, r.start) for r in self.state.ranges])
        if spec == "a":
            return self._enter_insert([Range(r.start, r.end) for r in self.state.ranges])
        if spec == "I":
            return self._insert_at(lambda r: self._first_non_blank(r.start))
        if spec == "A":
            return self._insert_at(lambda r: mv.line_bounds(self.text, mv.line_of(self.text, r.cursor))[1])
        if spec == "o":
            return self._open_line(1)
        if spec == "O":
            return self._open_line(0)
        if spec == "y":
            ed.registers['"'] = [self.state.selected(r) for r in ed.ranges]
            return
        if spec in ("p", "P"):
            return self._paste(after=spec == "p", count=n)
        if spec == "~":
            return self._map_text(lambda s: s.swapcase())
        if spec == "`":
            return self._map_text(lambda s: s.lower())
        if spec == "<A-`>":
            return self._map_text(lambda s: s.upper())
        if spec == "J":
            return self._join(n)
        if spec == ">":
            return self._indent(n, 1)
        if spec == "<":
            return self._indent(n, -1)
        if spec == "u":
            return ed.undo()
        if spec == "U":
            return ed.redo()
        if spec == "<esc>":
            self.extend = False
            return

    # -- match mode --------------------------------------------------------

    def _match(self, seq: list[Key], n: int) -> None:
        what = seq[1].spec
        if what == "m":
            return self._goto_matching()
        if what in ("i", "a"):
            return self._textobject(seq[2].spec, around=what == "a")
        if what == "s":
            return self._surround_add(seq[2].spec)
        if what == "d":
            return self._surround_delete(seq[2].spec)
        if what == "r":
            return self._surround_replace(seq[2].spec, seq[3].spec)
        return None

    def _pair_at(self, pos: int, open_ch: str, close_ch: str) -> tuple[int, int] | None:
        """Innermost pair enclosing pos, honouring nesting."""
        t = self.text
        if open_ch == close_ch:
            # A quote under the cursor is ambiguous -- Helix cannot tell opener
            # from closer -- so it only matches a pair strictly containing pos.
            hits = [i for i, c in enumerate(t) if c == open_ch]
            for a, b in zip(hits[0::2], hits[1::2]):
                if a < pos < b:
                    return a, b
            return None
        depth, start = 0, None
        for i in range(pos, -1, -1):
            c = t[i]
            if c == close_ch and i != pos:
                depth += 1
            elif c == open_ch:
                if depth == 0:
                    start = i
                    break
                depth -= 1
        if start is None:
            return None
        depth = 0
        for j in range(start + 1, len(t)):
            c = t[j]
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                if depth == 0:
                    return start, j
                depth -= 1
        return None

    def _goto_matching(self) -> None:
        t = self.text

        def one(r: Range) -> Range:
            pos = r.cursor
            ch = t[pos] if pos < len(t) else ""
            for key, (o, c) in PAIRS.items():
                if o == c or key not in (o, c):
                    continue
                if ch == o or ch == c:
                    found = self._pair_at(pos, o, c)
                    if found:
                        target = found[1] if ch == o else found[0]
                        return Range(target, target).widen(len(t))
            return r

        self._motion(one)

    def _word_object(self, pos: int, around: bool, long: bool) -> tuple[int, int] | None:
        t = self.text
        if not t:
            return None
        pos = min(pos, len(t) - 1)
        boundary = (lambda a, b: is_long_word_boundary(a, b)) if long else \
            (lambda a, b: is_word_boundary(a, b))
        start = pos
        while start > 0 and not boundary(t[start - 1], t[start]):
            start -= 1
        end = pos
        while end + 1 < len(t) and not boundary(t[end], t[end + 1]):
            end += 1
        if not around:
            return start, end + 1
        stop = end + 1
        while stop < len(t) and t[stop] in " \t":
            stop += 1
        if stop == end + 1:
            while start > 0 and t[start - 1] in " \t":
                start -= 1
        return start, stop

    def _textobject(self, obj: str, around: bool) -> None:
        def one(r: Range) -> Range:
            if obj in ("w", "W"):
                found = self._word_object(r.cursor, around, obj == "W")
                return Range(*found) if found else r
            if obj in PAIRS:
                o, c = PAIRS[obj]
                found = self._pair_at(r.cursor, o, c)
                if not found:
                    return r
                a, b = found
                return Range(a, b + 1) if around else Range(a + 1, b)
            return r

        self._motion(one)

    def _surround_add(self, ch: str) -> None:
        o, c = surround_pair(ch)
        st = self.state
        specs = [(r.start, r.end, o + st.selected(r) + c) for r in st.ranges]
        self._apply(specs, lambda p, r: Range(p[0], p[1]))

    def _surround_delete(self, ch: str) -> None:
        if ch not in PAIRS:
            return
        o, c = PAIRS[ch]
        pairs = []
        for r in self.state.ranges:
            found = self._pair_at(r.cursor, o, c)
            if found:
                pairs.append(found)
        if not pairs:
            return
        specs = []
        for a, b in sorted(set(pairs)):
            specs.append((a, a + 1, ""))
            specs.append((b, b + 1, ""))
        self.ed.checkpoint()
        text, _ = self._splice(specs)
        shift = self._shifter(specs)
        st = self.state
        self._set(State(text, st.ranges, st.primary, st.mode).with_ranges(
            [Range(shift(r.anchor), shift(r.head)).widen(len(text)) for r in st.ranges]))

    def _surround_replace(self, old: str, new: str) -> None:
        if old not in PAIRS or new not in PAIRS:
            return
        o, c = PAIRS[old]
        no, nc = PAIRS[new]
        pairs = []
        for r in self.state.ranges:
            found = self._pair_at(r.cursor, o, c)
            if found:
                pairs.append(found)
        if not pairs:
            return
        specs = []
        for a, b in sorted(set(pairs)):
            specs.append((a, a + 1, no))
            specs.append((b, b + 1, nc))
        self.ed.checkpoint()
        text, _ = self._splice(specs)
        st = self.state
        self._set(State(text, st.ranges, st.primary, st.mode))

    # -- helpers ---------------------------------------------------------

    def _set(self, st: State) -> None:
        self.ed.state = st

    def _map(self, fn) -> None:
        self._set(self.state.map_ranges(fn))

    def _motion(self, fn) -> None:
        self.ed.goal_column = None
        self._map(fn)

    def _word(self, r: Range, n: int, target: str) -> Range:
        out = mv.word_move(self.text, r, n, target)
        if not self.extend:
            return out
        return r.put_cursor(len(self.text), out.cursor, True)

    def _vertical(self, n: int, d: int) -> None:
        goal = self.ed.goal_column
        new, col = [], goal
        for r in self.state.ranges:
            nr, col = mv.move_vertically(self.text, r, n, d, self.extend, goal)
            new.append(nr)
        self.ed.goal_column = col
        self._set(self.state.with_ranges(new))

    def _first_non_blank(self, pos: int) -> int:
        s, e = mv.line_bounds(self.text, mv.line_of(self.text, pos))
        i = s
        while i < e and self.text[i] in " \t":
            i += 1
        return i

    def _goto(self, k: Key, n: int) -> None:
        spec = k.spec
        t = self.text
        if spec == "g":
            return self._goto_line(n if self.count or n > 1 else 1)
        if spec == "e":
            pos = self._line_to_char(mv.last_content_line(t))
            return self._map(lambda r: self._at(pos, r))
        if spec == "h":
            return self._map(lambda r: self._at(mv.line_bounds(t, mv.line_of(t, r.cursor))[0], r))
        if spec == "l":
            return self._map(
                lambda r: self._at(max(mv.line_bounds(t, mv.line_of(t, r.cursor))[1] - 1, 0), r))
        if spec == "s":
            return self._map(lambda r: self._at(self._first_non_blank(r.cursor), r))

    def _at(self, pos: int, r: Range | None = None) -> Range:
        base = r if r is not None else Range(pos, pos)
        return base.put_cursor(len(self.text), pos, self.extend and r is not None)

    def _goto_line(self, n: int) -> None:
        line = min(n - 1, mv.last_content_line(self.text))
        s, _ = mv.line_bounds(self.text, line)
        self._map(lambda r: self._at(s, r))

    def _find(self, kind: str, ch: str, n: int) -> None:
        t = self.text
        fwd = kind in "ft"
        till = kind in "tT"

        def one(r: Range) -> Range:
            pos = r.cursor
            base = Range(pos, min(pos + 1, len(t))) if not self.extend else r
            step = 2 if till else 1
            for _ in range(n):
                i = t.find(ch, pos + step) if fwd else t.rfind(ch, 0, max(pos - step + 1, 0))
                if i == -1:
                    return r
                pos = i
            target = pos - 1 if (till and fwd) else pos + 1 if (till and not fwd) else pos
            return base.put_cursor(len(t), target, True)

        self._motion(one)

    # -- selection ops ----------------------------------------------------

    def _line_range(self, r: Range) -> tuple[int, int]:
        t = self.text
        to = r.end if r.start == r.end else max(r.end - 1, r.start)
        return mv.line_of(t, r.start), mv.line_of(t, to)

    def _line_to_char(self, line: int) -> int:
        starts = mv.line_starts(self.text)
        return starts[line] if line < len(starts) else len(self.text)

    def _n_lines(self) -> int:
        return len(mv.line_starts(self.text))

    def _extend_line_below(self, n: int) -> None:
        def one(r: Range) -> Range:
            sl, el = self._line_range(r)
            start = self._line_to_char(sl)
            end = self._line_to_char(min(el + n, self._n_lines()))
            if start == r.start and end == r.end:
                end = self._line_to_char(min(el + n + 1, self._n_lines()))
            return Range(start, end)

        self._map(one)

    def _extend_to_line_bounds(self) -> None:
        def one(r: Range) -> Range:
            sl, el = self._line_range(r)
            return Range(self._line_to_char(sl), self._line_to_char(min(el + 1, self._n_lines())))

        self._map(one)

    def _keep_primary(self) -> None:
        st = self.state
        self._set(State(st.text, (st.ranges[st.primary],), 0, st.mode))

    def _remove_primary(self) -> None:
        st = self.state
        if len(st.ranges) < 2:
            return
        rs = list(st.ranges)
        rs.pop(st.primary)
        self._set(State(st.text, tuple(rs), min(st.primary, len(rs) - 1), st.mode))

    def _copy_selection(self, n: int, d: int) -> None:
        t = self.text
        st = self.state
        rs = list(st.ranges)
        src = rs[st.primary]
        sl = mv.line_of(t, src.start)
        col_a = src.start - self._line_to_char(sl)
        width = src.end - src.start
        added = 0
        line = sl
        limit = self._n_lines() - 1
        while added < n:
            line += d
            if line < 0 or line > limit:
                break
            ls, le = mv.line_bounds(t, line)
            if ls + col_a > le:
                continue
            a = ls + col_a
            rs.append(Range(a, min(a + width, len(t))))
            added += 1
        if not added:
            return
        # Helix makes the newly copied cursor the primary one, which is what a
        # following `,` (keep_primary_selection) then keeps.
        moved = State(st.text, tuple(rs), len(rs) - 1, st.mode)
        self._set(moved.with_ranges(rs))

    # -- text edits --------------------------------------------------------

    def _splice(self, specs: list[tuple[int, int, str]]) -> tuple[str, list[tuple[int, int]]]:
        """Apply per-range (start, end, replacement) edits; return new text + spans."""
        t = self.text
        order = sorted(range(len(specs)), key=lambda i: specs[i][0])
        out: list[str] = []
        pos = offset = 0
        placed: list[tuple[int, int]] = [(0, 0)] * len(specs)
        for i in order:
            s, e, repl = specs[i]
            out.append(t[pos:s])
            out.append(repl)
            pos = e
            ns = s + offset
            placed[i] = (ns, ns + len(repl))
            offset += len(repl) - (e - s)
        out.append(t[pos:])
        return "".join(out), placed

    def _apply(self, specs, to_range) -> None:
        text, placed = self._splice(specs)
        if text != self.text:
            self.ed.checkpoint()
        st = self.state
        rs = [to_range(p, r) for p, r in zip(placed, st.ranges)]
        self._set(State(text, st.ranges, st.primary, st.mode).with_ranges(rs))

    def _delete(self, yank: bool, collapse: bool = False) -> None:
        st = self.state
        if yank:
            self.ed.registers['"'] = [st.selected(r) for r in st.ranges]
        specs = [(r.start, r.end, "") for r in st.ranges]
        n_after = len(self.text) - sum(e - s for s, e, _ in specs)
        place = (lambda p, r: Range(p[0], p[0])) if collapse \
            else (lambda p, r: Range(p[0], p[0]).widen(n_after))
        self._apply(specs, place)

    def _map_text(self, fn) -> None:
        st = self.state
        specs = [(r.start, r.end, fn(st.selected(r))) for r in st.ranges]
        self._apply(specs, lambda p, r: Range(p[0], p[1]) if r.forward else Range(p[1], p[0]))

    def _replace_char(self, ch: str) -> None:
        self._map_text(lambda s: ch * len(s))

    def _enter_insert(self, ranges=None) -> None:
        st = self.state
        self._set(State(st.text, tuple(ranges) if ranges else st.ranges, st.primary, "insert"))

    def _insert_at(self, where) -> None:
        """Insert mode puts the head at the insertion point; `i` flips the range to do it."""
        self._enter_insert([Range(where(r), where(r)) for r in self.state.ranges])

    def _insert_key(self, k: Key) -> None:
        if k.spec == "<esc>":
            st = self.state
            self._set(State(st.text, st.ranges, st.primary, "normal").map_ranges(
                lambda r: r.widen(len(st.text))))
            return
        ch = k.char
        if ch is None:
            return
        st = self.state
        specs = [(r.head, r.head, ch) for r in st.ranges]
        text, _ = self._splice(specs)
        starts = sorted(sp[0] for sp in specs)

        def shift(pos: int) -> int:
            return pos + sum(len(ch) for s0 in starts if s0 <= pos)

        rs = [Range(shift(r.anchor), shift(r.head)) for r in st.ranges]
        self._set(State(text, tuple(rs), st.primary, "insert"))

    def _open_line(self, below: int) -> None:
        t = self.text
        st = self.state
        specs = []
        for r in st.ranges:
            line = mv.line_of(t, r.cursor)
            ls, le = mv.line_bounds(t, line)
            indent = t[ls:len(t[ls:le]) - len(t[ls:le].lstrip(" \t")) + ls]
            if below:
                specs.append((le, le, "\n" + indent))
            else:
                specs.append((ls, ls, indent + "\n"))
        self.ed.checkpoint()
        text, placed = self._splice(specs)
        rs = [Range(p[1], p[1]) if below else Range(max(p[1] - 1, 0), max(p[1] - 1, 0))
              for p in placed]
        self._set(State(text, tuple(rs), st.primary, "insert"))

    def _paste(self, after: bool, count: int) -> None:
        vals = self.ed.registers.get('"')
        if not vals:
            return
        t = self.text
        st = self.state
        specs = []
        for i, r in enumerate(st.ranges):
            val = vals[i] if i < len(vals) else vals[-1]
            val = val * count
            if val.endswith("\n"):
                line = mv.line_of(t, r.cursor)
                pos = self._line_to_char(min(line + 1, self._n_lines())) if after \
                    else mv.line_bounds(t, line)[0]
            else:
                pos = r.end if after else r.start
            specs.append((pos, pos, val))
        self._apply(specs, lambda p, r: Range(p[0], p[1]))

    def _join(self, n: int) -> None:
        """Helix drops the separator when the line being pulled up is blank."""
        t = self.text
        st = self.state
        last = len(mv.line_starts(t)) - 1
        lines = sorted({ln for r in st.ranges
                        for ln in range(self._line_range(r)[0], self._line_range(r)[1] + 1)
                        if ln < last})
        if not lines:
            return
        specs = []
        for ln in lines:
            _, e = mv.line_bounds(t, ln)
            j = e + 1
            while j < len(t) and t[j] in " \t":
                j += 1
            sep = "" if j == mv.line_bounds(t, ln + 1)[1] else " "
            specs.append((e, j, sep))
        self.ed.checkpoint()
        text, _ = self._splice(specs)
        shift = self._shifter(specs)
        st2 = State(text, st.ranges, st.primary, st.mode)
        self._set(st2.with_ranges(
            [Range(shift(r.anchor), shift(r.head)) for r in st.ranges]))

    def _shifter(self, specs):
        """Map an old position through a set of applied splices."""
        ordered = sorted(specs)

        def shift(pos: int) -> int:
            off = 0
            for s, e, repl in ordered:
                if e <= pos:
                    off += len(repl) - (e - s)
                elif s < pos:
                    off += max(0, s + len(repl) - pos)
            return max(pos + off, 0)

        return shift

    def _indent(self, n: int, d: int) -> None:
        t = self.text
        st = self.state
        unit = mv.detect_indent(t)
        lines = sorted({ln for r in st.ranges
                        for ln in range(self._line_range(r)[0], self._line_range(r)[1] + 1)})
        specs = []
        for ln in lines:
            s, e = mv.line_bounds(t, ln)
            if d > 0:
                specs.append((s, s, unit * n))
            else:
                strip = 0
                while strip < len(unit) * n and s + strip < e and t[s + strip] == " ":
                    strip += 1
                specs.append((s, s + strip, ""))
        if not specs:
            return
        self.ed.checkpoint()
        text, _ = self._splice(specs)
        shift = self._shifter(specs)
        st2 = State(text, st.ranges, st.primary, st.mode)
        self._set(st2.with_ranges([Range(shift(r.anchor), shift(r.head)) for r in st.ranges]))
