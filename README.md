# helix-spaced

Spaced repetition trainer for Helix keybindings. Covers the ground `helix-trainer`
covers, but grades you: hints, wrong tries and slow answers all cost you, and the
cards you keep fumbling come back more often.

```
mise run install     # one time
mise run train       # start a session
mise run stats       # history + your hardest cards
```

## How grading works

Every attempt produces two numbers.

**An FSRS rating** decides when the card comes back at all:

| Result | Rating |
|---|---|
| Wrong, or gave up | `Again` |
| Hint used | `Hard` |
| Recovered after a restart | `Hard` |
| Clean, but over 2x your median for that card | `Hard` |
| Clean, normal speed | `Good` |
| Clean, under 0.6x your median, first try | `Easy` |

**A penalty (0..1)** is tracked separately as a per-card EWMA. It biases which of
the *currently due* cards get drawn first, so hard cards recur within a session
without distorting the spacing model. Easy cards still come around; they just
wait their turn.

Speed only counts once there is a baseline: the first time you see a card, you
cannot be graded slow.

## Keys

Cards start the moment they appear, so while one is running every key belongs to
Helix. The controls use the **same letter throughout** — you just hold ctrl while
a card is live, and drop it once the card is graded.

| While a card runs | Once graded | Action |
|---|---|---|
| `Ctrl-T` | `t` | hint (penalty) |
| `Ctrl-R` | `r` | restart the card (counts as a wrong try) |
| `Ctrl-G` | `g` | give up, show the answer |
| `Ctrl-N` | `n` | next card (skipping a live card scores nothing) |
| `Ctrl-Q` | `q` | quit |

Ctrl still works after grading, so muscle memory never misfires. `Enter` and
`Space` also move to the next card.

Those five are the only reserved keys. Helix's own ctrl bindings in normal mode
are `b`/`f`/`u`/`d`, `e`/`y`, `i`/`o`, `s`, `a`/`x`, `w` and `c`, none of which
overlap, so cards stay free to train them.

A card is solved the moment the buffer *and* selection match the target, so any
route that gets there counts, not just the keystrokes the card had in mind.

## How it knows what Helix does

The trainer contains a Helix emulator ([src/helix_spaced/emu](src/helix_spaced/emu)):
a text buffer plus multi-selection model, with `movement.py` ported from
helix-core's `movement.rs`. Nothing here is trusted on its own — there are two
separate things to prove, and each has its own check.

### 1. The emulator matches Helix

[tools/calibrate.py](tools/calibrate.py) drives a **real `hx` process** in a pty,
sends a key sequence, then overwrites the selection with a sentinel character and
reads the file back. Because that edit is length-preserving, the selected span is
recovered exactly; a second run collapses to the cursor first, which yields the
range's direction.

1382 cases across twenty-one buffers are checked in as
[tests/fixtures/helix_truth.json](tests/fixtures/helix_truth.json), and
[tests/test_conformance.py](tests/test_conformance.py) replays every one against
the emulator. That fixture, not the Python, is the specification.

```
mise run recalibrate     # re-pin after a Helix upgrade
```

The corpus deliberately includes a **hold-out block** (`STRESS` in
[tools/corpus.py](tools/corpus.py)): unicode, CJK, tabs, an empty buffer,
multi-cursor chains, counts on edits, prompt commands. It was written to be
unlike the rest and run cold. The emulator scored **95.6%** on it first time;
the four bugs it exposed are fixed and it now scores **99.4%**, the remainder
being an empty buffer.

That number, not the passing test count, is the honest measure of how far the
emulator can be trusted on keys no card anticipated.

### 2. Each card does what it claims

The conformance fixture proves the emulator is faithful on *its* corpus. It says
nothing about whether a given card is right. `validate` alone is circular: it
only checks a card's solution against the emulator's own idea of that solution.

So [tools/verify_deck.py](tools/verify_deck.py) runs **every card's `start + keys`
through real `hx`** and records the result;
[tests/test_deck_conformance.py](tests/test_deck_conformance.py) asserts the state
the trainer grades against is the state Helix actually reaches.

```
mise run verify-deck     # re-probe every card
```

This is not theoretical — it caught `,` (keep primary selection) keeping the
wrong cursor after `C`, which `validate` passed happily.

What is still not machine-checkable: that a card's English prompt *describes* its
keys. Only the editor behaviour can be proven.

### 3. Prefix and prompt keys cannot leak

A sub-menu key that is dropped instead of consumed turns the next keystroke into
an unrelated command — an unimplemented `m` once made `ma` mean *append*, and
before prompts were handled, `sd<ret>` (search for "d") ran `d` and deleted the
selection.
[tests/test_prefixes.py](tests/test_prefixes.py) checks every prefix (`g`, `m`,
`[`, `]`, `z`, `Z`, space, `"`, `C-w`) swallows its own sequence, including the
ones the emulator does not implement. The hx probe cannot cover this: a pending
prefix eats the probe's own sentinel keystroke.

Prompt keys (`s`, `S`, `/`, `?`, `:`, `|`, `!`) consume everything up to `<ret>`
or `<esc>`. `s`, `S`, `/` and `?` are implemented and pinned against hx; the rest
are consumed and do nothing.

### Probe limits, corrected for rather than emulated

Helix appends a final newline when saving, and the sentinel **cannot mark a
zero-width selection**. Where a case records no selection at all, the probe was
swallowed and only text is compared.

That second limit is not cosmetic: it once made `C` look correct when it was
wrong, because Helix's second cursor sat at end-of-file with zero width and was
invisible to the probe. A surprising "verified" result deserves a second look.

### Known deviations

Four, all recorded as `xfail` in `KNOWN_DEVIATIONS`:

- `2C` onto a *blank* line — Helix merges the two cursors into one backward range.
- `yPp`, `Cid<esc>`, `wcX<esc>w` on a buffer holding **only a newline** — paste and
  multi-cursor insert land a character differently in an empty file.

No card uses an empty buffer, so these are recorded rather than chased.

Not implemented at all (inert, so they cannot misfire, but no card can train
them): `.` repeat, macros `q`/`@`, `=` format, selection rotation, and the
treesitter text objects `mif`/`mic`, which need a real grammar.

## Adding cards

Decks are TOML in [decks](decks). There are two kinds.

### State cards (the default)

Graded on where the editor ends up — buffer text plus selection — so any route
that reaches the target counts, not just the keystrokes the card had in mind.

```toml
[[card]]
id = "motions:w"
prompt = "Move to the start of the next word"
text = "the quick brown fox\n"
keys = "w"
hint = "One key."
```

`start` runs setup keys before the card begins. `accept` lists alternative
solutions where more than one end state is genuinely correct.

### Keystroke cards (`kind = "keys"`)

Code navigation drives a language server or opens another file, so there is no
buffer state to compare — real `hx` has nothing to report and the emulator has
nothing to check. Those cards are graded on the keys pressed:

```toml
deck = "navigation"
kind = "keys"      # applies to every card in the file

[[card]]
id = "nav:jump-back"
prompt = "Go back to where you were before that jump"
keys = "<C-o>"
text = "..."
```

Because nothing else validates them, the bindings in
[decks/navigation.toml](decks/navigation.toml) were read out of the installed
Helix's own Goto infobox rather than from memory, and `C-o`/`C-i` were confirmed
by probing a real `hx`. [tests/test_keys_cards.py](tests/test_keys_cards.py)
pins each binding, checks the keys are inert in the emulator, and checks no card
asks for a key the trainer itself reserves.

`accept` matters more here: terminals send the same byte for `Ctrl-I` and `Tab`,
so the jump-forward card accepts both.

### Checking a deck

```
mise run validate      # every card's solution solves it
mise run verify-deck    # state cards re-probed in a real hx
```

## Coverage

The deck covers **all 87 distinct commands** taught by
[helix-trainer](https://github.com/bug-ops/helix-trainer) (read from its
`scenarios/en/**/*.toml`, 160 scenarios), across 114 cards, plus 47 commands it
does not teach — LSP navigation, the jumplist, `W`/`B`/`E`, `<A-;>`, `<A-d>`,
counts, and search.

Two places where we deliberately differ from it:

- **`q` / `Q` are the right way round.** helix-trainer's lesson hints say `q`
  records and `Q` replays; real Helix is the opposite. Verified by pressing each
  in a real `hx` — `q` reports "Register [@] empty", a failed *replay*.
- **No Vim-isms.** Its daily quests drill `0`, `$` and `yy`. `0`/`$` are
  non-default aliases and `yy` is not a Helix binding at all.

## Navigation needs a language server

The `gd`/`gr`/`gi`/`gy` cards teach keys that do nothing in real Helix without a
server for that filetype — and they fail *silently*, with no error. Check with:

```
hx --health python
```

If the language-server rows are all crosses, install one. `ruff` alone is not
enough: it lints and formats but has no goto-definition. For Python:

```
uv tool install jedi-language-server    # goto-definition, references
uv tool install ruff                    # lint + format
```

Helix merges the features of every server it finds, so both together is fine.
`gf` (open the file whose path is under the cursor) needs no server at all.

## Layout

| Path | |
|---|---|
| [decks/](decks) | cards: motions, selection, edits, navigation |
| [emu/](src/helix_spaced/emu) | Helix emulator: ranges, movement, key dispatch |
| [scoring.py](src/helix_spaced/scoring.py) | attempt to rating + penalty |
| [scheduler.py](src/helix_spaced/scheduler.py) | FSRS plus difficulty-weighted draw |
| [store.py](src/helix_spaced/store.py) | SQLite; every attempt logged for later retuning |
| [app.py](src/helix_spaced/app.py) | Textual TUI |
| [tools/calibrate.py](tools/calibrate.py) | ground truth from a real hx |
| [tools/verify_deck.py](tools/verify_deck.py) | re-probes every card in a real hx |

Review data lives in `~/.local/share/helix-spaced/reviews.db`. Set
`HELIX_SPACED_HOME` to move it.
