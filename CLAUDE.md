# helix-spaced

Spaced repetition trainer for Helix keybindings, containing a Helix emulator.

## Commit cadence

**Commit and push at the end of every fix or feature.** Do not batch several
changes into one commit, and do not wait to be asked — as soon as a unit of work
is done and `mise run test` is green, propose the commit.

The approval flow is unchanged: follow `toolkit:git-workflow`, which means
staging named files, writing the message to a file, showing it, and getting
approval through `AskUserQuestion` before committing.

## The correctness story is the load-bearing part

The trainer emulates Helix rather than driving it. That was a deliberate choice
with a known risk — drift — so nothing in `src/helix_spaced/emu/` is trusted on
its own. **Two separate things need proving, and each has its own fixture.**

| Claim | Proof | Regenerate |
|---|---|---|
| the emulator matches Helix | `tests/fixtures/helix_truth.json` (1544 probed cases) | `mise run recalibrate` |
| each card does what it claims | `tests/fixtures/deck_truth.json` (every state card) | `mise run verify-deck` |

**`mise run validate` alone is circular** — it only checks a card's solution
against the emulator's own idea of that solution. It has passed cards that were
wrong. Always run `verify-deck` after touching a deck, and `recalibrate` after
touching the engine.

Both use `tools/calibrate.py`, which drives a real `hx` in a pty and recovers the
selection by overwriting it with a sentinel char — length-preserving, so there is
no diff ambiguity. A plain delete-and-diff is *not* good enough: deleting
`" quick"` and `"quick "` give identical text.

### Two traps in the harness itself

- **The sentinel cannot mark a zero-width selection.** This once made `C` look
  correct when it was wrong: Helix's second cursor sat at end-of-file with zero
  width and was invisible. A surprising "pass" deserves a second look.
- **The harness sends `:wq` to save**, so scraping Helix's own help popups picks
  up *that* command's help. Use a no-save variant when reading infoboxes.

### Don't test against invented inputs

Asserting `from_textual("alt+shift+c", ...)` only proves the translation handles
a name *I made up*. `tests/test_keymap_parser.py` feeds real escape sequences
through Textual's own parser instead. Doing it properly found a second bug that
the invented-name tests could never have caught.

Same principle throughout: test against the real component, not your model of it.

## The curriculum is gated

Cards live in ordered sections, one TOML file each (`decks/NN-name.toml`, with
`section`/`title`/`order` in the header). A section must be fully mastered before
the next is introduced.

**Gating applies to what is introduced, not to what is reviewed.** Earlier
sections stay in rotation once due; locked sections are never drawn. Getting this
backwards would mean a mastered section is never seen again and rots.

`sections_mastered()` and `current_section()` can disagree — a lapse in an early
section makes it current again while later ones stay mastered. Report both.

**Card ids are stable and independent of their file.** The review log keys on
them, so re-filing a card into another section must never change its id.

## Deck conventions

Two card kinds:

- **`state`** (default) — graded on the resulting buffer and selection, so any
  route counts. Every one is verified against real `hx`.
- **`keys`** (`kind = "keys"` at file level) — graded on the keystrokes. Only for
  commands with no buffer state to compare: LSP navigation, pickers, scrolling.
  Nothing that edits text belongs here. A comment toggle was misfiled this way
  and the buffer silently never changed.

Card `par` is the shortest **typeable** answer. `accept` blesses an alternate
route at any length. A key the trainer reserves must never set par — that
penalised a correct answer once.

## Keys the trainer reserves

`^n ^t ^r ^g ^q` only. **`Ctrl-C` is deliberately not reserved** — it is Helix's
toggle-comments — so `Ctrl-Q` is the only quit. Never reserve a key a card needs.

`<A-;>` and `` <A-`> `` require a terminal speaking the kitty keyboard protocol;
on the legacy encoding Textual drops the Alt before we see it. `mise run keys`
shows what a terminal actually sends.

## Known deviations

`KNOWN_DEVIATIONS` in `tests/test_conformance.py`, all one family: a file of one
line or less with the cursor at end-of-buffer. No card uses such a buffer. Record
new ones there with a reason rather than contorting the EOF handling.
