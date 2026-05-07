import discord
from discord.ext import commands

from utils.embeds import C_DARK, C_INFO


def _help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📡  廢土生存手冊  v3.0",
        description="歡迎來到廢土。以下是所有可用指令。",
        color=C_DARK,
    )

    embed.add_field(
        name="👤  角色",
        value=(
            "`/start` 　　建立你的廢土角色\n"
            "`/profile` 　查看角色狀態面板\n"
            "`/allocate` 　分配升級獲得的屬性點\n"
            "`/rest` 　　 花費 **50** 💰 完全恢復 HP 與能量"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚔️  戰鬥",
        value=(
            "`/fight` 　　在當前地點遭遇並挑戰敵人\n"
            "　⚔️ 攻擊（連擊累積傷害+10%/層）\n"
            "　🛡️ 防禦（-70%傷害+反擊，消耗能量）\n"
            "　💠 技能選單（3個職業技能）\n"
            "　🩹 急救包　🔋 能量電池　🏃 逃跑"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎒  裝備 & 道具",
        value=(
            "`/inventory` 　查看背包與裝備欄（武器/護甲/頭盔/配件）\n"
            "`/unequip` 　 卸下任意欄位裝備\n"
            "`/sell` 　　　出售背包中的裝備換取信用點\n"
            "`/shop` 　　 查看黑市商品（急救包/能量電池）\n"
            "`/buy` 　　　購買急救包或能量電池"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔧  裝備行 & 材料行",
        value=(
            "`/gear_shop` 　　查看黑市裝備行（等級縮放隨機裝備，共 6 件）\n"
            "`/buy_gear` 　　購買裝備行中的裝備（輸入編號 1–6）\n"
            "`/mat_shop` 　　查看強化材料行與價格\n"
            "`/buy_material` 購買強化材料（廢棄金屬／電路板／能量核心／奈米纖維／量子晶片）"
        ),
        inline=False,
    )

    embed.add_field(
        name="🗺️  探索",
        value=(
            "`/explore` 　在當前地點搜刮物資（寶箱 / 陷阱 / 補給 / 裝備）\n"
            "`/travel` 　 移動到其他地點\n\n"
            "**地點解鎖：** 🏚️ 廢墟東區 Lv.1　🏭 工業廢墟 Lv.3　🏢 企業廢棄總部 Lv.5　🌑 深層地下道 Lv.8"
        ),
        inline=False,
    )

    embed.add_field(
        name="🗺️  迷宮",
        value=(
            "`/dungeon` 　挑戰 5 層迷宮（自動戰鬥），第 5 層為 Boss\n"
            "　層層通關或隨時撤退，通關獎勵豐厚\n"
            "　廢棄工廠 Lv.1　企業伺服器室 Lv.5　地下競技場 Lv.8"
        ),
        inline=False,
    )

    embed.add_field(
        name="📋  任務",
        value=(
            "`/quest` 　　　每日任務（3個，依等級縮放，每日 0 點重置）\n"
            "`/weekly_quest`  週常任務（3個，更高獎勵，每週一重置）\n"
            "　　　　　完成後點擊「領取獎勵」獲得 EXP + 信用點"
        ),
        inline=False,
    )

    embed.add_field(
        name="🏆  排行 & 成長",
        value=(
            "`/rank` 　　 查看等級 / 擊殺數 / 信用點排行榜\n"
            "`/rebirth` 　Lv.50 後轉生，重置等級並獲得永久屬性加成（最多 5 次）\n"
            "`/achievements` 查看成就進度（16 個成就）\n"
            "`/titles` 　 查看與裝備稱號（17 個稱號，部分提供加成）"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚔️  PvP 決鬥",
        value=(
            "`/duel @玩家` 　向其他玩家發起決鬥（自動戰鬥，套用裝備＋稱號）\n"
            "`/pvp_stats` 　查看勝率與今日決鬥次數\n"
            "　每日上限 5 場、間隔 30 分鐘；勝者奪取 5% 對方信用點 (上限 1000)"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔨  強化 & 鍛造",
        value=(
            "`/enhance` 　強化已裝備的武器/護甲/頭盔/配件，每級 +2\n"
            f"　　　　　選擇材料可提升成功率（最高 +{25}%），最高強化 +5\n"
            "`/craft` 　　鍛造工坊：升階（3件→1件）、重鑄（重新滾屬性）"
        ),
        inline=False,
    )

    embed.add_field(
        name="💠  職業技能（各 3 個，從技能選單選擇）",
        value=(
            "⚔️ **街頭武士**　🗡️ 暴怒斬(2×傷害)　🛡️ 鐵壁防禦(-70%+反擊)　⚡ 義體超載(ATK×1.5/3回)\n"
            "💻 **竄網使**　　💀 神經駭入(傷害+癱瘓)　🦠 病毒植入(中毒3回)　🔌 電磁爆(1.5×+感電)\n"
            "🗡️ **拾荒者**　　⚡ 速攻連擊(雙段)　💨 煙霧彈(閃避+逃跑95%)　🗡️ 毒刃(傷害+中毒3回)"
        ),
        inline=False,
    )

    embed.add_field(
        name="🧪  材料",
        value=(
            "打怪有機率掉落材料（🔩🖥️🔋🧵💎）\n"
            "在 `/enhance` 選擇材料使用，提升強化成功率 +5%～+25%"
        ),
        inline=False,
    )

    embed.set_footer(text="裝備武器↑ATK · 護甲↑DEF · 頭盔↑DEF+HP · 配件↑能量+暴擊率")
    return embed


class HelpCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @discord.slash_command(name="rpg_help", description="📡 查看所有可用指令")
    async def rpg_help(self, ctx: discord.ApplicationContext) -> None:
        await ctx.respond(embed=_help_embed(), ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(HelpCog(bot))
