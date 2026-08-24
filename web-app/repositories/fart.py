"""Repository for fart scores database access."""

import json
import sqlite3
from pathlib import Path
from random import randint

from fart_game.abilities import all_actions, all_items, discover_usage_tables
from webapp_config import FART_SCORES_DB_PATH

_CMD_EFFECTS = {cls.name: cls.effect for cls in all_actions()}
_SHOP_EFFECTS = {cls.name: cls.effect for cls in all_items()}


class FartRepository:
    """Data access for fart_scores.db."""

    _DEFAULT_SHOP_ITEMS = [cls.as_shop_tuple() for cls in all_items()]
    _DEFAULT_COMMANDS = [cls.as_command_tuple() for cls in all_actions()]

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = str(db_path or FART_SCORES_DB_PATH)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _add_column_if_missing(conn, table: str, column: str, col_type: str = "TEXT"):
        """Add a column to a table if it doesn't already exist."""
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()

    def _ensure_commands_table(self, conn):
        """Create fart_game_commands table and seed defaults if empty."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fart_game_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                description TEXT,
                cost INTEGER NOT NULL DEFAULT 0,
                damage INTEGER NOT NULL DEFAULT 0,
                cooldown TEXT NOT NULL DEFAULT 'daily',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                effect TEXT
            )
        """)
        self._add_column_if_missing(conn, "fart_game_commands", "effect", "TEXT")
        # Gothic S6: remove retired daily actions from existing installs
        conn.execute(
            "DELETE FROM fart_game_commands WHERE name IN ('attackfart', 'syphonfart')"
        )
        # Sync taxes/wealth redistribution percents on existing installs
        for name, label, desc, cost, damage, cooldown, sort_order in self._DEFAULT_COMMANDS:
            if name not in ("taxes", "wealth"):
                continue
            effect_json = json.dumps(_CMD_EFFECTS.get(name, {}))
            conn.execute(
                "UPDATE fart_game_commands SET description = ?, damage = ?, effect = ? WHERE name = ?",
                (desc, damage, effect_json, name),
            )
        count = conn.execute("SELECT COUNT(*) FROM fart_game_commands").fetchone()[0]
        if count == 0:
            for name, label, desc, cost, damage, cooldown, sort_order in self._DEFAULT_COMMANDS:
                effect_json = json.dumps(_CMD_EFFECTS.get(name, {}))
                conn.execute(
                    "INSERT INTO fart_game_commands (name, label, description, cost, damage, cooldown, sort_order, effect) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, label, desc, cost, damage, cooldown, sort_order, effect_json),
                )
            conn.commit()
        else:
            # Backfill effect for existing rows that have NULL effect
            rows = conn.execute(
                "SELECT id, name FROM fart_game_commands WHERE effect IS NULL"
            ).fetchall()
            for row in rows:
                effect = _CMD_EFFECTS.get(row["name"], {})
                conn.execute(
                    "UPDATE fart_game_commands SET effect = ? WHERE id = ?",
                    (json.dumps(effect), row["id"]),
                )
            # Ensure newer built-ins exist on older installs
            existing = {
                r["name"]
                for r in conn.execute("SELECT name FROM fart_game_commands").fetchall()
            }
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM fart_game_commands"
            ).fetchone()[0]
            for name, label, desc, cost, damage, cooldown, sort_order in self._DEFAULT_COMMANDS:
                if name in existing:
                    continue
                max_order += 1
                effect_json = json.dumps(_CMD_EFFECTS.get(name, {}))
                conn.execute(
                    "INSERT INTO fart_game_commands (name, label, description, cost, damage, cooldown, sort_order, effect) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, label, desc, cost, damage, cooldown, max_order, effect_json),
                )
            conn.commit()

    def get_leaderboard(self) -> list[dict]:
        """Get fart leaderboard data ordered by score descending."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, user_display_name, score, date_last_updated
            FROM fart_scores
            ORDER BY score DESC
        """)
        rows = cur.fetchall()
        conn.close()

        return [
            {
                "rank": rank,
                "user_id": row[0],
                "username": row[1],
                "score": row[2],
                "last_updated": row[3],
            }
            for rank, row in enumerate(rows, start=1)
        ]

    # --- Commands config ---

    def get_commands(self) -> list[dict]:
        """Get all fart game command configs."""
        conn = self._get_connection()
        self._ensure_commands_table(conn)
        rows = conn.execute(
            "SELECT id, name, label, description, cost, damage, cooldown, enabled, sort_order, effect "
            "FROM fart_game_commands ORDER BY sort_order"
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            d["effect"] = json.loads(d["effect"]) if d.get("effect") else {}
            results.append(d)
        return results

    def add_command(self, name: str, label: str, description: str | None = None,
                    cost: int = 0, damage: int = 0, cooldown: str = "daily",
                    effect: dict | None = None) -> int:
        """Add a new fart command config. Returns the new ID."""
        conn = self._get_connection()
        self._ensure_commands_table(conn)
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM fart_game_commands").fetchone()[0]
        effect_json = json.dumps(effect) if effect else None
        cursor = conn.execute(
            "INSERT INTO fart_game_commands (name, label, description, cost, damage, cooldown, sort_order, effect) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, label, description, cost, damage, cooldown, max_order + 1, effect_json),
        )
        conn.commit()
        command_id = cursor.lastrowid
        conn.close()
        return command_id

    def update_command(self, command_id: int, **fields) -> bool:
        """Update a fart command config. Returns True if updated."""
        allowed = {"name", "label", "description", "cost", "damage", "cooldown", "enabled", "sort_order", "effect"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "effect" and isinstance(v, dict):
                updates[k] = json.dumps(v)
            else:
                updates[k] = v
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [command_id]
        conn = self._get_connection()
        cursor = conn.execute(f"UPDATE fart_game_commands SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def delete_command(self, command_id: int) -> bool:
        """Delete a fart command config."""
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM fart_game_commands WHERE id = ?", (command_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    # --- Shop items ---

    def _ensure_shop_table(self, conn):
        """Create fart_shop_items table and seed defaults if empty."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fart_shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                description TEXT,
                cost INTEGER NOT NULL DEFAULT 0,
                damage INTEGER NOT NULL DEFAULT 0,
                cooldown TEXT NOT NULL DEFAULT 'none',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                effect TEXT
            )
        """)
        self._add_column_if_missing(conn, "fart_shop_items", "effect", "TEXT")
        # Gothic S6: remove retired shop items from existing installs
        conn.execute(
            "DELETE FROM fart_shop_items WHERE name IN ('bluestar', 'blue_star')"
        )
        count = conn.execute("SELECT COUNT(*) FROM fart_shop_items").fetchone()[0]
        if count == 0:
            for i, (name, label, desc, cost, damage, cooldown) in enumerate(self._DEFAULT_SHOP_ITEMS):
                effect_json = json.dumps(_SHOP_EFFECTS.get(name, {}))
                conn.execute(
                    "INSERT INTO fart_shop_items (name, label, description, cost, damage, cooldown, sort_order, effect) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, label, desc, cost, damage, cooldown, i + 1, effect_json),
                )
            conn.commit()
        else:
            # Backfill effect for existing rows that have NULL effect
            rows = conn.execute(
                "SELECT id, name FROM fart_shop_items WHERE effect IS NULL"
            ).fetchall()
            for row in rows:
                effect = _SHOP_EFFECTS.get(row["name"], {})
                conn.execute(
                    "UPDATE fart_shop_items SET effect = ? WHERE id = ?",
                    (json.dumps(effect), row["id"]),
                )
            # Ensure newer built-ins exist (e.g. restored fart_donation)
            existing = {
                r["name"]
                for r in conn.execute("SELECT name FROM fart_shop_items").fetchall()
            }
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM fart_shop_items"
            ).fetchone()[0]
            for name, label, desc, cost, damage, cooldown in self._DEFAULT_SHOP_ITEMS:
                if name in existing:
                    continue
                max_order += 1
                effect_json = json.dumps(_SHOP_EFFECTS.get(name, {}))
                conn.execute(
                    "INSERT INTO fart_shop_items (name, label, description, cost, damage, cooldown, sort_order, effect) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, label, desc, cost, damage, cooldown, max_order, effect_json),
                )
            conn.commit()

    def get_shop_items(self) -> list[dict]:
        """Get all fart shop item configs."""
        conn = self._get_connection()
        self._ensure_shop_table(conn)
        rows = conn.execute(
            "SELECT id, name, label, description, cost, damage, cooldown, enabled, sort_order, effect "
            "FROM fart_shop_items ORDER BY sort_order"
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            d["effect"] = json.loads(d["effect"]) if d.get("effect") else {}
            results.append(d)
        return results

    def add_shop_item(self, name: str, label: str, description: str | None = None,
                      cost: int = 0, damage: int = 0, cooldown: str = "none",
                      effect: dict | None = None) -> int:
        """Add a new fart shop item. Returns the new ID."""
        conn = self._get_connection()
        self._ensure_shop_table(conn)
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM fart_shop_items").fetchone()[0]
        effect_json = json.dumps(effect) if effect else None
        cursor = conn.execute(
            "INSERT INTO fart_shop_items (name, label, description, cost, damage, cooldown, sort_order, effect) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, label, description, cost, damage, cooldown, max_order + 1, effect_json),
        )
        conn.commit()
        item_id = cursor.lastrowid
        conn.close()
        return item_id

    def update_shop_item(self, item_id: int, **fields) -> bool:
        """Update a fart shop item. Returns True if updated."""
        allowed = {"name", "label", "description", "cost", "damage", "cooldown", "enabled", "sort_order", "effect"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "effect" and isinstance(v, dict):
                updates[k] = json.dumps(v)
            else:
                updates[k] = v
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [item_id]
        conn = self._get_connection()
        cursor = conn.execute(f"UPDATE fart_shop_items SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def delete_shop_item(self, item_id: int) -> bool:
        """Delete a fart shop item."""
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM fart_shop_items WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    # --- Game management ---

    def reset_game(self) -> dict:
        """Reset the fart game / season — scores, history, and every Action/Item usage table."""
        conn = self._get_connection()
        existing = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        tables = discover_usage_tables(existing)
        cleared = {}
        for table in tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
                cleared[table] = count
            except sqlite3.OperationalError:
                cleared[table] = 0
        conn.commit()
        conn.close()
        return cleared

    def evil_start(self) -> dict:
        """Evil start - reset game then give all known players random chaotic starting scores (-50 to 50)."""
        conn = self._get_connection()
        # Gather known players before reset
        try:
            players = conn.execute(
                "SELECT user_id, user_display_name FROM fart_scores"
            ).fetchall()
            players = [(r[0], r[1]) for r in players]
        except sqlite3.OperationalError:
            players = []
        conn.close()

        # Reset everything first
        self.reset_game()

        if not players:
            return {"players_affected": 0, "message": "No players found - game reset only"}

        # Re-seed with chaotic scores
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fart_scores (
                user_id INTEGER PRIMARY KEY,
                user_display_name TEXT,
                date_last_updated TEXT,
                score INTEGER
            )
        """)
        results = []
        for user_id, display_name in players:
            score = randint(-50, 50)
            conn.execute(
                "INSERT INTO fart_scores (user_id, user_display_name, date_last_updated, score) VALUES (?, ?, NULL, ?)",
                (user_id, display_name, score),
            )
            results.append({"user_id": user_id, "username": display_name, "score": score})
        conn.commit()
        conn.close()
        return {"players_affected": len(results), "players": results}
