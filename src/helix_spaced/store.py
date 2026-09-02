"""SQLite persistence: card scheduling state plus an append-only review log.

Every attempt is logged in full so the scoring weights in scoring.py can be
retuned later and replayed against real history.
"""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id           TEXT PRIMARY KEY,
    deck         TEXT NOT NULL,
    fsrs         TEXT,
    penalty_ewma REAL,
    reviews      INTEGER NOT NULL DEFAULT 0,
    lapses       INTEGER NOT NULL DEFAULT 0,
    due          TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     TEXT NOT NULL,
    at          TEXT NOT NULL,
    solved      INTEGER NOT NULL,
    elapsed_ms  INTEGER NOT NULL,
    hints       INTEGER NOT NULL,
    wrong       INTEGER NOT NULL,
    keystrokes  INTEGER NOT NULL,
    rating      INTEGER NOT NULL,
    penalty     REAL NOT NULL,
    keys        TEXT,
    extra       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS reviews_card ON reviews(card_id, at);
"""


def default_path() -> Path:
    root = os.environ.get("HELIX_SPACED_HOME")
    if root:
        return Path(root) / "reviews.db"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "helix-spaced" / "reviews.db"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """The review log is append-only, so new fields are added in place."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(reviews)")}
        if "extra" not in cols:
            self.db.execute("ALTER TABLE reviews ADD COLUMN extra INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self.db.close()

    def card(self, card_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()

    def all_cards(self) -> dict[str, sqlite3.Row]:
        return {r["id"]: r for r in self.db.execute("SELECT * FROM cards")}

    def ensure(self, card_id: str, deck: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO cards (id, deck) VALUES (?, ?)", (card_id, deck))
        self.db.commit()

    def save_card(self, card_id: str, deck: str, fsrs: dict, penalty_ewma: float,
                  lapsed: bool, due: datetime) -> None:
        self.db.execute(
            """INSERT INTO cards (id, deck, fsrs, penalty_ewma, reviews, lapses, due)
               VALUES (?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 fsrs = excluded.fsrs,
                 penalty_ewma = excluded.penalty_ewma,
                 reviews = cards.reviews + 1,
                 lapses = cards.lapses + excluded.lapses,
                 due = excluded.due""",
            (card_id, deck, json.dumps(fsrs), penalty_ewma, int(lapsed), due.isoformat()))
        self.db.commit()

    def log(self, card_id: str, attempt, rating: int, penalty: float, keys: str) -> None:
        self.db.execute(
            """INSERT INTO reviews
               (card_id, at, solved, elapsed_ms, hints, wrong, keystrokes,
                rating, penalty, keys, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, datetime.now(UTC).isoformat(), int(attempt.solved),
             attempt.elapsed_ms, attempt.hints, attempt.wrong_attempts,
             attempt.keystrokes, int(rating), penalty, keys, attempt.extra_keys))
        self.db.commit()

    def reference_time(self, card_id: str, window: int = 8,
                       percentile: float = 0.25) -> int | None:
        """The time to beat on this card: a low percentile of recent solved
        attempts, so the bar tracks demonstrated ability rather than drifting up
        to match however slow you have been lately."""
        rows = self.db.execute(
            "SELECT elapsed_ms FROM reviews WHERE card_id = ? AND solved = 1 "
            "ORDER BY at DESC LIMIT ?", (card_id, window)).fetchall()
        if not rows:
            return None
        vals = sorted(r["elapsed_ms"] for r in rows)
        idx = max(0, min(len(vals) - 1, round(percentile * (len(vals) - 1))))
        return vals[idx]

    def stats(self) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) n, SUM(solved) ok, AVG(elapsed_ms) avg_ms FROM reviews").fetchone()
        return {"reviews": row["n"] or 0, "solved": row["ok"] or 0,
                "avg_ms": int(row["avg_ms"] or 0)}

    def hardest(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM cards WHERE penalty_ewma IS NOT NULL "
            "ORDER BY penalty_ewma DESC LIMIT ?", (limit,)).fetchall()
