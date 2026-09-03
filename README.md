# helix-spaced

Spaced repetition trainer for Helix keybindings. Covers the ground `helix-trainer`
covers, but grades you: revealing the answer, wrong tries and slow answers all
cost you, and the cards you keep fumbling come back more often.

```
mise run install     # one time
mise run train       # start a session
mise run stats       # history + your hardest cards
```

## How grading works

Getting there is not the same as knowing it. An attempt is judged on four things
— **correctness, keystrokes, help taken, and time** — and each one costs.

Every attempt produces two numbers, and they do different jobs.

### 1. An FSRS rating — decides *when* the card comes back

| What you did | Rating |
|---|---|
| Wrong, or gave up | `Again` |
| Revealed the answer | `Hard` |
| Restarted, then got it | `Hard` |
| Solved, but with keystrokes to spare | `Hard` |
| Solved cleanly, but slow for you | `Hard` |
| Solved cleanly, normal speed | `Good` |
| Solved cleanly and fast, first try | `Easy` |

### 2. A penalty, 0..1 — decides *which due card you see first*

The penalty is kept as a per-card EWMA (α = 0.3) and is **separate from the
rating on purpose**. FSRS alone would ask an easy card as often as a hard one
once both fall due. The penalty biases the draw among currently-due cards toward
the ones you keep fumbling — so difficult material recurs within a session
without distorting the spacing model.

Weights, all in [scoring.py](src/helix_spaced/scoring.py):

| Cost | Weight |
|---|---|
| Answer revealed | 0.60 each |
| Keystroke over par | 0.15 each |
| Restart | 0.12 each |
| Slow | 0.20 per multiple past 2x, capped at 0.80 |
| Wrong / gave up | 1.00 flat |

They add up, capped at 1.0. Worked examples, generated from the code above:

| What you did | Rating | Penalty |
|---|---|---|
| solved it cleanly, normal speed | `Good` | 0.00 |
| solved it under 0.6x your best | `Easy` | 0.00 |
| one keystroke over par | `Hard` | 0.15 |
| three keystrokes over par | `Hard` | 0.45 |
| seven keystrokes over par | `Hard` | 1.00 |
| restarted once, then clean | `Hard` | 0.12 |
| revealed the answer | `Hard` | 0.60 |
| 2.5x your reference time | `Hard` | 0.10 |
| 4x your reference time | `Hard` | 0.40 |
| 9x your reference time | `Hard` | 0.80 |
| revealed AND 3 over par | `Hard` | 1.00 |
| gave up | `Again` | 1.00 |
| first ever sighting, 60s | `Good` | 0.00 |

### Keystrokes: par, not just arrival

Each card has a **par** — the length of its shortest accepted answer. Every key
above par costs 0.15 and caps the rating at `Hard`.

This exists because arriving at the right state is cheap. On a one-key card,
typing `b j k w` lands exactly where `w` does. That used to score `Easy` — and
because it was *fast*, wandering outranked a careful, slower answer. Precisely
backwards for a muscle-memory trainer.

- **`accept` blesses an alternate route**, whatever its length. Toggling a
  comment is `<C-c>` (one key) or `<space>c` (two); both are accepted, so
  neither is charged against the other.
- **A key the trainer reserves can never set par.** Otherwise a card would be
  penalised for an answer you are physically unable to press.
- **Beating par is free.** Find a shorter route than the deck's own answer and
  par clamps at zero — you are never punished for being better than the deck.
- **A restart is not a free undo.** Keys spent before `Ctrl-R` still count.

### Time: measured against your own best, not a stopwatch

The reference is the **25th percentile of your last 8 solved attempts** on that
card — what you have *proven you can do*. Past 2x that, the penalty ramps at
0.20 per additional multiple (so 2.5x costs 0.10 and 9x costs 0.80) rather than
a flat fee, because 9x should not cost what 2.1x costs.

The percentile matters. With the *median* as the reference, times of
2s/3s/20s/21s give a median of 11.5s, and a 22s attempt reads as merely 1.9x —
free. The percentile puts the bar at 3s, and the same attempt reads as 7.3x.
A median reference drifts up to meet however slow you have lately been; a low
percentile does not.

Two deliberate limits, worth stating plainly:

- **The first sighting of a card is never slow.** You cannot be slow at
  something you have never seen, so there is no reference yet.
- **A card you have never once done fast cannot be flagged as slow.** With no
  quick attempt on record there is no evidence you can go faster. Fixing that
  would need an absolute time budget, and the clock starts when the card appears
  — so it includes reading the prompt, and prompts differ a lot in length. An
  absolute bar would tax long prompts rather than slow recall.

### What you see after each card

The verdict answers *did I get it?* first, then what it cost:

```
  RIGHT              0.4s   1 key (par 1)
next in 9m  (on schedule)

  RIGHT, PENALISED   1.2s   4 keys (par 1)
3 keystrokes over par    penalty 0.45
next in 5m  (coming back sooner)

  WRONG              0.0s   0 keys (par 1)
not solved    penalty 1.00
Answer: w
next in 59s  (will come back soon)
```

Green for clean, yellow when it cost you, red when it did not count. Every cost
is listed, not just the first — reveal the answer *and* fumble a restart and you
see both. The FSRS rating is deliberately not the headline: reading `HARD` tells
you nothing about whether you were right.

### Mastering a card

The penalty is not a permanent mark — it is worked off. Every clean answer decays
it, and below 0.10 it is **cleared to exactly zero**. An exponential decay only
approaches zero, so without that floor a card could never actually be free of a
bad day.

A card is **mastered** when its penalty is cleared *and* the last three answers
were clean. Both halves matter: the penalty is long-run difficulty, the streak is
recent reliability.

From a total failure that is seven clean answers:

```
failed badly       penalty 1.000  streak 0
clean answer  1    penalty 0.700  streak 1
clean answer  2    penalty 0.490  streak 2
...
clean answer  6    penalty 0.118  streak 6
clean answer  7    penalty 0.000  streak 7   <- mastered
```

One slip afterwards is treated proportionately: a single keystroke over par is
too small to re-inflate the penalty, but it **resets the streak**, so mastery is
lost and takes three more clean answers to earn back. A real failure does both.

The live status line carries `mastered 12/139`, the verdict screen calls out the
moment a card tips over, and `mise run stats` reports the total. A practice redo
cannot grant it — an unscored run does not advance the streak.

### Retuning it later

Every attempt is logged in full — solved, elapsed, reveals, restarts,
keystrokes, keys over par, the resulting rating and penalty, and the exact keys
pressed. So these weights can be re-derived against real history instead of
guessed at. See [store.py](src/helix_spaced/store.py).

```
mise run stats     # totals plus your hardest cards by penalty EWMA
```

## Keys

Cards start the moment they appear, so while one is running every key belongs to
Helix. The controls use the **same letter throughout** — you just hold ctrl while
a card is live, and drop it once the card is graded.

| While a card runs | Once graded | Action |
|---|---|---|
| `Ctrl-T` | `t` | show the answer (penalty) |
| `Ctrl-R` | `r` | restart a live card, or redo one you just finished |
| `Ctrl-G` | `g` | give up, show the answer |
| `Ctrl-N` | `n` | next card (skipping a live card scores nothing) |
| `Ctrl-Q` | `q` | quit |

`Ctrl-C` is **not** reserved — it is Helix's toggle-comments and reaches the
buffer, so `Ctrl-Q` is the only way out.

Ctrl still works after grading, so muscle memory never misfires. `Enter` and
`Space` also move to the next card.

### Redoing a card

`r` on the grade screen replays the card you just did. **A redo is never
scored** — no review is logged, the penalty EWMA does not move, and the schedule
does not shift. Only a card the spacing model actually offers you counts.

That is deliberate on two grounds. An immediate re-test is not a review: FSRS
depends on the gap, so recording one would corrupt the interval. And a scored
redo would make a clean grade farmable — fumble it, retry until fast, keep the
good result. You still get the full verdict on a redo, so it works as practice;
it just does not touch your record.

Mid-card, the same key restarts the attempt, and that *does* count — the
keystrokes already spent are kept and the restart is charged.

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
```

`start` runs setup keys before the card begins. `accept` lists alternative
solutions where more than one end state is genuinely correct.

There is no `hint` field. `Ctrl-T` reveals `keys` verbatim — the literal
keystrokes to type — because a card is often the first time you meet a command.
Deriving it from `keys` means the revealed answer can never drift from the
solution the card is graded against.

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

## Things with no single key

Some everyday operations have no dedicated binding, which is where a Vim habit
misfires. `D` is not bound at all, and `gld` deletes only the last character.

| To do this | Press |
|---|---|
| Delete to end of line | `vgld` |
| Change to end of line | `vgl` then `c` |
| Delete to start of line | `vghd` |
| Close the file, stay in Helix | `:bc<ret>` |

`v` enters select mode so the following motion *extends* rather than replaces the
selection. An edit then hands the keyboard back: `d`, `c`, `y`, `p`, `~`, `>` and
`r` all leave select mode, while pure selection work (`;`, `x`, `_`, `<A-;>`) and
undo stay in it. That asymmetry is verified against a real `hx` and pinned in the
corpus — the emulator originally got it wrong in both directions.

## Buffers, files and the space menu

Closing a file without leaving Helix has no keybinding — it is
`:bc<ret>` (`:buffer-close`, aliases `bc` / `bclose`). The
[files deck](decks/files.toml) covers that plus `:w`, `:wq`, `:q`, `:o`, and the
space menu: `<space>b` buffer picker, `<space>f` file picker, `<space>/` global
search, `<space>y` / `<space>p` system clipboard, `<space>k` docs, `<space>r`
rename, `<space>a` code action, `<space>s` symbols, `<space>d` diagnostics,
`<space>c` comment, `<space>?` command palette.

Every one of those was read out of the installed Helix — the space-menu infobox
and each command's own help popup — rather than from memory. Only aliases Helix
itself reports are accepted as answers.

## Layout

| Path | |
|---|---|
| [decks/](decks) | cards: motions, selection, edits, navigation, files |
| [emu/](src/helix_spaced/emu) | Helix emulator: ranges, movement, key dispatch |
| [scoring.py](src/helix_spaced/scoring.py) | attempt to rating + penalty |
| [scheduler.py](src/helix_spaced/scheduler.py) | FSRS plus difficulty-weighted draw |
| [store.py](src/helix_spaced/store.py) | SQLite; every attempt logged for later retuning |
| [app.py](src/helix_spaced/app.py) | Textual TUI |
| [tools/calibrate.py](tools/calibrate.py) | ground truth from a real hx |
| [tools/verify_deck.py](tools/verify_deck.py) | re-probes every card in a real hx |

Review data lives in `~/.local/share/helix-spaced/reviews.db`. Set
`HELIX_SPACED_HOME` to move it.
