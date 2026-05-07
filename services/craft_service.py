"""
Crafting system — upgrade and reforge equipment using materials.

Two recipe types:
  ▸ Upgrade: 3× same-slot+tier items + materials → 1× random tier+1 item
  ▸ Reforge: 1× shop/crafted item + materials → re-rolled stats (same tier)
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import flag_modified

from services import gear_gen
from services.equipment_service import get_item, item_slot
from services.title_service import increment_craft_count

if TYPE_CHECKING:
    from models.character import Character


_INVENTORY_LIMIT = 20

# tier (current) → cost dict for upgrading to tier+1
UPGRADE_COSTS: dict[int, dict[str, int]] = {
    1: {"credits":  500, "scrap_metal":   5},
    2: {"credits": 1500, "scrap_metal":   5, "circuit_board": 3},
    3: {"credits": 4000, "circuit_board": 5, "energy_core":   2},
}

# tier → cost dict for reforging an item of that tier
REFORGE_COSTS: dict[int, dict[str, int]] = {
    1: {"credits":  200, "scrap_metal":   2},
    2: {"credits":  600, "circuit_board": 2},
    3: {"credits": 1500, "energy_core":   1},
    4: {"credits": 3500, "nano_fiber":    1},
}

_CI_PREFIXES = ("ci_w_", "ci_a_", "ci_h_", "ci_ac_")


# ── Helpers ───────────────────────────────────────────────────────

def _slot_to_attr(slot: str) -> str:
    return {
        "武器": "equipped_weapon", "護甲": "equipped_armor",
        "頭盔": "equipped_helmet", "配件": "equipped_accessory",
    }.get(slot, "")


def _get_tier(item_id: str, custom_items: dict | None) -> int:
    item = get_item(item_id, custom_items)
    return item.get("tier", 1) if item else 1


def get_inventory_by_slot_tier(char: Character) -> dict[tuple[str, int], list[str]]:
    """Group inventory items by (slot, tier). Used by the upgrade UI."""
    out: dict[tuple[str, int], list[str]] = {}
    ci = char.custom_items or {}
    for iid in (char.inventory or []):
        slot = item_slot(iid)
        if not slot:
            continue
        tier = _get_tier(iid, ci)
        out.setdefault((slot, tier), []).append(iid)
    return out


def _check_cost(char: Character, cost: dict[str, int]) -> tuple[bool, str]:
    if char.credits < cost.get("credits", 0):
        return False, f"信用點不足（需 {cost['credits']:,}）。"
    mats = char.materials or {}
    for k, v in cost.items():
        if k == "credits":
            continue
        if mats.get(k, 0) < v:
            return False, f"材料 {k} 不足（需 {v}）。"
    return True, ""


def _deduct_cost(char: Character, cost: dict[str, int]) -> None:
    char.credits -= cost.get("credits", 0)
    mats = dict(char.materials or {})
    for k, v in cost.items():
        if k == "credits":
            continue
        mats[k] = mats.get(k, 0) - v
        if mats[k] <= 0:
            mats.pop(k, None)
    char.materials = mats
    flag_modified(char, "materials")


# ── Upgrade ───────────────────────────────────────────────────────

def can_upgrade(char: Character, slot: str, tier: int) -> tuple[bool, str]:
    if tier >= 4:
        return False, "已是最高階，無法繼續升階。"
    cost = UPGRADE_COSTS.get(tier)
    if not cost:
        return False, "此階級不支援升階。"
    ok, reason = _check_cost(char, cost)
    if not ok:
        return False, reason
    by = get_inventory_by_slot_tier(char)
    if len(by.get((slot, tier), [])) < 3:
        return False, f"背包中沒有 3 件 {slot} T{tier} 裝備。"
    return True, ""


def perform_upgrade(
    char: Character, slot: str, tier: int
) -> tuple[bool, dict | None, str]:
    """Returns (success, new_item_stats, message)."""
    ok, reason = can_upgrade(char, slot, tier)
    if not ok:
        return False, None, reason

    by = get_inventory_by_slot_tier(char)
    consumed = list(by[(slot, tier)][:3])

    inv = list(char.inventory or [])
    for iid in consumed:
        inv.remove(iid)

    if len(inv) >= _INVENTORY_LIMIT:
        return False, None, "背包已滿，請先騰出空間。"

    _deduct_cost(char, UPGRADE_COSTS[tier])

    # Generate new item
    new_stats, _price = gear_gen.generate_item(slot, tier + 1, char.level)
    new_id = f"{gear_gen.slot_prefix(slot)}_{uuid.uuid4().hex[:12]}"

    ci = dict(char.custom_items or {})
    ci[new_id] = new_stats
    char.custom_items = ci
    flag_modified(char, "custom_items")

    # Strip enhance data for items that are no longer in inventory or equipped
    equipped_attr = _slot_to_attr(slot)
    enh = dict(char.item_enhancements or {})
    for iid in consumed:
        if iid not in inv and (not equipped_attr or getattr(char, equipped_attr, None) != iid):
            enh.pop(iid, None)
    char.item_enhancements = enh
    flag_modified(char, "item_enhancements")

    inv.append(new_id)
    char.inventory = inv
    flag_modified(char, "inventory")

    increment_craft_count(char)
    return True, new_stats, "升階成功！"


# ── Reforge ───────────────────────────────────────────────────────

def can_reforge(char: Character, item_id: str) -> tuple[bool, str]:
    if not item_id.startswith(_CI_PREFIXES):
        return False, "僅可重鑄商店或合成裝備（基礎裝備不可重鑄）。"
    ci = char.custom_items or {}
    item = get_item(item_id, ci)
    if not item:
        return False, "找不到該裝備。"
    if item_id not in (char.inventory or []):
        return False, "該裝備不在背包中（必須先卸下才能重鑄）。"
    tier = item.get("tier", 1)
    cost = REFORGE_COSTS.get(tier)
    if not cost:
        return False, "該階級不支援重鑄。"
    ok, reason = _check_cost(char, cost)
    if not ok:
        return False, reason
    return True, ""


def perform_reforge(
    char: Character, item_id: str
) -> tuple[bool, dict | None, dict | None, str]:
    """Returns (success, new_stats, old_stats, message)."""
    ok, reason = can_reforge(char, item_id)
    if not ok:
        return False, None, None, reason

    ci = dict(char.custom_items or {})
    old = dict(ci.get(item_id, {}))
    if not old:
        return False, None, None, "找不到該裝備資料。"
    tier = old.get("tier", 1)
    slot = item_slot(item_id)

    _deduct_cost(char, REFORGE_COSTS[tier])

    new_stats, _price = gear_gen.generate_item(slot, tier, char.level)
    ci[item_id] = new_stats
    char.custom_items = ci
    flag_modified(char, "custom_items")

    # Reset enhance level (reforge wipes enhancement)
    enh = dict(char.item_enhancements or {})
    if item_id in enh:
        enh.pop(item_id, None)
        char.item_enhancements = enh
        flag_modified(char, "item_enhancements")

    increment_craft_count(char)
    return True, new_stats, old, "重鑄成功！"
