from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import CLASS_SKILLS, DEFEND_ENERGY_COST

if TYPE_CHECKING:
    from cogs.combat import CombatCog
    from services.combat_service import CombatState


class SkillSelect(discord.ui.Select):
    """Dropdown that shows all 3 class skills; selecting one fires the turn."""

    def __init__(self, cog: CombatCog, character_id: int, state: CombatState) -> None:
        self.cog          = cog
        self.character_id = character_id

        skills  = CLASS_SKILLS[state.char_class]
        options: list[discord.SelectOption] = []

        for skill in skills:
            can_afford = state.energy >= skill["energy_cost"]
            label = f"{skill['name']}  ({skill['energy_cost']} 能量)"
            desc  = skill["desc"][:50]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=skill["id"],
                    emoji=skill["emoji"],
                    description=desc,
                    default=False,
                )
            )

        super().__init__(
            placeholder="💠 選擇技能...",
            options=options,
            min_values=1,
            max_values=1,
            row=1,
        )
        # Disable the whole select only if all skills are too expensive
        self.disabled = not any(state.energy >= s["energy_cost"] for s in skills)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, f"skill_{self.values[0]}")


class CombatView(discord.ui.View):
    def __init__(self, cog: CombatCog, character_id: int, state: CombatState) -> None:
        super().__init__(timeout=120)
        self.cog          = cog
        self.character_id = character_id

        # ── Skill select (row 1) ──────────────────────────────────
        self.add_item(SkillSelect(cog, character_id, state))

        # Decorator buttons land in children[0..4]: attack, defend, flee, medkit, energy_cell
        # SkillSelect is appended as children[5] by add_item above.
        can_defend = state.energy >= DEFEND_ENERGY_COST
        self.children[1].disabled = not can_defend  # defend btn

        mk = state.medkits
        self.children[3].label    = f"急救包 ×{mk}"
        self.children[3].disabled = mk <= 0

        ec = state.energy_cells_in_combat
        self.children[4].label    = f"能量電池 ×{ec}"
        self.children[4].disabled = ec <= 0

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

    # ── Row 2 ────────────────────────────────────────────────────

    @discord.ui.button(label="急救包 ×0", emoji="🩹", style=discord.ButtonStyle.secondary, row=2)
    async def medkit(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, "item_medkit")

    @discord.ui.button(label="能量電池 ×0", emoji="🔋", style=discord.ButtonStyle.secondary, row=2)
    async def energy_cell(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self.cog.process_turn(interaction, self.character_id, "item_energy")

    # ── Timeout ──────────────────────────────────────────────────

    async def on_timeout(self) -> None:
        await self.cog.handle_timeout(self.character_id)
