from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import CLASS_SKILLS, DEFEND_ENERGY_COST

if TYPE_CHECKING:
    from cogs.combat import CombatCog
    from services.combat_service import CombatState


# (action_suffix, label, emoji, row)
_ITEM_DEFS = [
    ("medkit",        "急救包",    "🩹", 2),
    ("energy",        "能量電池",  "🔋", 2),
    ("stimulant",     "興奮劑",    "💉", 2),
    ("nano_repair",   "奈米修復劑","🧬", 2),
    ("adrenaline",    "腎上腺素",  "💊", 3),
    ("shield_chip",   "護盾晶片",  "🔰", 3),
    ("corrosive_vial","腐蝕瓶",    "🧪", 3),
    ("emp_grenade",   "EMP手雷",   "⚡", 3),
]


def _item_count(state: CombatState, action: str) -> int:
    if action == "medkit":
        return state.medkits
    if action == "energy":
        return state.energy_cells_in_combat
    return state.consumables_in_combat.get(action, 0)


class ItemButton(discord.ui.Button):
    def __init__(
        self,
        cog: CombatCog,
        character_id: int,
        action: str,
        label: str,
        emoji: str,
        count: int,
        row: int,
    ) -> None:
        super().__init__(
            label=f"{label} ×{count}",
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            disabled=count <= 0,
            row=row,
        )
        self.cog          = cog
        self.character_id = character_id
        self.action       = action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, f"item_{self.action}")


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

        # ── Rows 2–3: item buttons (data-driven) ─────────────────
        for action, label, emoji, row in _ITEM_DEFS:
            count = _item_count(state, action)
            self.add_item(ItemButton(cog, character_id, action, label, emoji, count, row))

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
