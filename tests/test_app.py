import re
from datetime import UTC

import pytest
from textual.widgets import Static

from helix_spaced.app import (
    ACTIONS,
    ACTIVE,
    GRADED,
    QUIT,
    TrainerApp,
    human_interval,
    render_buffer,
    render_help,
    resolve,
)
from helix_spaced.deck import Card, load_dir
from helix_spaced.emu.engine import Engine
from helix_spaced.keymap import from_textual
from helix_spaced.scheduler import Trainer
from helix_spaced.store import Store


def test_keymap_translates_plain_and_modified_keys():
    assert from_textual("w", "w") == "w"
    assert from_textual("escape", None) == "<esc>"
    assert from_textual("space", " ") == " "
    assert from_textual("alt+semicolon", None) == "<A-;>"


def test_reserved_control_keys_never_reach_the_buffer():
    for key in ("ctrl+q", "ctrl+n", "ctrl+t", "ctrl+r", "ctrl+g"):
        assert from_textual(key, None) is None


def test_control_keys_helix_uses_still_reach_the_buffer():
    assert from_textual("ctrl+w", None) == "<C-w>"
    assert from_textual("ctrl+a", None) == "<C-a>"


# -- the key rule ---------------------------------------------------------


def test_each_action_uses_the_same_letter_in_both_phases():
    """The rule: hold ctrl while a card runs, drop it once graded."""
    for letter, action in ACTIONS.items():
        assert resolve(f"ctrl+{letter}", ACTIVE) == action
        assert resolve(f"ctrl+{letter}", GRADED) == action
        assert resolve(letter, GRADED) == action


def test_bare_letters_belong_to_the_buffer_while_a_card_runs():
    for letter in ACTIONS:
        assert resolve(letter, ACTIVE) is None


def test_help_shows_the_same_letters_with_and_without_ctrl():
    active = render_help(ACTIVE).plain
    graded = render_help(GRADED).plain
    assert "^n" in active and "^q" in active
    assert " n " in graded and "^n" not in graded


# -- rendering ------------------------------------------------------------


def test_render_marks_exactly_the_selection():
    e = Engine.run("the quick\n", "w")
    assert e.spans == [(0, 4)]
    out = render_buffer(e)
    reversed_text = "".join(out.plain[s.start:s.end]
                            for s in out.spans if "reverse" in str(s.style))
    assert reversed_text == "the "


def test_render_shows_a_selected_newline():
    e = Engine.run("ab\ncd\n", "x")
    out = render_buffer(e)
    assert "¬" in out.plain


# -- app ------------------------------------------------------------------


@pytest.fixture
def trainer(tmp_path):
    card = Card(id="t:w", deck="t", prompt="next word",
                text="the quick brown fox\n", keys="w")
    store = Store(tmp_path / "a.db")
    yield Trainer([card], store)
    store.close()


@pytest.mark.asyncio
async def test_a_card_starts_immediately(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test():
        assert app.phase == ACTIVE
        assert app.session.started is not None


@pytest.mark.asyncio
async def test_typing_the_answer_grades_the_card(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert app.session.solved
        assert app.phase == GRADED
        assert trainer.store.card("t:w")["reviews"] == 1


@pytest.mark.asyncio
async def test_letters_reach_the_buffer_not_the_trainer(trainer):
    """`n`, `t`, `g` are Helix keys while a card runs, not controls."""
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("t")
        assert app.session.typed == "t"
        assert app.session.hints == 0


@pytest.mark.asyncio
async def test_the_answer_key_shows_the_keys_to_type(trainer):
    """It reveals the literal solution, not a nudge -- so it must cost you."""
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")
        assert app.session.hints == 1
        assert app.session.typed == ""
        shown = app.query_one("#hint", Static).render().plain
        assert shown == "Answer: w"
        await pilot.press("w")
        assert app.session.attempt().hints == 1


@pytest.mark.asyncio
async def test_giving_up_records_a_failure(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+g")
        assert app.phase == GRADED
        assert trainer.store.card("t:w")["lapses"] == 1


@pytest.mark.asyncio
async def test_restart_clears_typed_keys_and_keeps_the_clock(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        started = app.session.started
        await pilot.press("b")
        await pilot.press("ctrl+r")
        assert app.session.typed == "" and app.session.wrong == 1
        assert app.phase == ACTIVE and app.session.started == started


@pytest.mark.asyncio
async def test_skip_during_a_card_does_not_score_it(trainer):
    app = TrainerApp(trainer, limit=2)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+n")
        assert trainer.store.card("t:w")["reviews"] == 0


@pytest.mark.asyncio
async def test_a_bare_letter_advances_once_graded(tmp_path):
    store = Store(tmp_path / "c.db")
    cards = [Card(id=f"t:{i}", deck="t", prompt="next word",
                  text="the quick brown fox\n", keys="w") for i in range(3)]
    app = TrainerApp(Trainer(cards, store), limit=3)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert app.phase == GRADED
        first = app.session.card.id
        await pilot.press("n")
        assert app.phase == ACTIVE and app.session.card.id != first
    store.close()


@pytest.mark.asyncio
async def test_ctrl_also_advances_once_graded(tmp_path):
    """Ctrl keeps working after grading, so muscle memory never misfires."""
    store = Store(tmp_path / "d.db")
    cards = [Card(id=f"t:{i}", deck="t", prompt="next word",
                  text="the quick brown fox\n", keys="w") for i in range(3)]
    app = TrainerApp(Trainer(cards, store), limit=3)
    async with app.run_test() as pilot:
        await pilot.press("w")
        first = app.session.card.id
        await pilot.press("ctrl+n")
        assert app.phase == ACTIVE and app.session.card.id != first
    store.close()


@pytest.mark.asyncio
async def test_help_tracks_the_phase(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        assert app.query_one("#help", Static).render().plain == render_help(ACTIVE).plain
        await pilot.press("w")
        assert app.query_one("#help", Static).render().plain == render_help(GRADED).plain


@pytest.mark.asyncio
async def test_real_deck_loads_into_the_app(tmp_path):
    store = Store(tmp_path / "b.db")
    app = TrainerApp(Trainer(load_dir(), store), limit=2)
    async with app.run_test():
        assert app.session is not None
        assert app.session.card.prompt
    store.close()


# -- the verdict ----------------------------------------------------------


def verdict(app):
    return app.query_one("#status", Static).render().plain


@pytest.mark.asyncio
async def test_a_clean_answer_says_right(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("w")
        text = verdict(app)
        assert "RIGHT" in text
        assert "PENALISED" not in text
        assert "penalty" not in text


@pytest.mark.asyncio
async def test_a_penalised_answer_says_so_and_why(trainer):
    """Reading `HARD` never told you whether you were even right."""
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        for k in ("b", "j", "k", "w"):
            await pilot.press(k)
        text = verdict(app)
        assert "RIGHT, PENALISED" in text
        assert "3 keystrokes over par" in text
        assert "penalty 0.45" in text


@pytest.mark.asyncio
async def test_a_failed_card_says_wrong_and_shows_the_answer(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+g")
        text = verdict(app)
        assert "WRONG" in text
        assert "Answer: w" in text


@pytest.mark.asyncio
async def test_the_verdict_reports_keys_against_par(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert "1 key (par 1)" in verdict(app)


@pytest.mark.asyncio
async def test_the_verdict_says_when_the_card_returns(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert "next in" in verdict(app)


@pytest.mark.asyncio
async def test_every_cost_is_listed_not_just_the_first(trainer):
    app = TrainerApp(trainer, limit=1)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")
        await pilot.press("b")
        await pilot.press("ctrl+r")
        await pilot.press("w")
        text = verdict(app)
        assert "answer revealed" in text
        assert "restart" in text


def test_human_interval_reads_naturally():
    from datetime import datetime, timedelta
    now = datetime.now(UTC)
    assert human_interval((now + timedelta(seconds=30)).isoformat()).endswith("s")
    assert human_interval((now + timedelta(minutes=10)).isoformat()) == "10m"
    assert human_interval((now + timedelta(hours=5)).isoformat()) == "5h"
    assert human_interval((now + timedelta(days=3)).isoformat()) == "3d"
    assert human_interval(None) == "soon"


# -- redo -----------------------------------------------------------------


async def solve(pilot, app, keys):
    for k in keys:
        await pilot.press(k)
    await pilot.pause()


@pytest.mark.asyncio
async def test_r_after_grading_runs_the_card_again(trainer):
    app = TrainerApp(trainer, limit=5)
    async with app.run_test() as pilot:
        await solve(pilot, app, ["w"])
        assert app.phase == GRADED
        await pilot.press("r")
        assert app.phase == ACTIVE
        assert app.session.card.id == "t:w"
        assert app.session.typed == ""


@pytest.mark.asyncio
async def test_a_redo_is_not_scored(trainer):
    """Re-running a card you just did is practice. Letting it count would both
    corrupt the spacing and make a clean grade farmable."""
    app = TrainerApp(trainer, limit=5)
    async with app.run_test() as pilot:
        await solve(pilot, app, ["b", "b", "w"])       # sloppy: 2 over par
        before = dict(trainer.store.card("t:w"))
        reviews = trainer.store.stats()["reviews"]

        await pilot.press("r")
        await solve(pilot, app, ["w"])                  # perfect this time

        after = dict(trainer.store.card("t:w"))
        assert trainer.store.stats()["reviews"] == reviews, "logged a second review"
        assert after["penalty_ewma"] == before["penalty_ewma"], "penalty moved"
        assert after["due"] == before["due"], "schedule moved"
        assert after["reviews"] == before["reviews"]


@pytest.mark.asyncio
async def test_a_redo_does_not_count_toward_the_session_total(trainer):
    app = TrainerApp(trainer, limit=5)
    async with app.run_test() as pilot:
        await solve(pilot, app, ["w"])
        assert app.done == 1
        await pilot.press("r")
        await solve(pilot, app, ["w"])
        assert app.done == 1


@pytest.mark.asyncio
async def test_a_redo_still_gives_feedback(trainer):
    """Unscored, but you still see whether you got it and what it would cost."""
    app = TrainerApp(trainer, limit=5)
    async with app.run_test() as pilot:
        await solve(pilot, app, ["w"])
        await pilot.press("r")
        await solve(pilot, app, ["b", "b", "w"])
        text = verdict(app)
        assert "RIGHT, PENALISED" in text
        assert "2 keystrokes over par" in text
        assert "not scored" in text


@pytest.mark.asyncio
async def test_a_redo_can_be_repeated(trainer):
    app = TrainerApp(trainer, limit=5)
    async with app.run_test() as pilot:
        await solve(pilot, app, ["w"])
        for _ in range(3):
            await pilot.press("r")
            await solve(pilot, app, ["w"])
        assert trainer.store.stats()["reviews"] == 1


@pytest.mark.asyncio
async def test_moving_on_after_a_redo_scores_again(tmp_path):
    """Practice is per-card: the next card the schedule offers still counts."""
    store = Store(tmp_path / "redo.db")
    cards = [Card(id=f"t:{i}", deck="t", prompt="next word",
                  text="the quick brown fox\n", keys="w") for i in range(3)]
    app = TrainerApp(Trainer(cards, store), limit=5)
    async with app.run_test() as pilot:
        await solve(pilot, app, ["w"])
        await pilot.press("r")
        await solve(pilot, app, ["w"])
        assert app.practice
        assert store.stats()["reviews"] == 1

        await pilot.press("n")
        assert not app.practice
        await solve(pilot, app, ["w"])
        assert store.stats()["reviews"] == 2, "a scheduled card must score again"
    store.close()


def test_the_graded_help_offers_redo():
    assert "redo" in render_help(GRADED).plain


@pytest.mark.asyncio
async def test_ctrl_c_reaches_the_buffer_and_does_not_quit(tmp_path):
    """Ctrl-C is Helix's toggle-comments. Ctrl-Q is the only way out."""
    store = Store(tmp_path / "cc.db")
    card = Card(id="t:c", deck="t", prompt="comment it out",
                text="x = 1\ny = 2\n", keys="<C-c>", accept=["<space>c"])
    app = TrainerApp(Trainer([card], store), limit=1)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        assert app.is_running
        assert app.session.solved
        assert app.session.engine.text == "# x = 1\ny = 2\n"
    store.close()


def test_ctrl_q_is_the_only_quit():
    assert resolve("ctrl+q", ACTIVE) == QUIT
    assert resolve("ctrl+q", GRADED) == QUIT
    assert resolve("ctrl+c", ACTIVE) is None, "ctrl+c must fall through to the buffer"
    assert resolve("ctrl+c", GRADED) is None


def clean_attempt():
    from helix_spaced.scoring import Attempt
    return Attempt(solved=True, elapsed_ms=1000, hints=0, wrong_attempts=0,
                   keystrokes=1, extra_keys=0)


@pytest.mark.asyncio
async def test_mastering_a_card_is_called_out(trainer):
    """The moment a card tips into mastered should be visible, not silent."""
    trainer.review("t:w", clean_attempt())
    trainer.review("t:w", clean_attempt())
    assert not trainer.mastered("t:w")
    app = TrainerApp(trainer, limit=9)
    async with app.run_test() as pilot:
        await pilot.press("w")
        text = verdict(app)
        assert trainer.mastered("t:w")
        assert "MASTERED" in text
        assert "this card is done" in text


@pytest.mark.asyncio
async def test_an_already_mastered_card_is_not_re_announced(trainer):
    for _ in range(3):
        trainer.review("t:w", clean_attempt())
    assert trainer.mastered("t:w")
    app = TrainerApp(trainer, limit=9)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert "MASTERED" not in verdict(app)
        assert "RIGHT" in verdict(app)


@pytest.mark.asyncio
async def test_the_status_line_shows_mastery_progress(trainer):
    app = TrainerApp(trainer, limit=9)
    async with app.run_test():
        assert "mastered 0/1" in app.query_one("#status", Static).render().plain


@pytest.mark.asyncio
async def test_a_practice_redo_cannot_grant_mastery(trainer):
    """Redoing is unscored, so it must not advance the streak either."""
    trainer.review("t:w", clean_attempt())
    trainer.review("t:w", clean_attempt())
    app = TrainerApp(trainer, limit=9)
    async with app.run_test() as pilot:
        await pilot.press("w")            # third clean -> mastered
        assert trainer.mastered("t:w")
        streak = trainer.store.card("t:w")["clean_streak"]
        await pilot.press("r")
        await pilot.press("w")
        assert trainer.store.card("t:w")["clean_streak"] == streak, "redo moved the streak"
        assert "MASTERED" not in verdict(app), "a redo must not re-announce it"


# -- Alt keys -------------------------------------------------------------


@pytest.mark.parametrize(("key", "character", "expected"), [
    # Textual names a shifted Alt key either way, depending on the terminal
    ("alt+C", "C", "<A-C>"),
    ("alt+shift+c", None, "<A-C>"),
    ("alt+shift+C", None, "<A-C>"),
    ("alt+J", "J", "<A-J>"),
    ("alt+shift+j", None, "<A-J>"),
    # punctuation arrives spelled out once it carries a modifier
    ("alt+grave_accent", None, "<A-`>"),
    ("alt+semicolon", None, "<A-;>"),
    ("alt+period", None, "<A-.>"),
    ("alt+left_square_bracket", None, "<A-[>"),
    # meta is alt on some terminals
    ("meta+d", None, "<A-d>"),
])
def test_alt_keys_survive_every_name_a_terminal_uses(key, character, expected):
    assert from_textual(key, character) == expected


def test_every_alt_key_in_the_deck_is_reachable():
    """A name the keymap does not recognise is swallowed, which reads as a dead
    key -- `<A-C>` and `<A-`>` were both unreachable this way."""
    for card in load_dir():
        for answer in card.answers:
            for token in re.findall(r"<A-(.)>", answer):
                shapes = [(f"alt+{token}", token)]
                if token.isalpha() and token.isupper():
                    shapes.append((f"alt+shift+{token.lower()}", None))
                for name, ch in shapes:
                    assert from_textual(name, ch) == f"<A-{token}>", \
                        f"{card.id}: {name} does not reach {token}"
