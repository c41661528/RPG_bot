from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import CLASS_SKILLS, DEFEND_ENERGY_COST

if TYPE_CHECKING:
    from cogs.combat import CombatCog
    from services.combat_service import CombatState


# (action_suffix, label, emoji, description, tier)
_ITEM_DEFS = [
    ("medkit",          "急救包",       "🩹", "回復 35% HP",       1),
    ("tactical_medkit", "戰術急救包",   "⚕️", "回復 50% HP",       2),
    ("large_medkit",    "大型急救包",   "🚑", "回復 70% HP",       3),
    ("neuro_kit",       "神經修復套組", "🌟", "完全回滿 HP",       4),
    ("energy",          "能量電池",     "🔋", "回復能量",          1),
    ("stimulant",       "興奮劑",       "💉", "少量回 HP+能量",    2),
    ("nano_repair",     "奈米修復劑",   "🧬", "持續回 HP",         3),
    ("adrenaline",      "腎上腺素",     "💊", "暫時提升攻擊力",    2),
    ("shield_chip",     "護盾晶片",     "🔰", "獲得格擋與反擊",    3),
    ("corrosive_vial",  "腐蝕瓶",       "🧪", "對敵人持續中毒",    2),
    ("emp_grenade",     "EMP手雷",      "⚡", "癱瘓敵人 1 回合",   4),
]

_TIER_E = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣"}


def _item_count(state: CombatState, action: str) -> int:
    if action == "medkit":
        return state.medkits
    if action == "energy":
        return state.energy_cells_in_combat
    return state.consumables_in_combat.get(action, 0)


class ItemSelect(discord.ui.Select):
    def __init__(self, cog: CombatCog, character_id: int, state: CombatState) -> None:
        self.cog          = cog
        self.character_id = character_id

        options: list[discord.SelectOption] = []
        for action, label, emoji, desc, tier in _ITEM_DEFS:
            count = _item_count(state, action)
            if count <= 0:
                continue
            tier_e = _TIER_E.get(tier, "⚪")
            options.append(
                discord.SelectOption(
                    label=f"{label} ×{count}",
                    value=action,
                    emoji=emoji,
                    description=f"{tier_e} {desc}",
                )
            )

        disabled = not options
        if not options:
            options = [discord.SelectOption(label="（沒有可用道具）", value="__none__")]

        super().__init__(
            placeholder="🎒 使用道具...",
            options=options,
            min_values=1,
            max_values=1,
            row=2,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        action = self.values[0]
        if action == "__none__":
            return await interaction.response.defer()
        await self.cog.process_turn(interaction, self.character_id, f"item_{action}")


class SkillSelect(discord.ui.Select):
    def __init__(self, cog: CombatCog, character_id: int, state: CombatState) -> None:
        self.cog          = cog
        self.character_id = character_id

        skills  = CLASS_SKILLS[state.char_class]
        options = [
            discord.SelectOption(
                label=f"{s['name']}  ({s['energy_cost']} 能量)",
                value=s["id"],
                emoji=s["emoji"],
                description=s["desc"][:50],
            )
            for s in skills
        ]

        super().__init__(
            placeholder="💠 選擇技能...",
            options=options,
            min_values=1,
            max_values=1,
            row=1,
        )
        self.disabled = not any(state.energy >= s["energy_cost"] for s in skills)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, f"skill_{self.values[0]}")


class CombatView(discord.ui.View):
    def __init__(self, cog: CombatCog, character_id: int, state: CombatState) -> None:
        super().__init__(timeout=120)
        self.cog          = cog
        self.character_id = character_id

        # ── Row 1: skill select ───────────────────────────────────
        self.add_item(SkillSelect(cog, character_id, state))

        # ── Row 2: item select ───────────────────────────────────
        self.add_item(ItemSelect(cog, character_id, state))

        # Disable defend when low energy
        can_defend = state.energy >= DEFEND_ENERGY_COST
        self.children[1].disabled = not can_defend   # defend is children[1]

    # ── Row 0 ────────────────────────────────────────────────────

    @discord.ui.button(label="攻擊", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, "attack")

    @discord.ui.button(label="防禦", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
    async def defend(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, "defend")

    @discord.ui.button(label="逃跑", emoji="🏃", style=discord.ButtonStyle.secondary, row=0)
    async def flee(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, "flee")

    # ── Timeout ──────────────────────────────────────────────────

    async def on_timeout(self) -> None:
        await self.cog.handle_timeout(self.character_id)
