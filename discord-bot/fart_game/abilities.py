"""Action and Item class registry for the fart game.

Season reset collects usage tables from every registered subclass. When you
add a new command, subclass Action or Item and declare how usage is stored —
do not add it to a separate reset list.
"""

from __future__ import annotations

from typing import ClassVar

COOLDOWN_NONE = "none"
COOLDOWN_DAILY = "daily"
COOLDOWN_WEEKLY = "weekly"
COOLDOWN_SEASON = "once_per_season"
COOLDOWN_REIGN = "once_per_reign"

# Shared daily action among !fart / !fart_gift / !fartprediction lives on
# fart_scores.date_last_updated, which is wiped with GAME_STATE_TABLES.
GAME_STATE_TABLES = (
    "fart_scores",
    "fart_history",
    "lucky_charms",
    "protection_status",
    "shop_blocks",
    "gas_shields",
    "fart_traps",
)

_REGISTRY: dict[str, type[FartAbility]] = {}


class FartAbility:
    """Base for anything a player can do that may track usage."""

    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    cooldown: ClassVar[str] = COOLDOWN_NONE
    cost: ClassVar[int] = 0
    damage: ClassVar[int] = 0
    sort_order: ClassVar[int] = 0
    effect: ClassVar[dict] = {}
    kind: ClassVar[str] = "ability"

    # None = infer from cooldown. "" = no dedicated usage table.
    usage_table: ClassVar[str | None] = None
    # user | pair | guild | shared_reign
    usage_scope: ClassVar[str] = "user"
    extra_reset_tables: ClassVar[tuple[str, ...]] = ()
    uses_shared_daily_action: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__name__ in {"FartAbility", "Action", "Item"}:
            return
        name = getattr(cls, "name", None)
        if not name:
            return
        _REGISTRY[name] = cls

    @classmethod
    def inferred_usage_table(cls) -> str | None:
        if cls.usage_table is not None:
            return cls.usage_table or None
        if cls.uses_shared_daily_action:
            return None
        if cls.cooldown in (COOLDOWN_DAILY, COOLDOWN_WEEKLY):
            if cls.usage_scope == "guild":
                return f"{cls.name}_usage"
            return "command_usage"
        if cls.cooldown == COOLDOWN_SEASON:
            return f"{cls.name}_usage"
        if cls.cooldown == COOLDOWN_REIGN:
            return "fart_leader_only_once"
        return None

    @classmethod
    def usage_tables(cls) -> tuple[str, ...]:
        tables: list[str] = []
        inferred = cls.inferred_usage_table()
        if inferred:
            tables.append(inferred)
        tables.extend(cls.extra_reset_tables)
        return tuple(dict.fromkeys(tables))

    @classmethod
    def as_command_tuple(cls) -> tuple:
        return (
            cls.name,
            cls.label,
            cls.description,
            cls.cost,
            cls.damage,
            cls.cooldown,
            cls.sort_order,
        )

    @classmethod
    def as_shop_tuple(cls) -> tuple:
        return (
            cls.name,
            cls.label,
            cls.description,
            cls.cost,
            cls.damage,
            cls.cooldown,
        )


class Action(FartAbility):
    kind = "action"


class Item(FartAbility):
    kind = "item"


def all_abilities() -> list[type[FartAbility]]:
    return list(_REGISTRY.values())


def all_actions() -> list[type[Action]]:
    return [c for c in _REGISTRY.values() if issubclass(c, Action) and c is not Action]


def all_items() -> list[type[Item]]:
    return [c for c in _REGISTRY.values() if issubclass(c, Item) and c is not Item]


def get_ability(name: str) -> type[FartAbility] | None:
    return _REGISTRY.get(name)


def tables_to_reset() -> tuple[str, ...]:
    """Every game-state and ability-usage table a season reset should wipe."""
    tables: list[str] = list(GAME_STATE_TABLES)
    for cls in all_abilities():
        tables.extend(cls.usage_tables())
    return tuple(dict.fromkeys(tables))


def discover_usage_tables(existing_table_names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Include leftover *_usage tables so new stores reset even before a class exists."""
    extra = [
        name
        for name in existing_table_names
        if name.endswith("_usage") and name not in tables_to_reset()
    ]
    return tuple(dict.fromkeys([*tables_to_reset(), *extra]))


# --- Actions -----------------------------------------------------------------


class Fart(Action):
    name = "fart"
    label = "Fart"
    description = "Roll for random fart points"
    cooldown = COOLDOWN_DAILY
    sort_order = 1
    uses_shared_daily_action = True
    usage_table = ""
    effect = {"action": "roll", "formula": "1d100", "points": "roll_value"}


class FartGift(Action):
    name = "fart_gift"
    label = "Fart Gift"
    description = (
        "Roll your daily fart and give the points to another player "
        "(once per player per season)"
    )
    cooldown = COOLDOWN_DAILY
    sort_order = 2
    uses_shared_daily_action = True
    usage_table = "fart_gift_usage"
    usage_scope = "pair"
    effect = {
        "action": "gift_roll",
        "formula": "1d100",
        "points": "roll_value",
        "target": "specified",
        "uses_daily": True,
        "once_per_recipient_per_season": True,
    }


class FartPrediction(Action):
    name = "fartprediction"
    label = "Fart Prediction"
    description = "Predict fart type for 2x or half points"
    cooldown = COOLDOWN_DAILY
    sort_order = 3
    uses_shared_daily_action = True
    usage_table = ""
    effect = {
        "action": "prediction",
        "correct_multiplier": 2,
        "wrong_multiplier": 0.5,
    }


class BullFart(Action):
    name = "bullfart"
    label = "Bull Fart"
    description = "Bonus points based on last fart type"
    cooldown = COOLDOWN_WEEKLY
    sort_order = 4
    effect = {
        "action": "bonus",
        "source": "last_fart_type",
        "bonuses": {
            "curio_shart": 50,
            "unique": 35,
            "elite": 25,
            "exceptional": 15,
            "ordinary": 10,
        },
    }


class Taxes(Action):
    name = "taxes"
    label = "Taxes"
    description = "Take 20% from everyone else, give it all to the fartlord"
    cooldown = COOLDOWN_REIGN
    damage = 20
    sort_order = 5
    usage_scope = "shared_reign"
    usage_table = "fart_leader_only_once"
    effect = {"action": "redistribute", "from": "others", "to": "leader", "percent": 20}


class Wealth(Action):
    name = "wealth"
    label = "Wealth"
    description = "Take 50% from top 5, give to everyone else"
    cooldown = COOLDOWN_REIGN
    damage = 50
    sort_order = 6
    usage_scope = "shared_reign"
    usage_table = "fart_leader_only_once"
    effect = {"action": "redistribute", "from": "top5", "to": "others", "percent": 50}


class GigaFartCannon(Action):
    name = "giga_fart_cannon"
    label = "Giga Fart Cannon"
    description = (
        "Assigns double damage to a random top 5 player (once per day for the whole server)"
    )
    cooldown = COOLDOWN_DAILY
    sort_order = 7
    usage_scope = "guild"
    usage_table = "giga_fart_cannon_usage"
    effect = {
        "action": "mark_double_damage",
        "target": "random_top5",
        "scope": "guild",
        "once_per_day": True,
    }


# --- Items -------------------------------------------------------------------


class BlueShell(Item):
    name = "blue_shell"
    label = "Blue Shell"
    description = "Hits the leader with 6d20/2 damage"
    cost = 20
    cooldown = COOLDOWN_DAILY
    effect = {"action": "damage", "target": "leader", "formula": "6d20/2"}


class RedShell(Item):
    name = "red_shell"
    label = "Red Shell"
    description = "Hits the player directly in front of you with 3d20/2 damage"
    cost = 10
    effect = {"action": "damage", "target": "ahead_1", "formula": "3d20/2"}


class GreenShell(Item):
    name = "green_shell"
    label = "Green Shell"
    description = "Hits a random player in front of you with 2d20/2 damage"
    cost = 5
    effect = {"action": "damage", "target": "random_ahead", "formula": "2d20/2"}


class Banana(Item):
    name = "banana"
    label = "Banana"
    description = "Hits a random player behind you with 2d20/2 damage"
    cost = 5
    effect = {"action": "damage", "target": "random_behind", "formula": "2d20/2"}


class BigBanana(Item):
    name = "big_banana"
    label = "Big Banana"
    description = "Hits a random player behind you with 4d10 damage"
    cost = 20
    cooldown = COOLDOWN_DAILY
    effect = {"action": "damage", "target": "random_behind", "formula": "4d10"}


class Star(Item):
    name = "star"
    label = "Star"
    description = (
        "Protects you from all items for 72 hours (costs 10% of your points). "
        "Blocked after Evil Star."
    )
    cooldown = COOLDOWN_WEEKLY
    extra_reset_tables = ("protection_status",)
    effect = {
        "action": "protect",
        "duration": "72h",
        "cost_type": "percent",
        "cost_percent": 10,
        "blocked_after": "evil_star",
    }


class Mushroom(Item):
    name = "mushroom"
    label = "Mushroom"
    description = "Next fart rolls twice, take higher!"
    cost = 5
    cooldown = COOLDOWN_WEEKLY
    usage_table = "lucky_charm_usage"
    extra_reset_tables = ("lucky_charms",)
    effect = {
        "action": "buff",
        "effect": "double_roll",
        "description": "Next fart rolls twice, take higher",
    }


class Bobomb(Item):
    name = "bobomb"
    label = "Bob-omb"
    description = "Hits the top 5 players with 3d20/2 damage"
    cost = 25
    effect = {"action": "damage", "target": "top5", "formula": "3d20/2"}


class FartStar(Item):
    name = "fart_star"
    label = "Fart Star"
    description = (
        "Removes star protection from a random protected user. Blocked after Evil Star."
    )
    cooldown = COOLDOWN_WEEKLY
    effect = {
        "action": "remove_buff",
        "target": "random_protected",
        "removes": "star",
        "cost_type": "percent",
        "cost_percent": 10,
        "blocked_after": "evil_star",
    }


class EvilStar(Item):
    name = "evil_star"
    label = "Evil Star"
    description = (
        "Doubles your points if you have exactly 666. Once/season; locks out other stars."
    )
    cooldown = COOLDOWN_SEASON
    usage_table = "evil_star_usage"
    effect = {
        "action": "conditional",
        "condition": "score_equals",
        "value": 666,
        "on_true": {"action": "multiply_score", "multiplier": 2},
        "cost_type": "free",
        "once_per_season": True,
        "locks_star_commands": True,
    }


class ThunderFart(Item):
    name = "thunder_fart"
    label = "Thunder Fart"
    description = "Hits ALL players for 10 damage each"
    cost = 10
    cooldown = COOLDOWN_WEEKLY
    effect = {"action": "damage", "target": "all", "amount": 10}


class GasShield(Item):
    name = "gas_shield"
    label = "Gas Shield"
    description = "Reflects 50% damage back at the next attacker"
    cost = 8
    extra_reset_tables = ("gas_shields",)
    effect = {"action": "shield", "reflect_percent": 50}


class StinkBomb(Item):
    name = "stink_bomb"
    label = "Stink Bomb"
    description = "Hits a random player (anyone!) for 3d20/2 damage"
    cost = 12
    effect = {"action": "damage", "target": "random_any", "formula": "3d20/2"}


class FartRocket(Item):
    name = "fart_rocket"
    label = "Fart Rocket"
    description = "Swap scores with a random player"
    cost = 100
    cooldown = COOLDOWN_WEEKLY
    effect = {"action": "swap_scores", "target": "random"}


class FartLance(Item):
    name = "fart_lance"
    label = "Fart Lance"
    description = "Hits up to 3 players ahead with diminishing damage"
    cost = 15
    effect = {
        "action": "multi_damage",
        "target": "ahead_3",
        "formulas": ["3d20/2", "2d20/2", "1d20/2"],
    }


class FartTrap(Item):
    name = "fart_trap"
    label = "Fart Trap"
    description = "A player's next attack backfires on them!"
    cost = 20
    extra_reset_tables = ("fart_traps",)
    effect = {"action": "trap", "target": "random", "effect": "attack_backfire"}


class FartTwister(Item):
    name = "fart_twister"
    label = "Fart Twister"
    description = "Launch a player into another! Damage = half launched player's score"
    cost = 50
    cooldown = COOLDOWN_WEEKLY
    effect = {
        "action": "launch",
        "target": "random",
        "damage_formula": "target_score/2",
        "uses_daily": True,
    }


class StinkCloud(Item):
    name = "stink_cloud"
    label = "Stink Cloud"
    description = "Blocks a random player from shop for 24 hours (5% of points)"
    cooldown = COOLDOWN_DAILY
    extra_reset_tables = ("shop_blocks",)
    effect = {
        "action": "block_shop",
        "target": "random",
        "duration": "24h",
        "cost_type": "percent",
        "cost_percent": 5,
    }


class GasGamble(Item):
    name = "gas_gamble"
    label = "Gas Gamble"
    description = "40% chance to double your bet, 60% to lose it all"
    effect = {
        "action": "gamble",
        "win_chance": 40,
        "win_multiplier": 2,
        "lose_multiplier": 0,
    }


class FartLeech(Item):
    name = "fart_leech"
    label = "Fart Leech"
    description = "Steal 2d20/2 points from a random player"
    cost = 5
    cooldown = COOLDOWN_DAILY
    effect = {"action": "steal", "target": "random", "formula": "2d20/2"}


class FartDonation(Item):
    name = "fart_donation"
    label = "Fart Donation"
    description = "Donate points to another player (max 100, once per player per season)"
    cooldown = COOLDOWN_SEASON
    usage_table = "fart_donation_usage"
    usage_scope = "pair"
    effect = {
        "action": "donate",
        "target": "specified",
        "cost_type": "custom",
        "max_amount": 100,
        "once_per_recipient_per_season": True,
    }


class FartCourt(Item):
    name = "fart_court"
    label = "Fart Court"
    description = "50% chance they pay you the amount, 50% chance you pay them"
    cooldown = COOLDOWN_WEEKLY
    effect = {
        "action": "court",
        "target": "specified",
        "win_chance": 50,
        "cost_type": "custom",
    }
