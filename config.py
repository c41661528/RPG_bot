import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
DATABASE_URL: str = os.environ["DATABASE_URL"]

# ── Level progression ───────────────────────────────────────────
MAX_LEVEL = 50
STAT_POINTS_PER_LEVEL = 3


def exp_for_next_level(level: int) -> int:
    """EXP required to advance from `level` to `level + 1`."""
    return int(100 * (level**1.2))


# ── Starting conditions ─────────────────────────────────────────
STARTING_LOCATION = "廢墟東區"
STARTING_CREDITS = 500

# ── Class definitions ───────────────────────────────────────────
CLASS_BASE_STATS: dict[str, dict] = {
    "street_samurai": {"vitality": 8, "reflex": 5, "tech": 2, "hp": 120, "energy": 60},
    "netrunner":      {"vitality": 3, "reflex": 6, "tech": 6, "hp":  70, "energy": 120},
    "scavenger":      {"vitality": 5, "reflex": 8, "tech": 2, "hp":  90, "energy":  80},
}

# ── Skills (3 active skills per class) ─────────────────────────
CLASS_SKILLS: dict[str, list[dict]] = {
    "street_samurai": [
        {
            "id":          "berserker_slash",
            "name":        "暴怒斬",
            "emoji":       "🗡️",
            "energy_cost": 25,
            "desc":        "釋放義體全力一擊，造成 2 倍傷害。",
        },
        {
            "id":          "iron_wall",
            "name":        "鐵壁防禦",
            "emoji":       "🛡️",
            "energy_cost": 20,
            "desc":        "本回合傷害減少 70%，並以 50% 傷害反擊。",
        },
        {
            "id":          "cyber_overdrive",
            "name":        "義體超載",
            "emoji":       "⚡",
            "energy_cost": 35,
            "desc":        "超頻義體，ATK × 1.5，持續 3 回合。",
        },
    ],
    "netrunner": [
        {
            "id":          "neural_hack",
            "name":        "神經駭入",
            "emoji":       "💀",
            "energy_cost": 30,
            "desc":        "正常傷害，並使敵人下回合無法行動。",
        },
        {
            "id":          "virus_inject",
            "name":        "病毒植入",
            "emoji":       "🦠",
            "energy_cost": 25,
            "desc":        "注入病毒，每回合扣 8% 最大 HP，持續 3 回合。",
        },
        {
            "id":          "emp_blast",
            "name":        "電磁爆",
            "emoji":       "🔌",
            "energy_cost": 35,
            "desc":        "1.5 倍傷害，並使敵人感電 2 回合（每回合扣 5% HP）。",
        },
    ],
    "scavenger": [
        {
            "id":          "quick_strike",
            "name":        "速攻連擊",
            "emoji":       "⚡",
            "energy_cost": 20,
            "desc":        "閃電連續攻擊兩次。",
        },
        {
            "id":          "smoke_bomb",
            "name":        "煙霧彈",
            "emoji":       "💨",
            "energy_cost": 15,
            "desc":        "規避下次攻擊，且逃跑成功率提升至 95%。",
        },
        {
            "id":          "poison_blade",
            "name":        "毒刃",
            "emoji":       "🗡️",
            "energy_cost": 20,
            "desc":        "正常傷害，並使敵人中毒 3 回合（每回合扣 6% HP）。",
        },
    ],
}

# Keep backward-compat shim for anything still referencing SKILLS
SKILLS: dict[str, dict] = {cls: skills[0] for cls, skills in CLASS_SKILLS.items()}

# ── Combat mechanics ─────────────────────────────────────────────
DEFEND_ENERGY_COST = 20     # energy consumed when defending
COMBO_MAX          = 5      # max combo stacks
COMBO_BONUS        = 0.10   # +10 % damage per combo stack

# ── Enhancement ─────────────────────────────────────────────────
MAX_ENHANCE           = 5
ENHANCE_BONUS_PER_LV  = 2    # +2 ATK or DEF per enhance level
ENHANCE_COSTS         = [300, 800, 2_000, 4_000, 8_000]   # cost to go +0→+1 … +4→+5
ENHANCE_RATES         = [0.85, 0.70, 0.50, 0.30, 0.15]   # success rate

# ── Rebirth ─────────────────────────────────────────────────────
MAX_REBIRTH              = 5    # maximum number of rebirths
REBIRTH_REQUIRED_LEVEL   = 50   # must be max level
REBIRTH_STAT_BONUS       = 2    # +2 to ALL base stats per rebirth

# ── Shop prices ─────────────────────────────────────────────────
MEDKIT_COST           = 150   # credits
ENERGY_CELL_COST      = 100   # credits
MEDKIT_HEAL_PCT       = 0.35  # heals 35 % of max HP
LARGE_MEDKIT_COST     = 400   # credits
LARGE_MEDKIT_HEAL_PCT = 0.70  # heals 70 % of max HP — for higher-level players
ENERGY_CELL_RESTORE   = 40    # restores 40 energy

SHIELD_CHIP_COST     = 300
ADRENALINE_COST      = 200
STIMULANT_COST       = 180
CORROSIVE_VIAL_COST  = 220
EMP_GRENADE_COST     = 350
NANO_REPAIR_COST     = 280

# ── New consumable effects ──────────────────────────────────────
ADRENALINE_ATK_MULT  = 1.3    # +30 % ATK
ADRENALINE_DURATION  = 3      # turns
STIMULANT_HEAL_PCT   = 0.25   # 25 % HP
STIMULANT_ENERGY     = 25     # energy restored
CORROSIVE_VIAL_PCT   = 0.07   # 7 % HP per turn
CORROSIVE_VIAL_TURNS = 3
EMP_GRENADE_STUN     = 1      # turns
NANO_REPAIR_PCT      = 0.12   # 12 % HP per turn
NANO_REPAIR_TURNS    = 3

# ── Item rarity colour palette (shared with equipment) ─────────
TIER_EMOJI: dict[int, str] = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣"}

# ── Unified shop catalogue ─────────────────────────────────────
# tier 1: basic    tier 2: utility/buff    tier 3: advanced    tier 4: premium
SHOP_ITEMS: list[dict] = [
    {
        "id": "medkit", "name": "急救包", "emoji": "🩹", "tier": 1,
        "cost": MEDKIT_COST, "category": "recovery",
        "desc": f"恢復 {int(MEDKIT_HEAL_PCT * 100)}% 最大 HP",
    },
    {
        "id": "large_medkit", "name": "大型急救包", "emoji": "🚑", "tier": 3,
        "cost": LARGE_MEDKIT_COST, "category": "recovery",
        "desc": f"恢復 {int(LARGE_MEDKIT_HEAL_PCT * 100)}% 最大 HP（適合高等玩家）",
    },
    {
        "id": "energy_cell", "name": "能量電池", "emoji": "🔋", "tier": 1,
        "cost": ENERGY_CELL_COST, "category": "recovery",
        "desc": f"恢復 {ENERGY_CELL_RESTORE} 能量",
    },
    {
        "id": "stimulant", "name": "興奮劑", "emoji": "💉", "tier": 2,
        "cost": STIMULANT_COST, "category": "recovery",
        "desc": f"恢復 {int(STIMULANT_HEAL_PCT * 100)}% HP + {STIMULANT_ENERGY} 能量",
    },
    {
        "id": "nano_repair", "name": "奈米修復劑", "emoji": "🧬", "tier": 3,
        "cost": NANO_REPAIR_COST, "category": "recovery",
        "desc": f"每回合恢復 {int(NANO_REPAIR_PCT * 100)}% HP，持續 {NANO_REPAIR_TURNS} 回合",
    },
    {
        "id": "adrenaline", "name": "腎上腺素", "emoji": "💊", "tier": 2,
        "cost": ADRENALINE_COST, "category": "combat",
        "desc": f"ATK +{int((ADRENALINE_ATK_MULT - 1) * 100)}%，持續 {ADRENALINE_DURATION} 回合",
    },
    {
        "id": "shield_chip", "name": "護盾晶片", "emoji": "🔰", "tier": 3,
        "cost": SHIELD_CHIP_COST, "category": "combat",
        "desc": "抵擋下一次敵人攻擊",
    },
    {
        "id": "corrosive_vial", "name": "腐蝕瓶", "emoji": "🧪", "tier": 2,
        "cost": CORROSIVE_VIAL_COST, "category": "combat",
        "desc": f"敵人中毒 {CORROSIVE_VIAL_TURNS} 回合，每回合 -{int(CORROSIVE_VIAL_PCT * 100)}% HP",
    },
    {
        "id": "emp_grenade", "name": "電磁脈衝彈", "emoji": "⚡", "tier": 4,
        "cost": EMP_GRENADE_COST, "category": "combat",
        "desc": f"癱瘓敵人 {EMP_GRENADE_STUN} 回合",
    },
]

SHOP_ITEMS_BY_NAME: dict[str, dict] = {item["name"]: item for item in SHOP_ITEMS}

# ── Material shop prices ────────────────────────────────────────
MATERIAL_PRICES: dict[str, int] = {
    "scrap_metal":    350,
    "circuit_board":  900,
    "energy_core":  2_200,
    "nano_fiber":   5_500,
    "quantum_chip": 13_000,
}

CLASS_DISPLAY: dict[str, dict] = {
    "street_samurai": {
        "name": "街頭武士",
        "emoji": "⚔️",
        "desc": "義體強化的近戰戰士，擁有最高的生命值與護甲。以血肉之軀對抗機械洪流。",
    },
    "netrunner": {
        "name": "竄網使",
        "emoji": "💻",
        "desc": "意識連結網路的駭客術師，擅長電子攻擊與資訊戰。現實對他們不過是另一層程式碼。",
    },
    "scavenger": {
        "name": "拾荒者",
        "emoji": "🗡️",
        "desc": "在廢墟中求生的機巧之人，極高的反應神經讓他們總能先敵人一步找到好東西。",
    },
}
