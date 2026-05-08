import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from config import CLASS_BASE_STATS, CLASS_DISPLAY, STARTING_CREDITS, STARTING_LOCATION
from database.session import AsyncSessionFactory
from models.character import Character, ClassType
from models.player import Player
from utils.embeds import (
    allocate_embed,
    character_profile_embed,
    class_select_embed,
    error_embed,
    success_embed,
)


class AllocateView(discord.ui.View):
    def __init__(self, character_id: int, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.character_id    = character_id
        self.discord_user_id = discord_user_id

    async def _allocate(self, interaction: discord.Interaction, stat: str) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character).where(Character.id == self.character_id)
            )
            char = result.scalar_one()

            if char.stat_points_avail <= 0:
                for child in self.children:
                    child.disabled = True
                return await interaction.response.edit_message(view=self)

            if stat == "vitality":
                char.stat_vitality      += 1
                char.hp_max             += 8   # vitality physically expands HP pool
            elif stat == "reflex":
                char.stat_reflex        += 1
            else:
                char.stat_tech          += 1

            char.stat_points_avail -= 1
            await session.commit()
            await session.refresh(char)

        if char.stat_points_avail <= 0:
            for child in self.children:
                child.disabled = True

        await interaction.response.edit_message(embed=allocate_embed(char), view=self)

    @discord.ui.button(label="+ 體力", emoji="💪", style=discord.ButtonStyle.primary)
    async def add_vitality(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._allocate(interaction, "vitality")

    @discord.ui.button(label="+ 反應神經", emoji="⚡", style=discord.ButtonStyle.primary)
    async def add_reflex(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._allocate(interaction, "reflex")

    @discord.ui.button(label="+ 科技力", emoji="🔧", style=discord.ButtonStyle.primary)
    async def add_tech(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._allocate(interaction, "tech")


class CharacterNameModal(discord.ui.Modal):
    def __init__(self, player_id: int, class_type: str) -> None:
        super().__init__(title="▸ 輸入你的識別代號")
        self.player_id = player_id
        self.class_type = class_type
        self.add_item(
            discord.ui.InputText(
                label="識別代號（角色名稱）",
                placeholder="2 ~ 16 個字元",
                min_length=2,
                max_length=16,
            )
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        name = self.children[0].value.strip()
        stats = CLASS_BASE_STATS[self.class_type]
        class_info = CLASS_DISPLAY[self.class_type]

        async with AsyncSessionFactory() as session:
            char = Character(
                player_id=self.player_id,
                name=name,
                class_type=ClassType(self.class_type),
                stat_vitality=stats["vitality"],
                stat_reflex=stats["reflex"],
                stat_tech=stats["tech"],
                hp_max=stats["hp"],
                hp_current=stats["hp"],
                energy_max=stats["energy"],
                energy_current=stats["energy"],
                credits=STARTING_CREDITS,
                current_location=STARTING_LOCATION,
            )
            session.add(char)
            await session.commit()

        embed = success_embed(
            f"**{class_info['emoji']} {name}** 的意識已接入廢土網路。\n\n"
            f"職業：{class_info['name']}　│　位置：{STARTING_LOCATION}\n"
            f"起始信用點：**{STARTING_CREDITS:,}** 💰\n\n"
            "**▸ 下一步**\n"
            "1️⃣  `/fight` 或 `!fight` — 開始第一場戰鬥\n"
            "2️⃣  `/profile` — 查看角色狀態\n"
            "3️⃣  `/inventory` — 管理裝備與背包\n"
            "4️⃣  `/rpg_help` — 看完整指令清單\n\n"
            "💡 所有指令都可用 `/` 或 `!` 觸發（例：`!fight`）。"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ClassSelectView(discord.ui.View):
    def __init__(self, player_id: int) -> None:
        super().__init__(timeout=120)
        self.player_id = player_id

    @discord.ui.select(
        placeholder="▸ 選擇你的職業路徑...",
        options=[
            discord.SelectOption(
                label="街頭武士", value="street_samurai", emoji="⚔️",
                description="高血量 · 近戰 · 義體強化",
            ),
            discord.SelectOption(
                label="竄網使", value="netrunner", emoji="💻",
                description="駭客術 · 高能量 · 電子攻擊",
            ),
            discord.SelectOption(
                label="拾荒者", value="scavenger", emoji="🗡️",
                description="高敏捷 · 打寶專家 · 求生技能",
            ),
        ],
    )
    async def class_callback(
        self, select: discord.ui.Select, interaction: discord.Interaction
    ) -> None:
        modal = CharacterNameModal(self.player_id, select.values[0])
        await interaction.response.send_modal(modal)
        self.stop()


class CharacterCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="start", description="⚡ 連線至廢土網路，建立你的角色")
    async def start(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Player).where(Player.discord_id == ctx.author.id)
            )
            player = result.scalar_one_or_none()

            if player is None:
                player = Player(
                    discord_id=ctx.author.id,
                    discord_username=str(ctx.author),
                )
                session.add(player)
                await session.flush()  # generate player.id without committing

            player_id = player.id

            result = await session.execute(
                select(Character).where(Character.player_id == player_id)
            )
            existing = result.scalar_one_or_none()
            existing_name = existing.name if existing else None

            await session.commit()

        if existing_name:
            embed = error_embed(
                f"識別代號 **{existing_name}** 已存在於網路中。\n使用 `/profile` 查看狀態。"
            )
            return await ctx.respond(embed=embed, ephemeral=True)

        await ctx.respond(embed=class_select_embed(), view=ClassSelectView(player_id), ephemeral=True)

    @bridge.bridge_command(name="profile", description="📋 查看你的角色狀態面板")
    async def profile(self, ctx: discord.ApplicationContext) -> None:
        from services.title_service import check_title_unlocks

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            character = result.scalar_one_or_none()

            if character is None:
                embed = error_embed("尚未建立角色。\n使用 `/start` 連線至廢土網路。")
                return await ctx.respond(embed=embed, ephemeral=True)

            # Check title unlocks (incl. creator-exclusive) on every profile open
            check_title_unlocks(character, discord_id=ctx.author.id)
            await session.commit()
            await session.refresh(character)

        await ctx.respond(embed=character_profile_embed(character))

    @bridge.bridge_command(name="rest", description="🛌 在安全區休息，完全恢復 HP（花費 50 信用點）")
    async def rest(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

            if char is None:
                return await ctx.respond(
                    embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True
                )
            if char.is_in_combat:
                return await ctx.respond(
                    embed=error_embed("無法在戰鬥中休息！"), ephemeral=True
                )
            if char.hp_current >= char.hp_max:
                return await ctx.respond(
                    embed=error_embed("你的 HP 已滿，不需要休息。"), ephemeral=True
                )
            if char.credits < 50:
                return await ctx.respond(
                    embed=error_embed(f"信用點不足。休息需要 **50** 💰（現有：{char.credits}）。"),
                    ephemeral=True,
                )

            char.credits    -= 50
            char.hp_current  = char.hp_max
            char.energy_current = char.energy_max
            await session.commit()

        embed = success_embed(
            f"HP 與能量完全恢復。\n`{char.hp_max}` / `{char.hp_max}` ❤️\n花費：**50** 💰"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @bridge.bridge_command(name="allocate", description="⚙️ 分配可用的屬性點")
    async def allocate(self, ctx: discord.ApplicationContext) -> None:
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
            return await ctx.respond(embed=error_embed("無法在戰鬥中配點！"), ephemeral=True)
        if char.stat_points_avail <= 0:
            return await ctx.respond(
                embed=error_embed("目前沒有可分配的屬性點。\n打怪升級後獲得點數。"),
                ephemeral=True,
            )

        view = AllocateView(char.id, ctx.author.id)
        await ctx.respond(embed=allocate_embed(char), view=view, ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(CharacterCog(bot))
