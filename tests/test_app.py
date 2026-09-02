import pytest
from textual.widgets import Static

from helix_spaced.app import (
    ACTIONS,
    ACTIVE,
    GRADED,
    TrainerApp,
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
