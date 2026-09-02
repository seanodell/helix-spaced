from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Range:
    anchor: int
    head: int

    @property
    def start(self) -> int:
        return min(self.anchor, self.head)

    @property
    def end(self) -> int:
        return max(self.anchor, self.head)

    @property
    def forward(self) -> bool:
        return self.head >= self.anchor

    @property
    def cursor(self) -> int:
        return self.head - 1 if self.head > self.anchor else self.head

    def flip(self) -> "Range":
        return Range(self.head, self.anchor)

    def widen(self, n: int) -> "Range":
        if self.anchor == self.head and self.head < n:
            return Range(self.head, self.head + 1)
        return self

    def put_cursor(self, n: int, pos: int, extend: bool) -> "Range":
        """Port of helix-core Range::put_cursor -- how every motion lands its cursor."""
        if not extend:
            return Range(pos, min(pos + 1, n))
        if self.head >= self.anchor and pos < self.anchor:
            anchor = min(self.anchor + 1, n)
        elif self.head < self.anchor and pos >= self.anchor:
            anchor = max(self.anchor - 1, 0)
        else:
            anchor = self.anchor
        return Range(anchor, min(pos + 1, n)) if anchor <= pos else Range(anchor, pos)

    def overlaps(self, other: "Range") -> bool:
        return self.start < other.end and other.start < self.end

    def merge(self, other: "Range") -> "Range":
        lo, hi = min(self.start, other.start), max(self.end, other.end)
        return Range(lo, hi) if self.forward else Range(hi, lo)


def normalize(ranges: list[Range], primary: int) -> tuple[list[Range], int]:
    tagged = sorted(enumerate(ranges), key=lambda p: (p[1].start, p[1].end))
    out: list[Range] = []
    new_primary = 0
    for idx, r in tagged:
        if out and out[-1].overlaps(r):
            out[-1] = out[-1].merge(r)
            if idx == primary:
                new_primary = len(out) - 1
        else:
            if idx == primary:
                new_primary = len(out)
            out.append(r)
    return out, new_primary
