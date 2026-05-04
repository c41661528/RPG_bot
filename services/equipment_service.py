import json
import random
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data" / "equipment"
_MAT  = Path(__file__).parent.parent / "data"


def _load(filename: str) -> list[dict]:
    with open(_DATA / filename, encoding="utf-8") as f:
        return json.load(f)


def _load_mat() -> list[dict]:
    with open(_MAT / "materials.json", encoding="utf-8") as f:
        return json.load(f)


_WEAPONS:     dict[str, dict] = {w["id"]: w for w in _load("weapons.json")}
_ARMOR:       dict[str, dict] = {a["id"]: a for a in _load("armor.json")}
_HELMETS:     dict[str, dict] = {h["id"]: h for h in _load("helmets.json")}
_ACCESSORIES: dict[str, dict] = {a["id"]: a for a in _load("accessories.json")}
_MATERIALS:   dict[str, dict] = {m["id"]: m for m in _load_mat()}
_ALL:         dict[str, dict] = {**_WEAPONS, **_ARMOR, **_HELMETS, **_ACCESSORIES}

# Tier → enemy level mapping for drops
_TIER_BY_LEVEL: dict[int, list[int]] = {
    1: [1],
    2: [1, 2],
    3: [1, 2, 3],
    4: [2, 3, 4],
    5: [3, 4],
}


def get_item(item_id: str) -> dict | None:
    return _ALL.get(item_id)


def get_material(mat_id: str) -> dict | None:
    return _MATERIALS.get(mat_id)


def all_materials() -> list[dict]:
    return list(_MATERIALS.values())


def is_weapon(item_id: str) -> bool:
    return item_id in _WEAPONS


def is_armor(item_id: str) -> bool:
    return item_id in _ARMOR


def is_helmet(item_id: str) -> bool:
    return item_id in _HELMETS


def is_accessory(item_id: str) -> bool:
    return item_id in _ACCESSORIES


def item_slot(item_id: str) -> str:
    """Returns '武器' / '護甲' / '頭盔' / '配件' or '' if unknown."""
    if is_weapon(item_id):    return "武器"
    if is_armor(item_id):     return "護甲"
    if is_helmet(item_id):    return "頭盔"
    if is_accessory(item_id): return "配件"
    return ""


def equipped_bonuses(
    equipped_weapon:    str | None,
    equipped_armor:     str | None,
    item_enhancements:  dict | None = None,
    equipped_helmet:    str | None  = None,
    equipped_accessory: str | None  = None,
) -> tuple[int, int, int, int, float]:
    """Returns (atk_bonus, def_bonus, hp_bonus, energy_bonus, crit_bonus)."""
    from config import ENHANCE_BONUS_PER_LV
    enh = item_enhancements or {}

    atk = 0
    if equipped_weapon and equipped_weapon in _WEAPONS:
        atk = (_WEAPONS[equipped_weapon]["atk_bonus"]
               + enh.get(equipped_weapon, 0) * ENHANCE_BONUS_PER_LV)

    def_ = 0
    if equipped_armor and equipped_armor in _ARMOR:
        def_ = (_ARMOR[equipped_armor]["def_bonus"]
                + enh.get(equipped_armor, 0) * ENHANCE_BONUS_PER_LV)

    hp = 0
    if equipped_helmet and equipped_helmet in _HELMETS:
        h    = _HELMETS[equipped_helmet]
        def_ += h["def_bonus"] + enh.get(equipped_helmet, 0) * ENHANCE_BONUS_PER_LV
        hp    = h["hp_bonus"]

    energy = 0
    crit   = 0.0
    if equipped_accessory and equipped_accessory in _ACCESSORIES:
        a      = _ACCESSORIES[equipped_accessory]
        energy = a["energy_bonus"]
        crit   = a["crit_bonus"]

    return atk, def_, hp, energy, crit


def enhance_level(item_id: str, item_enhancements: dict) -> int:
    return item_enhancements.get(item_id, 0)


def can_enhance(item_id: str, item_enhancements: dict) -> bool:
    from config import MAX_ENHANCE
    return enhance_level(item_id, item_enhancements) < MAX_ENHANCE


def try_drop(enemy_level: int) -> dict | None:
    """Returns a random dropped item dict or None (weapons/armor only)."""
    drop_chance = 0.25 + enemy_level * 0.05   # 30 % at Lv.1 → 50 % at Lv.5
    if random.random() > drop_chance:
        return None

    tiers = _TIER_BY_LEVEL.get(enemy_level, [1])
    tier  = random.choice(tiers)

    pool_w = [w for w in _WEAPONS.values() if w["tier"] == tier]
    pool_a = [a for a in _ARMOR.values()   if a["tier"] == tier]
    pool   = pool_w + pool_a
    return random.choice(pool).copy() if pool else None


def try_drop_full(enemy_level: int) -> dict | None:
    """Returns weapon/armor/helmet/accessory drop or None."""
    drop_chance = 0.25 + enemy_level * 0.05
    if random.random() > drop_chance:
        return None

    tiers = _TIER_BY_LEVEL.get(enemy_level, [1])
    tier  = random.choice(tiers)

    pool: list[dict] = []
    for src in (_WEAPONS, _ARMOR, _HELMETS, _ACCESSORIES):
        pool += [x for x in src.values() if x["tier"] == tier]
    return random.choice(pool).copy() if pool else None


def try_drop_material(enemy_level: int) -> dict | None:
    """15 % base chance; returns a material dict or None."""
    if random.random() > (0.10 + enemy_level * 0.02):
        return None
    weights = [m["drop_weight"] for m in _MATERIALS.values()]
    mats    = list(_MATERIALS.values())
    return random.choices(mats, weights=weights, k=1)[0].copy()


# ── Sell value ────────────────────────────────────────────────────
_TIER_SELL_BASE: dict[int, int] = {1: 60, 2: 200, 3: 550, 4: 1_400}


def sell_value(item_id: str, enh_level: int = 0) -> int:
    """Return how many credits the player gets for selling item_id at enh_level."""
    item = get_item(item_id)
    if not item:
        return 0
    base = _TIER_SELL_BASE.get(item.get("tier", 1), 60)
    # Each enhance level adds 30 % of base value
    return int(base * (1.0 + enh_level * 0.30))


def get_items_by_tier(tier: int) -> list[dict]:
    """Return all weapons and armors of a given tier (for exploration drops)."""
    pool = [w for w in _WEAPONS.values() if w["tier"] == tier]
    pool += [a for a in _ARMOR.values()  if a["tier"] == tier]
    return pool


def all_weapons() -> list[dict]:
    return list(_WEAPONS.values())


def all_armor() -> list[dict]:
    return list(_ARMOR.values())


def all_helmets() -> list[dict]:
    return list(_HELMETS.values())


def all_accessories() -> list[dict]:
    return list(_ACCESSORIES.values())
