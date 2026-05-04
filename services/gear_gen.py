"""Random level-scaled equipment generation for the gear shop."""
import random
import uuid

# ── Stat ranges per tier ──────────────────────────────────────────
_W_ATK  = {1: (4, 9),   2: (10, 15), 3: (18, 25), 4: (26, 35)}
_A_DEF  = {1: (3, 7),   2: (8,  13), 3: (13, 20), 4: (18, 26)}
_H_DEF  = {1: (2, 5),   2: (5,  9),  3: (8,  14), 4: (13, 19)}
_H_HP   = {1: (15, 30), 2: (35, 55), 3: (55, 80), 4: (80, 110)}
_AC_EN  = {1: (12, 20), 2: (22, 32), 3: (35, 48), 4: (50, 68)}
_AC_CR  = {1: (0.02, 0.04), 2: (0.04, 0.07), 3: (0.06, 0.09), 4: (0.08, 0.12)}

_TIER_PRICE = {1: 900, 2: 2_800, 3: 6_500, 4: 16_000}

_WEAPON_POOL = {
    1: [("🔧", "改裝鋼管"), ("🔪", "定製刀刃")],
    2: [("🔫", "黑市手槍"), ("⚡", "過載電棍")],
    3: [("🗡️", "強化義體刀"), ("💥", "客製散彈槍")],
    4: [("🏹", "磁軌狙擊槍"), ("💀", "神經干擾器")],
}
_ARMOR_POOL = {
    1: [("🧥", "廢料護甲"), ("👕", "加固夾克")],
    2: [("🥋", "戰術防彈衣"), ("🦾", "輕型義甲")],
    3: [("🛡️", "企業級裝甲"), ("🔒", "反應護甲板")],
    4: [("🤖", "軍用外骨骼"), ("✨", "量子護盾甲")],
}
_HELMET_POOL = {
    1: [("⛑️", "廢料頭盔")],
    2: [("🪖", "戰術頭盔")],
    3: [("👾", "賽博目鏡")],
    4: [("👑", "神經皇冠")],
}
_ACCSS_POOL = {
    1: [("💾", "舊型晶片")],
    2: [("🔌", "反應增益器")],
    3: [("🧠", "戰鬥AI晶片")],
    4: [("⚛️", "量子突觸")],
}

# Bonus attribute display prefixes
_PREFIX = {
    "atk":    "鑄刀型",
    "def":    "護盾型",
    "hp":     "強韌型",
    "energy": "超頻型",
    "crit":   "精準型",
}


def _level_to_tier(level: int) -> int:
    return min(4, max(1, 1 + (level - 1) // 12))


def _roll_bonus(item_type: str) -> tuple[str | None, int | float]:
    """45 % chance of a secondary attribute bonus."""
    if random.random() > 0.45:
        return None, 0
    candidates = {
        "weapon":    ["def", "hp", "energy", "crit"],
        "armor":     ["atk", "hp", "energy", "crit"],
        "helmet":    ["atk", "energy", "crit"],
        "accessory": ["atk", "def", "hp"],
    }[item_type]
    attr = random.choice(candidates)
    val: int | float = {
        "atk":    random.randint(2, 6),
        "def":    random.randint(2, 5),
        "hp":     random.randint(15, 35),
        "energy": random.randint(8, 20),
        "crit":   round(random.uniform(0.01, 0.03), 2),
    }[attr]
    return attr, val


def _base_item(type_key: str) -> dict:
    return {"atk_bonus": 0, "def_bonus": 0, "hp_bonus": 0, "energy_bonus": 0, "crit_bonus": 0.0}


def _gen_weapon(tier: int, level: int) -> tuple[dict, int]:
    lo, hi = _W_ATK[tier]
    lv_b   = int(level * 0.12)
    atk    = random.randint(lo + lv_b, hi + lv_b)
    emoji, base_name = random.choice(_WEAPON_POOL[tier])
    bonus_attr, bonus_val = _roll_bonus("weapon")
    name = f"{_PREFIX[bonus_attr]} {base_name}" if bonus_attr else base_name

    item = {**_base_item("weapon"), "name": name, "emoji": emoji, "tier": tier,
            "atk_bonus": atk, "desc": f"ATK +{atk}"}
    price = _TIER_PRICE[tier] + atk * 85 + random.randint(-400, 400)

    if bonus_attr == "def":
        item["def_bonus"] = bonus_val; price += bonus_val * 180
    elif bonus_attr == "hp":
        item["hp_bonus"] = bonus_val;  price += bonus_val * 110
    elif bonus_attr == "energy":
        item["energy_bonus"] = bonus_val; price += bonus_val * 140
    elif bonus_attr == "crit":
        item["crit_bonus"] = bonus_val; price += int(bonus_val * 12_000)

    return item, max(600, price)


def _gen_armor(tier: int, level: int) -> tuple[dict, int]:
    lo, hi = _A_DEF[tier]
    lv_b   = int(level * 0.10)
    def_   = random.randint(lo + lv_b, hi + lv_b)
    emoji, base_name = random.choice(_ARMOR_POOL[tier])
    bonus_attr, bonus_val = _roll_bonus("armor")
    name = f"{_PREFIX[bonus_attr]} {base_name}" if bonus_attr else base_name

    item = {**_base_item("armor"), "name": name, "emoji": emoji, "tier": tier,
            "def_bonus": def_, "desc": f"DEF +{def_}"}
    price = _TIER_PRICE[tier] + def_ * 95 + random.randint(-400, 400)

    if bonus_attr == "atk":
        item["atk_bonus"] = bonus_val; price += bonus_val * 180
    elif bonus_attr == "hp":
        item["hp_bonus"] = bonus_val;  price += bonus_val * 110
    elif bonus_attr == "energy":
        item["energy_bonus"] = bonus_val; price += bonus_val * 140
    elif bonus_attr == "crit":
        item["crit_bonus"] = bonus_val; price += int(bonus_val * 12_000)

    return item, max(600, price)


def _gen_helmet(tier: int, level: int) -> tuple[dict, int]:
    dlo, dhi = _H_DEF[tier]
    hlo, hhi = _H_HP[tier]
    lv_bd    = int(level * 0.07)
    lv_bh    = int(level * 0.45)
    def_  = random.randint(dlo + lv_bd, dhi + lv_bd)
    hp    = random.randint(hlo + lv_bh, hhi + lv_bh)
    emoji, base_name = _HELMET_POOL[tier][0]
    bonus_attr, bonus_val = _roll_bonus("helmet")
    name = f"{_PREFIX[bonus_attr]} {base_name}" if bonus_attr else base_name

    item = {**_base_item("helmet"), "name": name, "emoji": emoji, "tier": tier,
            "def_bonus": def_, "hp_bonus": hp, "desc": f"DEF +{def_} / HP +{hp}"}
    price = _TIER_PRICE[tier] + def_ * 90 + hp * 45 + random.randint(-400, 400)

    if bonus_attr == "atk":
        item["atk_bonus"] = bonus_val; price += bonus_val * 180
    elif bonus_attr == "energy":
        item["energy_bonus"] = bonus_val; price += bonus_val * 140
    elif bonus_attr == "crit":
        item["crit_bonus"] = bonus_val; price += int(bonus_val * 12_000)

    return item, max(600, price)


def _gen_accessory(tier: int, level: int) -> tuple[dict, int]:
    elo, ehi = _AC_EN[tier]
    clo, chi = _AC_CR[tier]
    lv_be    = int(level * 0.25)
    energy = random.randint(elo + lv_be, ehi + lv_be)
    crit   = round(random.uniform(clo, chi), 2)
    emoji, base_name = _ACCSS_POOL[tier][0]
    bonus_attr, bonus_val = _roll_bonus("accessory")
    name = f"{_PREFIX[bonus_attr]} {base_name}" if bonus_attr else base_name

    item = {**_base_item("accessory"), "name": name, "emoji": emoji, "tier": tier,
            "energy_bonus": energy, "crit_bonus": crit,
            "desc": f"能量 +{energy} / 爆擊 +{int(crit * 100)}%"}
    price = _TIER_PRICE[tier] + energy * 110 + int(crit * 22_000) + random.randint(-400, 400)

    if bonus_attr == "atk":
        item["atk_bonus"] = bonus_val; price += bonus_val * 180
    elif bonus_attr == "def":
        item["def_bonus"] = bonus_val; price += bonus_val * 140
    elif bonus_attr == "hp":
        item["hp_bonus"] = bonus_val; price += bonus_val * 100

    return item, max(600, price)


# ── Public API ────────────────────────────────────────────────────

def generate_shop_stock(level: int) -> tuple[dict, dict]:
    """Returns (shop_stock, custom_items_to_merge).

    shop_stock  = {"gen_level": N, "items": [{"item_id": str, "price": int}, ...]}
    custom_items = {item_id: stats_dict, ...}
    """
    tier = _level_to_tier(level)

    slots = [
        ("ci_w",  _gen_weapon),
        ("ci_w",  _gen_weapon),
        ("ci_a",  _gen_armor),
        ("ci_a",  _gen_armor),
        ("ci_h",  _gen_helmet),
        ("ci_ac", _gen_accessory),
    ]

    stock_items: list[dict] = []
    new_customs: dict       = {}

    for prefix, gen_fn in slots:
        item_id = f"{prefix}_{uuid.uuid4().hex[:12]}"
        stats, price = gen_fn(tier, level)
        new_customs[item_id] = stats
        stock_items.append({"item_id": item_id, "price": price})

    return {"gen_level": level, "items": stock_items}, new_customs
