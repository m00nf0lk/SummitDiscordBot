"""Usage tracking for fart-game Action and Item classes."""

from __future__ import annotations

import datetime
import sqlite3
from zoneinfo import ZoneInfo

from fart_game.abilities import (
    COOLDOWN_DAILY,
    COOLDOWN_NONE,
    COOLDOWN_REIGN,
    COOLDOWN_SEASON,
    COOLDOWN_WEEKLY,
    FartAbility,
    get_ability,
)

EST = ZoneInfo("America/New_York")

DEFAULT_DB_PATH = "fart_scores.db"


def get_est_now():
    return datetime.datetime.now(EST)


def get_est_date():
    return get_est_now().date()


def get_est_midnight():
    now = get_est_now()
    tomorrow = now + datetime.timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


def safe_parse_datetime(date_string):
    if not date_string:
        return None
    try:
        return datetime.datetime.fromisoformat(date_string)
    except ValueError:
        try:
            import re

            pattern = (
                r"^(\d{4})-(\d{1,2})-(\d{1,2})T(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$"
            )
            match = re.match(pattern, date_string)
            if not match:
                return None
            year, month, day, hour, minute, second, microsecond = match.groups()
            fixed = (
                f"{year}-{month.zfill(2)}-{day.zfill(2)}T"
                f"{hour.zfill(2)}:{minute}:{second}"
            )
            if microsecond:
                fixed += f".{microsecond}"
            return datetime.datetime.fromisoformat(fixed)
        except Exception:
            return None


def parse_to_est_date(date_string):
    parsed = safe_parse_datetime(date_string)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EST)
    return parsed.astimezone(EST).date()


def _pretty(ability_name: str) -> str:
    return ability_name.replace("_", " ").title()


class UsageTracker:
    """Check and record ability usage from class metadata."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def ensure_tables(self, cur: sqlite3.Cursor, ability: type[FartAbility]):
        table = ability.inferred_usage_table()
        if not table:
            return
        if table == "command_usage" or table == "lucky_charm_usage":
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {table}
                    (user_id INTEGER,
                     command_name TEXT,
                     last_used TEXT,
                     PRIMARY KEY (user_id, command_name))"""
            )
        elif table == "fart_leader_only_once":
            cur.execute(
                """CREATE TABLE IF NOT EXISTS fart_leader_only_once
                   (user_id INTEGER PRIMARY KEY,
                    user_display_name TEXT)"""
            )
        elif table == "evil_star_usage":
            cur.execute(
                """CREATE TABLE IF NOT EXISTS evil_star_usage (
                    user_id INTEGER PRIMARY KEY,
                    used_at TEXT NOT NULL
                )"""
            )
        elif table == "fart_gift_usage":
            cur.execute(
                """CREATE TABLE IF NOT EXISTS fart_gift_usage (
                    gifter_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    gifted_at TEXT NOT NULL,
                    PRIMARY KEY (gifter_id, recipient_id)
                )"""
            )
        elif table == "fart_donation_usage":
            cur.execute(
                """CREATE TABLE IF NOT EXISTS fart_donation_usage (
                    donor_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    donated_at TEXT NOT NULL,
                    PRIMARY KEY (donor_id, recipient_id)
                )"""
            )
        elif ability.usage_scope == "guild":
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_used TEXT NOT NULL
                )"""
            )
        elif ability.cooldown == COOLDOWN_SEASON and ability.usage_scope == "user":
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {table} (
                    user_id INTEGER PRIMARY KEY,
                    used_at TEXT NOT NULL
                )"""
            )
        elif ability.cooldown == COOLDOWN_SEASON and ability.usage_scope == "pair":
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {table} (
                    user_id INTEGER NOT NULL,
                    peer_id INTEGER NOT NULL,
                    used_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, peer_id)
                )"""
            )
        else:
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {table}
                    (user_id INTEGER,
                     command_name TEXT,
                     last_used TEXT,
                     PRIMARY KEY (user_id, command_name))"""
            )

    def _ability(self, ability: type[FartAbility] | str) -> type[FartAbility]:
        if isinstance(ability, str):
            cls = get_ability(ability)
            if cls is None:
                raise KeyError(f"Unknown fart ability: {ability}")
            return cls
        return ability

    def check(
        self,
        ability: type[FartAbility] | str,
        user_id: int,
        *,
        peer_id: int | None = None,
    ) -> tuple[bool, str | None]:
        """Return (allowed, error_message)."""
        cls = self._ability(ability)
        if cls.cooldown == COOLDOWN_NONE and not cls.inferred_usage_table():
            return True, None

        conn = self._connect()
        cur = conn.cursor()
        try:
            self.ensure_tables(cur, cls)
            table = cls.inferred_usage_table()
            if not table:
                return True, None

            if cls.usage_scope == "guild":
                return self._check_guild(cur, cls, table)
            if cls.usage_scope == "pair":
                if peer_id is None:
                    return False, "A target player is required."
                return self._check_pair(cur, cls, table, user_id, peer_id)
            if cls.cooldown == COOLDOWN_REIGN or cls.usage_scope == "shared_reign":
                return self._check_reign(cur, table, user_id)
            if cls.cooldown == COOLDOWN_SEASON:
                return self._check_season_user(cur, cls, table, user_id)
            if table in ("command_usage", "lucky_charm_usage") or cls.cooldown in (
                COOLDOWN_DAILY,
                COOLDOWN_WEEKLY,
            ):
                return self._check_period(cur, cls, table, user_id)
            return True, None
        finally:
            conn.close()

    def mark(
        self,
        ability: type[FartAbility] | str,
        user_id: int,
        *,
        peer_id: int | None = None,
        display_name: str | None = None,
    ) -> None:
        cls = self._ability(ability)
        table = cls.inferred_usage_table()
        if not table:
            return

        conn = self._connect()
        cur = conn.cursor()
        try:
            self.ensure_tables(cur, cls)
            now = datetime.datetime.now().isoformat()
            if cls.usage_scope == "guild":
                cur.execute(
                    f"INSERT OR REPLACE INTO {table} (id, last_used) VALUES (1, ?)",
                    (now,),
                )
            elif cls.usage_scope == "pair":
                if peer_id is None:
                    raise ValueError(f"{cls.name} requires peer_id")
                self._mark_pair(cur, cls, table, user_id, peer_id, now)
            elif cls.cooldown == COOLDOWN_REIGN or cls.usage_scope == "shared_reign":
                cur.execute(
                    f"INSERT OR REPLACE INTO {table} (user_id, user_display_name) VALUES (?, ?)",
                    (user_id, display_name),
                )
            elif cls.cooldown == COOLDOWN_SEASON:
                cur.execute(
                    f"INSERT OR REPLACE INTO {table} (user_id, used_at) VALUES (?, ?)",
                    (user_id, now),
                )
            else:
                cur.execute(
                    f"INSERT OR REPLACE INTO {table} (user_id, command_name, last_used) "
                    "VALUES (?, ?, ?)",
                    (user_id, cls.name, now),
                )
            conn.commit()
        finally:
            conn.close()

    def _check_period(self, cur, cls: type[FartAbility], table: str, user_id: int):
        cur.execute(
            f"SELECT last_used FROM {table} WHERE user_id=? AND command_name=?",
            (user_id, cls.name),
        )
        row = cur.fetchone()
        if not row:
            return True, None
        parsed = safe_parse_datetime(row[0])
        if not parsed:
            return True, None
        pretty = _pretty(cls.name)
        if cls.cooldown == COOLDOWN_DAILY:
            last_date = parse_to_est_date(row[0])
            if last_date == get_est_date():
                remaining = get_est_midnight() - get_est_now()
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                return False, (
                    f"You can only use {pretty} once per day! "
                    f"Try again in **{hours}h {minutes}m** (resets at midnight EST)."
                )
            return True, None

        last_used_date = parsed.date()
        next_available = last_used_date + datetime.timedelta(weeks=1)
        today = datetime.datetime.now().date()
        if next_available > today:
            days_remaining = max(1, (next_available - today).days)
            return False, (
                f"You can only use {pretty} once per week! "
                f"Try again in {days_remaining} day{'s' if days_remaining != 1 else ''}."
            )
        return True, None

    def _check_guild(self, cur, cls: type[FartAbility], table: str):
        cur.execute(f"SELECT last_used FROM {table} WHERE id = 1")
        row = cur.fetchone()
        if not row:
            return True, None
        last_date = parse_to_est_date(row[0])
        if last_date == get_est_date():
            remaining = get_est_midnight() - get_est_now()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            pretty = _pretty(cls.name)
            return False, (
                f"{pretty} can only be fired once per day for the whole server! "
                f"Try again in **{hours}h {minutes}m** (resets at midnight EST)."
            )
        return True, None

    def _check_reign(self, cur, table: str, user_id: int):
        cur.execute(f"SELECT 1 FROM {table} WHERE user_id=?", (user_id,))
        if cur.fetchone():
            return False, "You have already used a once-per-reign action during your reign."
        return True, None

    def _check_season_user(self, cur, cls: type[FartAbility], table: str, user_id: int):
        cur.execute(f"SELECT 1 FROM {table} WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            pretty = _pretty(cls.name)
            return False, f"You can only use {pretty} once per season!"
        return True, None

    def _check_pair(self, cur, cls: type[FartAbility], table: str, user_id: int, peer_id: int):
        if table == "fart_gift_usage":
            cur.execute(
                "SELECT 1 FROM fart_gift_usage WHERE gifter_id = ? AND recipient_id = ?",
                (user_id, peer_id),
            )
        elif table == "fart_donation_usage":
            cur.execute(
                "SELECT 1 FROM fart_donation_usage WHERE donor_id = ? AND recipient_id = ?",
                (user_id, peer_id),
            )
        else:
            cur.execute(
                f"SELECT 1 FROM {table} WHERE user_id = ? AND peer_id = ?",
                (user_id, peer_id),
            )
        if cur.fetchone():
            pretty = _pretty(cls.name)
            return False, f"You can only use {pretty} on that player once per season!"
        return True, None

    def _mark_pair(self, cur, cls, table, user_id, peer_id, now):
        if table == "fart_gift_usage":
            cur.execute(
                "INSERT OR REPLACE INTO fart_gift_usage (gifter_id, recipient_id, gifted_at) "
                "VALUES (?, ?, ?)",
                (user_id, peer_id, now),
            )
        elif table == "fart_donation_usage":
            cur.execute(
                "INSERT OR REPLACE INTO fart_donation_usage (donor_id, recipient_id, donated_at) "
                "VALUES (?, ?, ?)",
                (user_id, peer_id, now),
            )
        else:
            cur.execute(
                f"INSERT OR REPLACE INTO {table} (user_id, peer_id, used_at) VALUES (?, ?, ?)",
                (user_id, peer_id, now),
            )


_default_tracker = UsageTracker()


def check_usage(ability, user_id: int, *, peer_id: int | None = None, db_path: str | None = None):
    tracker = UsageTracker(db_path) if db_path else _default_tracker
    return tracker.check(ability, user_id, peer_id=peer_id)


def mark_usage(
    ability,
    user_id: int,
    *,
    peer_id: int | None = None,
    display_name: str | None = None,
    db_path: str | None = None,
):
    tracker = UsageTracker(db_path) if db_path else _default_tracker
    tracker.mark(ability, user_id, peer_id=peer_id, display_name=display_name)
