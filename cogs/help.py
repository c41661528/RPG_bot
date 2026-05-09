import discord
from discord.ext import bridge, commands

from utils.embeds import C_DARK, C_INFO


# ── 新手入門須知（精簡版）─────────────────────────────────────

def _guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌅  廢土新手入門須知",
        description=(
            "歡迎來到廢土！這裡是基本生存指南，照著做就能上手。\n"
            "_所有指令支援 `/` 或 `!` 前綴，例如 `/fight` = `!fight`_"
        ),
        color=C_INFO,
    )

    embed.add_field(
        name="① 建立角色",
        value="`start` — 選職業、取名，從這裡開始你的廢土生涯。",
        inline=False,
    )

    embed.add_field(
        name="② 戰鬥賺取資源",
        value=(
            "`fight` — 與敵人戰鬥取得 EXP、信用點、裝備\n"
            "`explore` — 在當前地點搜刮物資\n"
            "`rest` — HP 不足時花 50💰 完全恢復"
        ),
        inline=False,
    )

    embed.add_field(
        name="③ 管理裝備",
        value=(
            "`inventory` — 查看背包、裝備武器/護甲/頭盔/配件\n"
            "`shop` / `buy` — 買急救包、能量電池等補給"
        ),
        inline=False,
    )

    embed.add_field(
        name="④ 升級成長",
        value=(
            "`profile` — 查看你的角色狀態\n"
            "`allocate` — 升級獲得屬性點，分配給體力/反應/科技\n"
            "`quest` — 完成每日任務領 EXP 獎勵"
        ),
        inline=False,
    )

    embed.add_field(
        name="💡  進階功能",
        value=(
            "強化、鍛造、迷宮、PvP決鬥、稱號、週常任務、成就⋯⋯\n"
            "全部指令請輸入 **`!rpg_help`** 查看。"
        ),
        inline=False,
    )

    embed.add_field(
        name="⏳  戰鬥冷卻",
        value=(
            "戰鬥結束後有 **10 秒義體冷卻**才能再次 `/fight`。\n"
            "這段時間正好可以查看 `/profile`、`/inventory`，或先去 `/quest` 領獎勵。"
        ),
        inline=False,
    )

    embed.set_footer(text="先 /start 建角色 → /fight 開打 → /inventory 裝備 → /rest 回血")
    return embed


# ── 完整指令列表 ─────────────────────────────────────────────

def _full_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📡  廢土指令手冊",
        description="所有指令都支援 `/` 或 `!` 前綴，例：`/fight` 或 `!fight`",
        color=C_DARK,
    )

    embed.add_field(
        name="🌟  新手必看",
        value=(
            "`start` 建角色　`profile` 看狀態　`fight` 戰鬥\n"
            "`explore` 探索　`inventory` 背包　`rest` 休息回血"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚔️  戰鬥 & 探索",
        value=(
            "`fight` 戰鬥　`explore` 探索掉寶\n"
            "`travel` 移動地點　`dungeon` 5 層迷宮"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎒  裝備 & 商店",
        value=(
            "`inventory` 背包　`unequip` 卸裝　`sell` 賣裝備\n"
            "`shop` 道具行　`buy` 買道具\n"
            "`gear_shop` 裝備行　`buy_gear` 買裝備\n"
            "`mat_shop` 材料行　`buy_material` 買材料\n"
            "`enhance` 強化（+1~+5，可用材料提升成功率）\n"
            "`craft` 鍛造工坊（升階／重鑄裝備）"
        ),
        inline=False,
    )

    embed.add_field(
        name="📋  任務 & 成就",
        value=(
            "`quest` 每日任務　`weekly_quest` 週常任務\n"
            "`achievements` 成就（16 個）　`titles` 稱號（17 個，部分加成）"
        ),
        inline=False,
    )

    embed.add_field(
        name="🥊  PvP 決鬥",
        value=(
            "`duel @玩家` 向人發起決鬥（自動戰鬥，套用裝備+稱號）\n"
            "`pvp_stats` 查看戰績\n"
            "每日上限 5 場、間隔 30 分鐘，勝者奪 5% 信用點（最多 1000）"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎯  隊伍",
        value=(
            "`party_form` 建立隊伍（你是隊長）\n"
            "`party_invite @玩家` 邀請朋友（最多 4 人）\n"
            "`party_status` 查看隊伍狀態　`party_leave` 離開\n"
            "面板按 [出發迷宮] 進隊伍迷宮（敵人HP×N、獎勵每人×1.5）"
        ),
        inline=False,
    )

    embed.add_field(
        name="📈  成長",
        value=(
            "`allocate` 配屬性點　`rank` 排行榜\n"
            "`rebirth` 轉生（Lv.50 後，最多 5 次）"
        ),
        inline=False,
    )

    embed.add_field(
        name="💡  小提醒",
        value=(
            "• 戰鬥中：⚔️攻擊　🛡️防禦　🏃逃跑　💠技能選單　🎒道具選單\n"
            "• 武器+ATK　護甲/頭盔+DEF　配件+能量/暴擊\n"
            "• 強化跟著「那件裝備」走，賣了會清掉\n"
            "• 稱號可在 `titles` 切換，部分提供 ATK/DEF/信用點%等加成\n"
            "• 戰鬥結束後有 **10 秒義體冷卻**才能再開戰"
        ),
        inline=False,
    )

    embed.set_footer(text="新手提示：先 /start 建角色，再 /fight 開打")
    return embed


# ── Cog ──────────────────────────────────────────────────────

class HelpCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="guide", description="🌅 新手入門須知（基礎指令）")
    async def guide(self, ctx: discord.ApplicationContext) -> None:
        await ctx.respond(embed=_guide_embed(), ephemeral=True)

    @bridge.bridge_command(name="rpg_help", description="📡 完整指令手冊")
    async def rpg_help(self, ctx: discord.ApplicationContext) -> None:
        await ctx.respond(embed=_full_help_embed(), ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(HelpCog(bot))
