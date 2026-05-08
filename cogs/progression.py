import discord
from discord.ext import bridge, commands
from sqlalchemy import select, func, desc

from config import (
    CLASS_BASE_STATS,
    CLASS_DISPLAY,
    MAX_REBIRTH,
    REBIRTH_REQUIRED_LEVEL,
    REBIRTH_STAT_BONUS,
)
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from utils.embeds import (
    C_DANGER,
    C_INFO,
    C_MYTHIC,
    C_PRIMARY,
    C_WARNING,
    error_embed,
    success_embed,
)

# ── Rank medals ──────────────────────────────────────────────────
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# ── Rank sorting choices ─────────────────────────────────────────
_SORT_COLS = {
    "等級":   (Character.level,   Character.kills),
    "擊殺數": (Character.kills,   Character.level),
    "信用點": (Character.credits, Character.level),
}


async def _fetch_leaderboard(sort_by: str) -> list[Character]:
    primary, secondary = _SORT_COLS[sort_by]
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Character)
            .order_by(desc(primary), desc(secondary))
            .limit(10)
        )
        return result.scalars().all()


async def _fetch_my_rank(char_id: int, sort_by: str) -> tuple[int, Character | None]:
    """Returns (rank, character). rank is 1-based."""
    primary, _ = _SORT_COLS[sort_by]
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Character).where(Character.id == char_id))
        me = result.scalar_one_or_none()
        if not me:
            return 0, None
        count_result = await session.execute(
            select(func.count()).select_from(Character).where(primary > getattr(me, primary.key))
        )
        rank = count_result.scalar() + 1
        return rank, me


def _rank_embed(top: list[Character], sort_by: str, my_rank: int, me: Character | None) -> discord.Embed:
    col_label = {"等級": "Lv.", "擊殺數": "擊殺", "信用點": "💰"}[sort_by]
    col_key   = {"等級": "level", "擊殺數": "kills", "信用點": "credits"}[sort_by]

    lines: list[str] = []
    for i, char in enumerate(top, 1):
        medal   = _MEDALS.get(i, f"`{i:>2}.`")
        val     = getattr(char, col_key)
        display = f"{val:,}" if col_key == "credits" else str(val)
        rb_mark = f" ✨×{char.rebirth_count}" if char.rebirth_count > 0 else ""
        class_e = CLASS_DISPLAY[char.class_type.value]["emoji"]
        lines.append(f"{medal}  {class_e} **{char.name}**{rb_mark}  —  {col_label}{display}")

    embed = discord.Embed(
        title=f"🏆  廢土排行榜  ─  {sort_by} Top 10",
        description="\n".join(lines) or "（尚無紀錄）",
        color=C_MYTHIC,
    )
    if me:
        rb_mark = f" ✨×{me.rebirth_count}" if me.rebirth_count > 0 else ""
        embed.set_footer(text=f"你的排名：第 {my_rank} 名  │  {me.name}{rb_mark}")
    return embed


# ── Rebirth confirm view ─────────────────────────────────────────

class RebirthView(discord.ui.View):
    def __init__(self, char: Character) -> None:
        super().__init__(timeout=60)
        self.char_id         = char.id
        self.discord_user_id = None   # set by cog after creation

    @discord.ui.button(label="確認轉生", emoji="✨", style=discord.ButtonStyle.danger)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

            if char.level < REBIRTH_REQUIRED_LEVEL:
                return await interaction.response.send_message(
                    embed=error_embed(f"需要達到 Lv.{REBIRTH_REQUIRED_LEVEL} 才能轉生。"),
                    ephemeral=True,
                )
            if char.rebirth_count >= MAX_REBIRTH:
                return await interaction.response.send_message(
                    embed=error_embed(f"已達最大轉生次數（{MAX_REBIRTH} 次）。"),
                    ephemeral=True,
                )

            # Build new rebirth_bonus
            old_rb  = dict(char.rebirth_bonus or {})
            new_rb  = {
                "vitality": old_rb.get("vitality", 0) + REBIRTH_STAT_BONUS,
                "reflex":   old_rb.get("reflex",   0) + REBIRTH_STAT_BONUS,
                "tech":     old_rb.get("tech",     0) + REBIRTH_STAT_BONUS,
            }
            stats   = CLASS_BASE_STATS[char.class_type.value]
            new_count = char.rebirth_count + 1

            char.rebirth_count    = new_count
            char.rebirth_bonus    = new_rb
            char.level            = 1
            char.exp              = 0
            char.stat_points_avail = 0
            char.stat_vitality    = stats["vitality"] + new_rb["vitality"]
            char.stat_reflex      = stats["reflex"]   + new_rb["reflex"]
            char.stat_tech        = stats["tech"]      + new_rb["tech"]
            char.hp_max           = stats["hp"]        + new_rb["vitality"] * 8
            char.energy_max       = stats["energy"]
            char.hp_current       = char.hp_max
            char.energy_current   = char.energy_max
            await session.commit()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=_rebirth_success_embed(char, new_count, new_rb),
            view=self,
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(description="✖  轉生已取消。", color=C_WARNING),
            view=self,
        )


def _rebirth_confirm_embed(char: Character) -> discord.Embed:
    old_rb   = dict(char.rebirth_bonus or {})
    new_vit  = old_rb.get("vitality", 0) + REBIRTH_STAT_BONUS
    new_ref  = old_rb.get("reflex",   0) + REBIRTH_STAT_BONUS
    new_tec  = old_rb.get("tech",     0) + REBIRTH_STAT_BONUS
    stats    = CLASS_BASE_STATS[char.class_type.value]
    new_hp   = stats["hp"] + new_vit * 8
    new_cnt  = char.rebirth_count + 1

    desc = (
        f"⚠️  **這個操作無法復原。**\n\n"
        f"**失去的：**\n"
        f"> 等級重置為 1，EXP 歸零，屬性點歸零\n\n"
        f"**保留的：**\n"
        f"> 信用點、背包、裝備、擊殺數\n\n"
        f"**永久獲得（第 {new_cnt} 次轉生加成）：**\n"
        f"> 💪 體力 **+{REBIRTH_STAT_BONUS}**（共 +{new_vit}）\n"
        f"> ⚡ 反應神經 **+{REBIRTH_STAT_BONUS}**（共 +{new_ref}）\n"
        f"> 🔧 科技力 **+{REBIRTH_STAT_BONUS}**（共 +{new_tec}）\n"
        f"> ❤️ HP 上限重置為 **{new_hp}**\n\n"
        f"剩餘轉生次數：**{MAX_REBIRTH - new_cnt}** 次"
    )
    return discord.Embed(
        title=f"✨  轉生確認  —  {char.name}  第 {new_cnt} 次",
        description=desc,
        color=C_DANGER,
    )


def _rebirth_success_embed(char: Character, new_count: int, new_rb: dict) -> discord.Embed:
    return discord.Embed(
        title=f"✨  轉生完成！第 {new_count} 次轉生",
        description=(
            f"**{char.name}** 的意識在廢土網路中完成了一次深層重組。\n\n"
            f"永久加成累計：\n"
            f"> 💪 體力 **+{new_rb['vitality']}**　"
            f"⚡ 反應神經 **+{new_rb['reflex']}**　"
            f"🔧 科技力 **+{new_rb['tech']}**\n\n"
            f"使用 `/profile` 查看新狀態。"
        ),
        color=C_MYTHIC,
    )


# ── Cog ──────────────────────────────────────────────────────────

class ProgressionCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="rank", description="🏆 查看廢土排行榜")
    async def rank(
        self,
        ctx: discord.ApplicationContext,
        sort_by: discord.Option(
            str,
            description="排序依據",
            choices=["等級", "擊殺數", "信用點"],
            default="等級",
        ),
    ) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            me = result.scalar_one_or_none()

        top       = await _fetch_leaderboard(sort_by)
        my_rank, me_full = await _fetch_my_rank(me.id if me else -1, sort_by)

        await ctx.respond(embed=_rank_embed(top, sort_by, my_rank, me_full))

    @bridge.bridge_command(name="rebirth", description="✨ 轉生重置（需 Lv.50，最多 5 次）")
    async def rebirth(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)
        if char.is_in_combat:
            return await ctx.respond(embed=error_embed("無法在戰鬥中轉生！"), ephemeral=True)
        if char.level < REBIRTH_REQUIRED_LEVEL:
            return await ctx.respond(
                embed=error_embed(
                    f"需要達到 **Lv.{REBIRTH_REQUIRED_LEVEL}** 才能轉生。\n"
                    f"（目前 Lv.{char.level}）"
                ),
                ephemeral=True,
            )
        if char.rebirth_count >= MAX_REBIRTH:
            return await ctx.respond(
                embed=error_embed(f"已達最大轉生次數（{MAX_REBIRTH} 次），無法再轉生。"),
                ephemeral=True,
            )

        view = RebirthView(char)
        view.discord_user_id = ctx.author.id
        await ctx.respond(embed=_rebirth_confirm_embed(char), view=view, ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ProgressionCog(bot))
