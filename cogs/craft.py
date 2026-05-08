from __future__ import annotations

import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.craft_service import (
    REFORGE_COSTS, UPGRADE_COSTS,
    get_inventory_by_slot_tier, perform_reforge, perform_upgrade,
)
from services.equipment_service import all_materials, get_item, get_material, item_slot
from services.title_service import check_title_unlocks
from utils.embeds import C_INFO, C_PRIMARY, error_embed


_RARITY = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣"}
_CI_PREFIXES = ("ci_w_", "ci_a_", "ci_h_", "ci_ac_")


def _fmt_cost(cost: dict[str, int]) -> str:
    parts = [f"{cost.get('credits', 0):,}💰"]
    for k, v in cost.items():
        if k == "credits":
            continue
        m = get_material(k)
        parts.append(f"{m['emoji']}×{v}" if m else f"{k}×{v}")
    return " ".join(parts)


def _craft_main_embed(char: Character) -> discord.Embed:
    mats_owned = char.materials or {}
    mat_lines: list[str] = []
    for m in all_materials():
        qty = mats_owned.get(m["id"], 0)
        if qty > 0:
            mat_lines.append(f"{m['emoji']} {m['name']} ×{qty}")
    mat_text = "　".join(mat_lines) if mat_lines else "`無材料`"

    embed = discord.Embed(
        title="🔨  鍛造工坊",
        description=(
            f"💰 信用點：**{char.credits:,}**\n"
            f"🧪 材料：{mat_text}\n\n"
            "▸ **升階**：消耗 3 件同槽位同階裝備 + 材料 → 隨機產出高一階裝備\n"
            "▸ **重鑄**：消耗 1 件商店/合成裝備 + 材料 → 重新產生同階屬性"
        ),
        color=C_INFO,
    )
    embed.set_footer(text="基礎裝備（非商店產出）僅可作為升階素材，不可重鑄")
    return embed


# ── Upgrade flow ─────────────────────────────────────────────────

class _UpgradeSelect(discord.ui.Select):
    def __init__(self, char: Character) -> None:
        self.char_id = char.id
        by = get_inventory_by_slot_tier(char)
        opts: list[discord.SelectOption] = []
        for (slot, tier), ids in sorted(by.items()):
            if len(ids) >= 3 and tier < 4:
                cost = UPGRADE_COSTS.get(tier, {})
                opts.append(discord.SelectOption(
                    label=f"{slot} T{tier} ×3 → T{tier + 1} 隨機",
                    value=f"{slot}|{tier}",
                    description=f"花費 {_fmt_cost(cost)}",
                ))
        if not opts:
            opts = [discord.SelectOption(label="無可升階組合", value="__none__")]
        super().__init__(placeholder="選擇升階組合…", options=opts)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: _UpgradeView = self.view  # type: ignore[assignment]
        if interaction.user.id != view.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        val = self.values[0]
        if val == "__none__":
            return await interaction.response.send_message("沒有可升階的組合。", ephemeral=True)
        slot, tier_s = val.split("|")
        tier = int(tier_s)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char = result.scalar_one()
            ok, new_stats, msg = perform_upgrade(char, slot, tier)
            new_titles: list[str] = []
            if ok:
                new_titles = check_title_unlocks(char, discord_id=view.discord_user_id)
            await session.commit()
            await session.refresh(char)

        if not ok:
            await interaction.response.edit_message(
                embed=_craft_main_embed(char),
                view=CraftMainView(char, view.discord_user_id),
            )
            return await interaction.followup.send(embed=error_embed(msg), ephemeral=True)

        title_txt = ("\n\n🎖️ 解鎖稱號：" + "、".join(new_titles)) if new_titles else ""
        embed = discord.Embed(
            title="✅  升階成功！",
            description=(
                f"消耗 3 件 {slot} T{tier} 裝備\n\n"
                f"獲得：{_RARITY[tier + 1]} {new_stats['emoji']} **{new_stats['name']}**\n"
                f"屬性：{new_stats.get('desc', '')}"
                f"{title_txt}"
            ),
            color=C_PRIMARY,
        )
        await interaction.response.edit_message(
            embed=embed,
            view=CraftMainView(char, view.discord_user_id),
        )


class _UpgradeView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.char_id = char.id
        self.discord_user_id = discord_user_id
        self.add_item(_UpgradeSelect(char))

    @discord.ui.button(label="↩ 返回", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char = result.scalar_one()
        await interaction.response.edit_message(
            embed=_craft_main_embed(char),
            view=CraftMainView(char, self.discord_user_id),
        )


# ── Reforge flow ─────────────────────────────────────────────────

class _ReforgeSelect(discord.ui.Select):
    def __init__(self, char: Character) -> None:
        self.char_id = char.id
        ci  = char.custom_items or {}
        opts: list[discord.SelectOption] = []
        seen: set[str] = set()
        for iid in (char.inventory or []):
            if iid in seen or len(opts) >= 25:
                continue
            seen.add(iid)
            if not iid.startswith(_CI_PREFIXES):
                continue
            it = get_item(iid, ci)
            if not it:
                continue
            tier = it.get("tier", 1)
            cost = REFORGE_COSTS.get(tier, {})
            opts.append(discord.SelectOption(
                label=f"{it['name']}  T{tier}",
                value=iid,
                emoji=it["emoji"],
                description=f"{item_slot(iid)} · {_fmt_cost(cost)}",
            ))
        if not opts:
            opts = [discord.SelectOption(label="無可重鑄裝備", value="__none__")]
        super().__init__(placeholder="選擇要重鑄的裝備…", options=opts)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: _ReforgeView = self.view  # type: ignore[assignment]
        if interaction.user.id != view.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        iid = self.values[0]
        if iid == "__none__":
            return await interaction.response.send_message("沒有可重鑄裝備。", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char = result.scalar_one()
            ok, new_stats, old, msg = perform_reforge(char, iid)
            new_titles: list[str] = []
            if ok:
                new_titles = check_title_unlocks(char, discord_id=view.discord_user_id)
            await session.commit()
            await session.refresh(char)

        if not ok:
            await interaction.response.edit_message(
                embed=_craft_main_embed(char),
                view=CraftMainView(char, view.discord_user_id),
            )
            return await interaction.followup.send(embed=error_embed(msg), ephemeral=True)

        title_txt = ("\n\n🎖️ 解鎖稱號：" + "、".join(new_titles)) if new_titles else ""
        embed = discord.Embed(
            title="✅  重鑄成功！",
            description=(
                f"原屬性：{old.get('desc', '')}\n"
                f"新屬性：{new_stats.get('desc', '')}"
                f"{title_txt}"
            ),
            color=C_PRIMARY,
        )
        await interaction.response.edit_message(
            embed=embed,
            view=CraftMainView(char, view.discord_user_id),
        )


class _ReforgeView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.char_id = char.id
        self.discord_user_id = discord_user_id
        self.add_item(_ReforgeSelect(char))

    @discord.ui.button(label="↩ 返回", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char = result.scalar_one()
        await interaction.response.edit_message(
            embed=_craft_main_embed(char),
            view=CraftMainView(char, self.discord_user_id),
        )


# ── Main view ────────────────────────────────────────────────────

class CraftMainView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.char_id = char.id
        self.discord_user_id = discord_user_id

    @discord.ui.button(label="升階裝備", emoji="⬆️", style=discord.ButtonStyle.primary, row=0)
    async def upgrade(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char = result.scalar_one()
        await interaction.response.edit_message(
            embed=_craft_main_embed(char),
            view=_UpgradeView(char, self.discord_user_id),
        )

    @discord.ui.button(label="重鑄裝備", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def reforge(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char = result.scalar_one()
        await interaction.response.edit_message(
            embed=_craft_main_embed(char),
            view=_ReforgeView(char, self.discord_user_id),
        )


# ── Cog ──────────────────────────────────────────────────────────

class CraftCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="craft", description="🔨 鍛造工坊：升階或重鑄裝備")
    async def craft(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()
        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。"), ephemeral=True)
        if char.is_in_combat:
            return await ctx.respond(embed=error_embed("無法在戰鬥中合成。"), ephemeral=True)
        await ctx.respond(
            embed=_craft_main_embed(char),
            view=CraftMainView(char, ctx.author.id),
            ephemeral=True,
        )


def setup(bot: discord.Bot) -> None:
    bot.add_cog(CraftCog(bot))
