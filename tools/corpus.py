"""Key sequences probed against real Helix to produce tests/fixtures/helix_truth.json."""

A = "the quick brown fox\n"
B = "alpha beta\ngamma delta\nepsilon zeta\n"
C = "foo_bar baz-qux (nested)\n"
D = "  indented one\n    deeper two\n"
E = "one\n\nthree\n"
F = "call(alpha, beta) end\n"
G = 'say "hi there" and {a: [1, 2]} ok\n'
H = "outer(inner(deep) x) y\n"

MOTION = ["h", "l", "j", "k", "w", "W", "b", "B", "e", "E",
          "2w", "3w", "5l", "2b", "2e", "ww", "wwb", "wb", "we",
          "gg", "ge", "gh", "gl", "gs", "G", "2G",
          "fq", "tq", "fo", "2fo", "wFt", "wTt", "fq;", "fo,"]
SELECT = ["x", "xx", "2x", "X", "%", ";", ",", "<A-;>", "<A-:>",
          "v", "vw", "vww", "ve", "vj", "wvb", "C", "2C", "<A-,>",
          "wx;", "%<A-;>"]
EDIT = ["d", "wd", "xd", "c!<esc>", "wcBIG<esc>", "iX<esc>", "aX<esc>",
        "IX<esc>", "AX<esc>", "oX<esc>", "OX<esc>", "wyP", "wygep",
        "r-", "wr-", "~", "w~", "J", "wJ", "<gt>", "<lt>", "xdu", "xduU",
        "dd", "wdb", "x<gt>", "x<lt>", "<A-d>", "<A-c>X<esc>"]

MATCH = ["miw", "maw", "miW", "maW", "wmiw", "wmaw",
         "mi(", "ma(", "mi{", "ma{", "mi[", "ma[", 'mi"', 'ma"',
         "wwmi(", "wwma(", "fbmi(", "fbma(",
         "mm", "f(mm", "f)mm",
         "ms(", "ms{", 'ms"', "wms(",
         "md(", "wwmd(", 'wwmd"',
         "mr({", "wwmr({", "wwmr([",
         "m", "ma", "mi", "mz", "zz", "[", "]", '"']

# Hold-out set: texts and sequences deliberately unlike the ones above, kept so
# that regressions in the awkward corners stay visible.
STRESS = {
    "unicode": "caf\u00e9 \u00fcber na\u00efve\n",
    "cjk": "hello \u4e16\u754c end\n",
    "tabs": "\tfirst line\n\t\tsecond\n",
    "trail": "spaced   out   words\n",
    "punct": "a.b,c;d:e f\n",
    "empty": "\n",
    "onechar": "x\n",
    "long": "alpha beta gamma delta epsilon zeta eta theta\n",
    "mixed": 'Foo_Bar baz.qux (a[b]c) "q" end\n',
}
STRESS_KEYS = [
    "3d", "2wd", "3x", "2xd", "3l", "2j", "5w", "3e", "2b",
    "Cd", "Cwd", "C~", "Cx;", "CC,", "Cr-", "Cid<esc>",
    "vwd", "vjd", "v2w", "vex", "vwy", "v%d",
    "wdd", "xdd", "wcX<esc>w", "yPp", "wywp", "ddu", "xdxd",
    "ged", "ggd", "glx", "gsd", "Ged",
    "fa;d", "ta,d", "F d", "2ta",
    "miw d", "maWd", "mi(d", "ma[d", 'mi"d', "msb", "md[",
    "gehd", "glld", "hhh", "lll", "kkk", "jjj",
    "w`", "w<A-`>", "x~",
    "wdwdu", "wdU", "xdduu",
    "%sa<ret>", "%se<ret>", "sxyz<esc>", "/e<ret>", "sd<ret>", "S <ret>",
    # select mode must be handed back after an edit: `w` here must not extend
    "vwdw", "vwyw", "vw~w", "vwpw", "vw<gt>w", "vwcX<esc>w", "vwr-w",
    "vwuw", "vwmi(w",
    # ...but pure selection work stays in select mode
    "vw;w", "vw_w", "vwxw", "vw<A-;>w",
    # delete to end of line, the thing with no single key
    "vgld", "wvgld", "wwvgld", "wwvgldw", "gld",
]

# Commands added to close the gap against helix-trainer's curriculum.
P = "first para\nstill first\n\nsecond para\nmore\n\nthird\n"
Q = "  padded  \nalpha beta gamma\none two one two\n"
GAP_KEYS = [
    "]p", "[p", "]p]p", "]p]p[p", "w]p", "j]p", "jj]p", "2]p",
    "mip", "map", "wmip", "wmap", "jjmip",
    "<A-J>", "w<A-J>", "R", "wyeR", "wywR",
    "_", "x_", "xx_", "<A-s>", "xx<A-s>", "x<A-s>",
    "iX<esc>.", "aY<esc>.", "wcZ<esc>.",
    "e*", "e*n", "e*nN", "e*nn", "wе*" if False else "we*n",
    '"ay"aP', '"ayw"aP', '"byd"bp',
    "T ", "wT ", "maw", "wmaw", "mi'", "ma'", "mi{", "ma{", "mi[", "ma[", 'ma"',
    "md[", "md{", 'md"', "mr[{", "mr{(", "ms*", "ms[", "ms'",
    "I!<esc>", "3h", "wl", "wh", "S <ret>", "Q", "q",
]

CASES = []
for text in (A, B, C, D, E):
    for keys in MOTION + SELECT + EDIT:
        CASES.append({"text": text, "keys": keys})
for text in (F, G, H, A):
    for keys in MATCH:
        CASES.append({"text": text, "keys": keys})
for text in STRESS.values():
    for keys in STRESS_KEYS:
        CASES.append({"text": text, "keys": keys})
for text in (P, Q, F, G):
    for keys in GAP_KEYS:
        CASES.append({"text": text, "keys": keys})

if __name__ == "__main__":
    import json
    import sys
    json.dump(CASES, sys.stdout)
