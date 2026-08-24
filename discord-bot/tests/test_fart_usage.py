"""Usage tracker driven by Action/Item classes."""

import sqlite3
from datetime import datetime, timedelta

from fart_game.abilities import get_ability
from fart_game.usage import UsageTracker


def test_daily_item_round_trip(tmp_path):
    db = str(tmp_path / "fart_scores.db")
    tracker = UsageTracker(db)
    allowed, msg = tracker.check("blue_shell", 7)
    assert allowed and msg is None
    tracker.mark("blue_shell", 7)
    allowed, msg = tracker.check("blue_shell", 7)
    assert not allowed
    assert "once per day" in msg


def test_weekly_mushroom_uses_lucky_charm_table(tmp_path):
    db = str(tmp_path / "fart_scores.db")
    tracker = UsageTracker(db)
    tracker.mark("mushroom", 3)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT command_name FROM lucky_charm_usage WHERE user_id=3"
    ).fetchone()
    conn.close()
    assert row[0] == "mushroom"
    allowed, msg = tracker.check("mushroom", 3)
    assert not allowed
    assert "once per week" in msg


def test_season_and_reign_and_guild(tmp_path):
    db = str(tmp_path / "fart_scores.db")
    tracker = UsageTracker(db)
    tracker.mark("evil_star", 1)
    assert tracker.check("evil_star", 1)[0] is False
    assert tracker.check("evil_star", 2)[0] is True

    tracker.mark("fart_gift", 10, peer_id=20)
    assert tracker.check("fart_gift", 10, peer_id=20)[0] is False
    assert tracker.check("fart_gift", 10, peer_id=21)[0] is True

    tracker.mark("taxes", 5, display_name="Lord")
    assert tracker.check("wealth", 5)[0] is False
    assert tracker.check("taxes", 9)[0] is True

    tracker.mark("giga_fart_cannon", 1)
    assert tracker.check("giga_fart_cannon", 99)[0] is False
    assert get_ability("giga_fart_cannon").usage_scope == "guild"


def test_weekly_expires(tmp_path):
    db = str(tmp_path / "fart_scores.db")
    tracker = UsageTracker(db)
    tracker.mark("bullfart", 1)
    conn = sqlite3.connect(db)
    old = (datetime.now() - timedelta(weeks=2)).isoformat()
    conn.execute(
        "UPDATE command_usage SET last_used=? WHERE user_id=1 AND command_name='bullfart'",
        (old,),
    )
    conn.commit()
    conn.close()
    assert tracker.check("bullfart", 1)[0] is True
