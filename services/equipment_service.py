import json
import random
import uuid
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

def _base_id(instance_id: str) -> str:
    """Strip the instance suffix (::xxxxxxxx) to get the base item id."""
    return instance_id.split("::")[0]


def make_instance_id(item_id: str) -> str:
    """Return a unique instance id for a newly created item."""
    return f"{item_id}::{uuid.uuid4().hex[:8]}"


def _tier_pool_for_level(level: int) -> list[int]:
    """Return the tier pool for a given enemy level (scales to any level)."""
    if level <= 1:  return [1]
    if level <= 2:  return [1, 2]
    if level <= 4:  return [2, 3]
    if level <= 6:  return [3, 4]
    return [4]


def get_item(item_id: str, custom_items: dict | None = None) -> dict | None:
    base = _base_id(item_id)
    if base in _ALL:
        return _ALL[base]
    if custom_items:
        return custom_items.get(item_id) or custom_items.get(base)
    return None


def get_material(mat_id: str) -> dict | None:
    return _MATERIALS.get(mat_id)


def all_materials() -> list[dict]:
    return list(_MATERIALS.values())


def is_weapon(item_id: str) -> bool:
    b = _base_id(item_id)
    return b in _WEAPONS or b.startswith("ci_w_")


def is_armor(item_id: str) -> bool:
    b = _base_id(item_id)
    return b in _ARMOR or b.startswith("ci_a_")


def is_helmet(item_id: str) -> bool:
    b = _base_id(item_id)
    return b in _HELMETS or b.startswith("ci_h_")


def is_accessory(item_id: str) -> bool:
    b = _base_id(item_id)
    return b in _ACCESSORIES or b.startswith("ci_ac_")


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
    custom_items:       dict | None = None,
) -> tuple[int, int, int, int, float]:
    """Returns (atk_bonus, def_bonus, hp_bonus, energy_bonus, crit_bonus)."""
    from config import ENHANCE_BONUS_PER_LV
    enh = item_enhancements or {}
    ci  = custom_items or {}

    def _get(iid: str) -> dict | None:
        return _ALL.get(_base_id(iid)) or ci.get(iid) or ci.get(_base_id(iid))

    atk = 0
    if equipped_weapon:
        w = _get(equipped_weapon)
        if w:
            atk = (w.get("atk_bonus", 0)
                   + enh.get(equipped_weapon, 0) * ENHANCE_BONUS_PER_LV)

    def_ = 0
    if equipped_armor:
        a = _get(equipped_armor)
        if a:
            def_ = (a.get("def_bonus", 0)
                    + enh.get(equipped_armor, 0) * ENHANCE_BONUS_PER_LV)

    hp = 0
    if equipped_helmet:
        h = _get(equipped_helmet)
        if h:
            def_ += h.get("def_bonus", 0) + enh.get(equipped_helmet, 0) * ENHANCE_BONUS_PER_LV
            hp    = h.get("hp_bonus", 0)

    energy = 0
    crit   = 0.0
    if equipped_accessory:
        ac = _get(equipped_accessory)
        if ac:
            energy = ac.get("energy_bonus", 0)
            crit   = ac.get("crit_bonus", 0.0)

    return atk, def_, hp, energy, crit


def enhance_level(item_id: str, item_enhancements: dict) -> int:
    return item_enhancements.get(item_id, 0)


def can_enhance(item_id: str, item_enhancements: dict) -> bool:
    from config import MAX_ENHANCE
    return enhance_level(item_id, item_enhancements) < MAX_ENHANCE


def try_drop(enemy_level: int) -> dict | None:
    """Returns a random dropped item dict or None (weapons/armor only)."""
    drop_chance = min(0.60, 0.25 + enemy_level * 0.05)
    if random.random() > drop_chance:
        return None

    tier = random.choice(_tier_pool_for_level(enemy_level))

    pool_w = [w for w in _WEAPONS.values() if w["tier"] == tier]
    pool_a = [a for a in _ARMOR.values()   if a["tier"] == tier]
    pool   = pool_w + pool_a
    return random.choice(pool).copy() if pool else None


def try_drop_full(enemy_level: int) -> dict | None:
    """Returns weapon/armor/helmet/accessory drop or None."""
    drop_chance = min(0.60, 0.25 + enemy_level * 0.05)
    if random.random() > drop_chance:
        return None

    tier = random.choice(_tier_pool_for_level(enemy_level))

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


def sell_value(item_id: str, enh_level: int = 0, custom_items: dict | None = None) -> int:
    """Return how many credits the player gets for selling item_id at enh_level."""
    item = get_item(item_id, custom_items)
    if not item:
        return 0
    base = _TIER_SELL_BASE.get(item.get("tier", 1), 60)
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
