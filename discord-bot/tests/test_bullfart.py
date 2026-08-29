"""Tests for !bullfart: weekly bonus that must not consume the daily action."""

import datetime
import os
import sqlite3
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault(
    "config",
    MagicMock(
        OPENAI_API_KEY="test",
        FART_CHANNEL_ID=1,
        GUILD_ID=1,
        LEADER_ROLE_ID=1,
    ),
)

from cogs.fun import FunCog, get_est_date  # noqa: E402


USER_ID = 111
DISPLAY_NAME = "Frogimago"
YESTERDAY = (get_est_date() - datetime.timedelta(days=1)).isoformat()


@pytest.fixture()
def fart_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cog = FunCog(MagicMock())
    yield cog
    if os.path.exists("fart_scores.db"):
        os.remove("fart_scores.db")


def _seed_player(last_type="elite", score=100, last_updated=YESTERDAY):
    conn = sqlite3.connect("fart_scores.db")
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS fart_scores
                   (user_id INTEGER PRIMARY KEY,
                    user_display_name TEXT,
                    date_last_updated TEXT,
                    score INTEGER)"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS fart_history
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    fart_type TEXT NOT NULL,
                    roll INTEGER NOT NULL,
                    timestamp TEXT NOT NULL)"""
    )
    cur.execute(
        "INSERT INTO fart_scores VALUES (?, ?, ?, ?)",
        (USER_ID, DISPLAY_NAME, last_updated, score),
    )
    cur.execute(
        "INSERT INTO fart_history (user_id, username, fart_type, roll, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (USER_ID, DISPLAY_NAME, last_type, 70, last_updated),
    )
    conn.commit()
    conn.close()


def _score_row():
    conn = sqlite3.connect("fart_scores.db")
    row = conn.execute(
        "SELECT score, date_last_updated FROM fart_scores WHERE user_id=?",
        (USER_ID,),
    ).fetchone()
    conn.close()
    return row


class TestBullfartDoesNotConsumeDaily:
    def test_awards_elite_bonus_without_touching_daily_timestamp(self, fart_db):
        _seed_player(last_type="elite", score=100, last_updated=YESTERDAY)

        result = fart_db.award_bullfart_bonus(USER_ID, DISPLAY_NAME)

        assert result == (25, "Elite Fart")
        score, last_updated = _score_row()
        assert score == 125
        assert last_updated == YESTERDAY

    def test_usable_after_daily_fart_without_resetting_daily(self, fart_db):
        today = get_est_date().isoformat()
        _seed_player(last_type="ordinary", score=40, last_updated=today)

        result = fart_db.award_bullfart_bonus(USER_ID, DISPLAY_NAME)

        assert result == (10, "Ordinary Fart")
        score, last_updated = _score_row()
        assert score == 50
        assert last_updated == today

    def test_save_fart_score_would_consume_daily_this_is_the_bug(self, fart_db):
        """Regression: save_fart_score stamps date_last_updated and blocks !fart."""
        _seed_player(last_type="elite", score=100, last_updated=YESTERDAY)
        now = datetime.datetime.now()

        fart_db.save_fart_score(now, USER_ID, DISPLAY_NAME, 25)

        score, last_updated = _score_row()
        assert score == 125
        assert last_updated == now.isoformat()
        assert last_updated != YESTERDAY

    def test_no_history_returns_none_and_does_not_create_score(self, fart_db):
        assert fart_db.award_bullfart_bonus(USER_ID, DISPLAY_NAME) is None

    def test_curio_shart_bonus(self, fart_db):
        _seed_player(last_type="curio_shart", score=10)
        assert fart_db.award_bullfart_bonus(USER_ID, DISPLAY_NAME) == (50, "Curio Shart")
        assert _score_row()[0] == 60


class TestBullfartWeeklyCooldown:
    def test_available_when_never_used(self, fart_db):
        assert fart_db.weekly_command_days_remaining(USER_ID, "bullfart") == 0

    def test_on_cooldown_after_use(self, fart_db):
        fart_db.record_command_used(USER_ID, "bullfart")
        days = fart_db.weekly_command_days_remaining(USER_ID, "bullfart")
        assert days >= 1
        assert days <= 7

    def test_available_after_a_week(self, fart_db):
        week_ago = datetime.datetime.now() - datetime.timedelta(weeks=1)
        fart_db.record_command_used(USER_ID, "bullfart", used_at=week_ago)
        assert fart_db.weekly_command_days_remaining(USER_ID, "bullfart") == 0

    def test_failed_award_does_not_start_weekly_cooldown(self, fart_db):
        assert fart_db.award_bullfart_bonus(USER_ID, DISPLAY_NAME) is None
        assert fart_db.weekly_command_days_remaining(USER_ID, "bullfart") == 0
