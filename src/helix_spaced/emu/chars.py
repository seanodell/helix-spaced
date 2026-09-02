from enum import Enum

LINE_ENDINGS = frozenset("\n\r\v\f\x85\u2028\u2029")


class Cat(Enum):
    EOL = 0
    WHITESPACE = 1
    WORD = 2
    PUNCTUATION = 3


def is_line_ending(c: str) -> bool:
    return c in LINE_ENDINGS


def categorize(c: str) -> Cat:
    if c in LINE_ENDINGS:
        return Cat.EOL
    if c.isspace():
        return Cat.WHITESPACE
    if c.isalnum() or c == "_":
        return Cat.WORD
    return Cat.PUNCTUATION


def is_word_boundary(a: str, b: str) -> bool:
    return categorize(a) != categorize(b)


def is_long_word_boundary(a: str, b: str) -> bool:
    ca, cb = categorize(a), categorize(b)
    if {ca, cb} == {Cat.WORD, Cat.PUNCTUATION}:
        return False
    return ca != cb
