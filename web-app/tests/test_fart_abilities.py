"""Fart game ability registry and season-reset coverage."""

import sqlite3

from fart_game.abilities import (
    COOLDOWN_DAILY,
    COOLDOWN_REIGN,
    COOLDOWN_SEASON,
    COOLDOWN_WEEKLY,
    Item,
    all_actions,
    all_items,
    discover_usage_tables,
    get_ability,
    tables_to_reset,
)
from repositories.fart import FartRepository


class TestAbilityRegistry:
    def test_actions_and_items_are_registered(self):
        action_names = {cls.name for cls in all_actions()}
        item_names = {cls.name for cls in all_items()}
        assert "fart" in action_names
        assert "taxes" in action_names
        assert "wealth" in action_names
        assert "giga_fart_cannon" in action_names
        assert "blue_shell" in item_names
        assert "evil_star" in item_names
        assert "fart_donation" in item_names
        assert "mushroom" in item_names

    def test_cooldown_kinds_are_represented(self):
        cooldowns = {cls.cooldown for cls in [*all_actions(), *all_items()]}
        assert COOLDOWN_DAILY in cooldowns
        assert COOLDOWN_WEEKLY in cooldowns
        assert COOLDOWN_SEASON in cooldowns
        assert COOLDOWN_REIGN in cooldowns

    def test_reset_tables_include_all_usage_stores(self):
        tables = set(tables_to_reset())
        assert "fart_scores" in tables
        assert "command_usage" in tables
        assert "lucky_charm_usage" in tables
        assert "fart_leader_only_once" in tables
        assert "evil_star_usage" in tables
        assert "fart_donation_usage" in tables
        assert "fart_gift_usage" in tables
        assert "giga_fart_cannon_usage" in tables

    def test_new_item_class_is_picked_up_without_reset_list_edit(self):
        class SeasonalHonk(Item):
            name = "seasonal_honk"
            label = "Seasonal Honk"
            cooldown = COOLDOWN_SEASON
            usage_table = "seasonal_honk_usage"

        try:
            assert "seasonal_honk_usage" in tables_to_reset()
            assert get_ability("seasonal_honk") is SeasonalHonk
        finally:
            from fart_game import abilities as abilities_mod

            abilities_mod._REGISTRY.pop("seasonal_honk", None)


class TestFartRepositoryResetCoverage:
    def test_reset_clears_daily_weekly_season_reign_and_unknown_usage(self, tmp_path):
        db_path = tmp_path / "fart_scores.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE fart_scores (
                user_id INTEGER PRIMARY KEY,
                user_display_name TEXT,
                date_last_updated TEXT,
                score INTEGER
            );
            CREATE TABLE command_usage (
                user_id INTEGER,
                command_name TEXT,
                last_used TEXT,
                PRIMARY KEY (user_id, command_name)
            );
            CREATE TABLE lucky_charm_usage (
                user_id INTEGER,
                command_name TEXT,
                last_used TEXT,
                PRIMARY KEY (user_id, command_name)
            );
            CREATE TABLE fart_leader_only_once (
                user_id INTEGER PRIMARY KEY,
                user_display_name TEXT
            );
            CREATE TABLE evil_star_usage (
                user_id INTEGER PRIMARY KEY,
                used_at TEXT NOT NULL
            );
            CREATE TABLE giga_fart_cannon_usage (
                id INTEGER PRIMARY KEY,
                last_used TEXT NOT NULL
            );
            CREATE TABLE future_widget_usage (
                user_id INTEGER PRIMARY KEY,
                used_at TEXT NOT NULL
            );
            INSERT INTO fart_scores VALUES (1, 'A', '2026-08-24T00:00:00', 10);
            INSERT INTO command_usage VALUES (1, 'blue_shell', '2026-08-24T00:00:00');
            INSERT INTO command_usage VALUES (1, 'bullfart', '2026-08-20T00:00:00');
            INSERT INTO lucky_charm_usage VALUES (1, 'mushroom', '2026-08-20T00:00:00');
            INSERT INTO fart_leader_only_once VALUES (1, 'A');
            INSERT INTO evil_star_usage VALUES (1, '2026-08-01T00:00:00');
            INSERT INTO giga_fart_cannon_usage VALUES (1, '2026-08-24T00:00:00');
            INSERT INTO future_widget_usage VALUES (1, '2026-08-24T00:00:00');
            """
        )
        conn.commit()
        conn.close()

        repo = FartRepository(db_path=db_path)
        cleared = repo.reset_game()

        assert cleared["command_usage"] == 2
        assert cleared["lucky_charm_usage"] == 1
        assert cleared["fart_leader_only_once"] == 1
        assert cleared["evil_star_usage"] == 1
        assert cleared["giga_fart_cannon_usage"] == 1
        assert cleared["future_widget_usage"] == 1
        assert cleared["fart_scores"] == 1

        conn = sqlite3.connect(str(db_path))
        for table in (
            "command_usage",
            "lucky_charm_usage",
            "fart_leader_only_once",
            "evil_star_usage",
            "giga_fart_cannon_usage",
            "future_widget_usage",
            "fart_scores",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()

    def test_discover_includes_unregistered_usage_tables(self):
        found = discover_usage_tables(["command_usage", "brand_new_item_usage", "fart_scores"])
        assert "brand_new_item_usage" in found
        assert "fart_scores" in found
