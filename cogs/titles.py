from __future__ import annotations

import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.title_service import (
    all_titles, check_title_unlocks, equipped_title_data,
    get_title, is_unlocked, rarity_emoji,
)
from utils.embeds import C_INFO, error_embed, success_embed


def _format_bonuses(b: dict) -> str:
    if not b:
        return "無數值加成"
    parts: list[str] = []
    if b.get("atk_pct"):              parts.append(f"ATK +{int(b['atk_pct']*100)}%")
    if b.get("def_pct"):              parts.append(f"DEF +{int(b['def_pct']*100)}%")
    if b.get("hp_pct"):               parts.append(f"HP +{int(b['hp_pct']*100)}%")
    if b.get("crit_bonus"):           parts.append(f"暴擊 +{int(b['crit_bonus']*100)}%")
    if b.get("credits_pct"):          parts.append(f"信用點 +{int(b['credits_pct']*100)}%")
    if b.get("exp_pct"):              parts.append(f"EXP +{int(b['exp_pct']*100)}%")
    if b.get("dungeon_reward_pct"):   parts.append(f"迷宮獎勵 +{int(b['dungeon_reward_pct']*100)}%")
    if b.get("craft_success_pct"):    parts.append(f"合成成功 +{int(b['craft_success_pct']*100)}%")
    return "  ".join(parts) if parts else "無數值加成"


def _titles_embed(char: Character) -> discord.Embed:
    titles = all_titles()
    cur = char.equipped_title or "wasteland_rookie"

    unlocked = [t for t in titles if is_unlocked(char, t["id"])]
    locked   = [t for t in titles if not is_unlocked(char, t["id"])]

    unlocked_lines: list[str] = []
    for t in unlocked:
        marker = "🟢" if t["id"] == cur else "  "
        bonus  = _format_bonuses(t.get("bonuses", {}))
        unlocked_lines.append(
            f"{marker} {rarity_emoji(t['rarity'])} {t['emoji']} **{t['name']}**\n"
            f"　　{t['desc']}\n"
            f"　　`{bonus}`"
        )
    locked_lines = [
        f"🔒 {rarity_emoji(t['rarity'])} ~~{t['name']}~~　{t['desc']}"
        for t in locked
    ]

    cur_t = equipped_title_data(char)
    cur_str = f"{rarity_emoji(cur_t['rarity'])} {cur_t['emoji']} **{cur_t['name']}**"

    embed = discord.Embed(
        title=f"🎖️  稱號  —  {char.name}",
        description=(
            f"已解鎖 **{len(unlocked)}/{len(titles)}** 個稱號\n"
            f"目前裝備：{cur_str}"
        ),
        color=C_INFO,
    )
    if unlocked_lines:
        embed.add_field(
            name="✅ 已解鎖（從下方選單裝備）",
            value="\n".join(unlocked_lines[:12]),
            inline=False,
        )
    if locked_lines:
        embed.add_field(
            name="🔒 未解鎖",
            value="\n".join(locked_lines[:12]),
            inline=False,
        )
    embed.set_footer(text="裝備稱號可獲得對應加成 · 部分稱號隨等級/擊殺/轉生自動解鎖")
    return embed


class TitleSelect(discord.ui.Select):
    def __init__(self, char: Character) -> None:
        self.char_id = char.id
        cur          = char.equipped_title or "wasteland_rookie"
        opts: list[discord.SelectOption] = []
        for t in all_titles():
            if not is_unlocked(char, t["id"]) or len(opts) >= 25:
                continue
            opts.append(discord.SelectOption(
                label=f"{t['name']}  [{rarity_emoji(t['rarity'])}]",
                value=t["id"],
                emoji=t["emoji"],
                description=t["desc"][:50],
                default=(t["id"] == cur),
            ))
        if not opts:
            opts = [discord.SelectOption(label="尚無已解鎖稱號", value="__none__")]
        super().__init__(
            placeholder="選擇要裝備的稱號…",
            options=opts,
            min_values=1, max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: TitleView = self.view  # type: ignore[assignment]
        if interaction.user.id != view.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        title_id = self.values[0]
        if title_id == "__none__":
            return await interaction.response.send_message("尚無可裝備稱號。", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()
            if not is_unlocked(char, title_id):
                return await interaction.response.send_message("該稱號尚未解鎖。", ephemeral=True)
            char.equipped_title = title_id
            await session.commit()
            await session.refresh(char)

        t = get_title(title_id)
        await interaction.response.edit_message(
            embed=_titles_embed(char),
            view=TitleView(char, view.discord_user_id),
        )
        await interaction.followup.send(
            embed=success_embed(f"已裝備稱號 {t['emoji']} **{t['name']}**！"),
            ephemeral=True,
        )


class TitleView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.discord_user_id = discord_user_id
        self.add_item(TitleSelect(char))


class TitlesCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="titles", description="🎖️ 查看與裝備稱號")
    async def titles(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()
            if char is None:
                return await ctx.respond(
                    embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True,
                )
            new_unlocks = check_title_unlocks(char)
            await session.commit()
            await session.refresh(char)

        embed = _titles_embed(char)
        if new_unlocks:
            embed.description += f"\n\n🎉 新解鎖：" + "、".join(new_unlocks)
        await ctx.respond(embed=embed, view=TitleView(char, ctx.author.id), ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(TitlesCog(bot))
