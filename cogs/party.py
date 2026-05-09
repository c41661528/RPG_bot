from __future__ import annotations

import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.party_service import (
    INVITE_TIMEOUT_SEC, MAX_PARTY_SIZE,
    Party, PartyMember,
)
from utils.embeds import C_DANGER, C_INFO, C_PRIMARY, C_WARNING, error_embed, success_embed


# ── Embeds ───────────────────────────────────────────────────────

def _party_embed(party: Party) -> discord.Embed:
    lines: list[str] = []
    for m in party.members.values():
        prefix = "👑" if m.discord_user_id == party.leader_id else "▸ "
        lines.append(f"{prefix} **{m.name}**  Lv.{m.level}")
    pending = len(party.pending_invites)
    pending_txt = f"\n📨 邀請待回覆：{pending}" if pending > 0 else ""

    embed = discord.Embed(
        title=f"🎯  隊伍面板  ({party.size}/{MAX_PARTY_SIZE})",
        description="\n".join(lines) + pending_txt,
        color=C_INFO,
    )
    embed.add_field(
        name="📈 戰鬥加成",
        value=(
            f"敵人 HP ×{party.hp_scale_factor():.1f}　│　獎勵每人 ×1.5"
        ),
        inline=False,
    )
    embed.set_footer(text="隊長：用 /party_invite 邀請玩家 → 出發迷宮")
    return embed


# ── Invite UI ────────────────────────────────────────────────────

class InviteView(discord.ui.View):
    def __init__(
        self,
        cog: PartyCog,
        leader_id:       int,
        target_user_id:  int,
        target_char_id:  int,
        target_name:     str,
        target_level:    int,
    ) -> None:
        super().__init__(timeout=INVITE_TIMEOUT_SEC)
        self.cog               = cog
        self.leader_id         = leader_id
        self.target_user_id    = target_user_id
        self.target_char_id    = target_char_id
        self.target_name       = target_name
        self.target_level      = target_level
        self._handled          = False

    @discord.ui.button(label="接受", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        if interaction.user.id != self.target_user_id:
            return await interaction.response.send_message("這個邀請不是給你的。", ephemeral=True)
        if self._handled:
            return
        self._handled = True

        party = self.cog.parties.get(self.leader_id)
        if not party:
            return await interaction.response.edit_message(
                embed=error_embed("隊伍已不存在。"), view=None,
            )
        if party.is_full:
            return await interaction.response.edit_message(
                embed=error_embed("隊伍已滿。"), view=None,
            )
        if self.cog.get_party_of(self.target_user_id):
            return await interaction.response.edit_message(
                embed=error_embed("你已加入其他隊伍。"), view=None,
            )

        party.members[self.target_user_id] = PartyMember(
            self.target_user_id, self.target_char_id,
            self.target_name, self.target_level,
        )
        party.pending_invites.discard(self.target_user_id)
        self.cog.user_to_leader[self.target_user_id] = self.leader_id

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅  加入隊伍",
                description=(
                    f"**{self.target_name}** 已加入隊伍！\n"
                    f"目前 {party.size}/{MAX_PARTY_SIZE} 人"
                ),
                color=C_PRIMARY,
            ),
            view=None,
        )

    @discord.ui.button(label="拒絕", emoji="❌", style=discord.ButtonStyle.secondary)
    async def decline(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        if interaction.user.id != self.target_user_id:
            return await interaction.response.send_message("這個邀請不是給你的。", ephemeral=True)
        if self._handled:
            return
        self._handled = True

        party = self.cog.parties.get(self.leader_id)
        if party:
            party.pending_invites.discard(self.target_user_id)

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌  邀請被拒絕",
                description=f"**{self.target_name}** 婉拒了邀請。",
                color=C_DANGER,
            ),
            view=None,
        )

    async def on_timeout(self) -> None:
        party = self.cog.parties.get(self.leader_id)
        if party:
            party.pending_invites.discard(self.target_user_id)
        self._handled = True


# ── Panel UI ─────────────────────────────────────────────────────

class PartyPanelView(discord.ui.View):
    def __init__(self, cog: PartyCog, leader_id: int) -> None:
        super().__init__(timeout=600)
        self.cog       = cog
        self.leader_id = leader_id

    def _party(self) -> Party | None:
        return self.cog.parties.get(self.leader_id)

    @discord.ui.button(label="出發迷宮", emoji="🗺️", style=discord.ButtonStyle.success, row=0)
    async def go_dungeon(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        party = self._party()
        if not party:
            return await interaction.response.send_message("隊伍已不存在。", ephemeral=True)
        if interaction.user.id != party.leader_id:
            return await interaction.response.send_message("只有隊長能出發。", ephemeral=True)
        if party.activity_in_progress:
            return await interaction.response.send_message("隊伍正在進行活動。", ephemeral=True)

        dungeon_cog = self.cog.bot.get_cog("DungeonCog")
        if dungeon_cog is None or not hasattr(dungeon_cog, "start_party_dungeon"):
            return await interaction.response.send_message("迷宮模組未啟用。", ephemeral=True)

        party.activity_in_progress = True
        try:
            await dungeon_cog.start_party_dungeon(interaction, party)
        except Exception:
            party.activity_in_progress = False
            raise

    @discord.ui.button(label="刷新", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        party = self._party()
        if not party:
            return await interaction.response.edit_message(
                embed=error_embed("隊伍已解散。"), view=None,
            )
        await interaction.response.edit_message(embed=_party_embed(party), view=self)

    @discord.ui.button(label="離開", emoji="🚪", style=discord.ButtonStyle.secondary, row=1)
    async def leave(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        party = self._party()
        if not party:
            return await interaction.response.send_message("隊伍已不存在。", ephemeral=True)
        if interaction.user.id not in party.members:
            return await interaction.response.send_message("你不在這個隊伍。", ephemeral=True)
        if party.activity_in_progress:
            return await interaction.response.send_message("活動進行中無法離開。", ephemeral=True)

        # Leader leaving auto-disbands
        if interaction.user.id == party.leader_id:
            self.cog.disband(party.leader_id)
            return await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🚪  隊長離開，隊伍解散",
                    color=C_WARNING,
                ),
                view=None,
            )

        del party.members[interaction.user.id]
        self.cog.user_to_leader.pop(interaction.user.id, None)
        await interaction.response.edit_message(embed=_party_embed(party), view=self)

    @discord.ui.button(label="解散", emoji="💥", style=discord.ButtonStyle.danger, row=1)
    async def disband(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        party = self._party()
        if not party:
            return await interaction.response.send_message("隊伍已不存在。", ephemeral=True)
        if interaction.user.id != party.leader_id:
            return await interaction.response.send_message("只有隊長能解散。", ephemeral=True)
        if party.activity_in_progress:
            return await interaction.response.send_message("活動進行中無法解散。", ephemeral=True)

        self.cog.disband(party.leader_id)
        await interaction.response.edit_message(
            embed=discord.Embed(title="💥  隊伍已解散", color=C_WARNING),
            view=None,
        )


# ── Cog ──────────────────────────────────────────────────────────

class PartyCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot              = bot
        self.parties:        dict[int, Party] = {}     # leader_user_id → Party
        self.user_to_leader: dict[int, int]   = {}     # user_id → leader_id

    # ── Helpers ──────────────────────────────────────────────────

    def get_party_of(self, user_id: int) -> Party | None:
        leader_id = self.user_to_leader.get(user_id)
        return self.parties.get(leader_id) if leader_id else None

    def disband(self, leader_id: int) -> None:
        party = self.parties.pop(leader_id, None)
        if party:
            for uid in party.members:
                self.user_to_leader.pop(uid, None)

    def _cleanup_expired(self) -> None:
        for lid in [lid for lid, p in self.parties.items() if p.is_expired]:
            self.disband(lid)

    # ── Commands ─────────────────────────────────────────────────

    @bridge.bridge_command(name="party_form", description="🎯 建立新隊伍（你會是隊長）")
    async def party_form(self, ctx: discord.ApplicationContext) -> None:
        self._cleanup_expired()
        if self.get_party_of(ctx.author.id):
            return await ctx.respond(
                embed=error_embed("你已經在隊伍中。先用 `/party_leave` 離開。"),
                ephemeral=True,
            )

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()
        if not char:
            return await ctx.respond(
                embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True,
            )

        leader = PartyMember(ctx.author.id, char.id, char.name, char.level)
        party  = Party(leader_id=ctx.author.id, members={ctx.author.id: leader})
        self.parties[ctx.author.id]        = party
        self.user_to_leader[ctx.author.id] = ctx.author.id

        await ctx.respond(
            embed=_party_embed(party),
            view=PartyPanelView(self, ctx.author.id),
        )

    @bridge.bridge_command(name="party_invite", description="🎯 邀請玩家加入你的隊伍")
    async def party_invite(
        self,
        ctx: discord.ApplicationContext,
        target: bridge.BridgeOption(discord.Member, description="要邀請的玩家"),
    ) -> None:
        party = self.get_party_of(ctx.author.id)
        if not party:
            return await ctx.respond(
                embed=error_embed("你不在任何隊伍。先用 `/party_form` 建立。"),
                ephemeral=True,
            )
        if party.leader_id != ctx.author.id:
            return await ctx.respond(embed=error_embed("只有隊長能邀請。"), ephemeral=True)
        if party.is_full:
            return await ctx.respond(
                embed=error_embed(f"隊伍已滿（{MAX_PARTY_SIZE} 人）。"), ephemeral=True,
            )
        if target.id == ctx.author.id:
            return await ctx.respond(embed=error_embed("不能邀請自己。"), ephemeral=True)
        if target.bot:
            return await ctx.respond(embed=error_embed("不能邀請機器人。"), ephemeral=True)
        if target.id in party.members:
            return await ctx.respond(
                embed=error_embed(f"{target.display_name} 已在隊伍中。"), ephemeral=True,
            )
        if self.get_party_of(target.id):
            return await ctx.respond(
                embed=error_embed(f"{target.display_name} 已在其他隊伍。"), ephemeral=True,
            )
        if target.id in party.pending_invites:
            return await ctx.respond(
                embed=error_embed(f"已經邀請過 {target.display_name}，等待回應中。"),
                ephemeral=True,
            )

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == target.id)
            )
            target_char = result.scalar_one_or_none()
        if not target_char:
            return await ctx.respond(
                embed=error_embed(f"{target.display_name} 尚未建立角色。"), ephemeral=True,
            )

        party.pending_invites.add(target.id)
        view = InviteView(
            self, party.leader_id, target.id,
            target_char.id, target_char.name, target_char.level,
        )
        embed = discord.Embed(
            title="🎯  隊伍邀請",
            description=(
                f"**{ctx.author.display_name}** 邀請 **{target.display_name}** "
                f"加入隊伍！\n"
                f"目前隊伍：{party.size}/{MAX_PARTY_SIZE} 人\n\n"
                f"⏳ 60 秒內按下方按鈕回應。"
            ),
            color=C_INFO,
        )
        await ctx.respond(content=target.mention, embed=embed, view=view)

    @bridge.bridge_command(name="party_status", description="🎯 查看你目前所在的隊伍")
    async def party_status(self, ctx: discord.ApplicationContext) -> None:
        party = self.get_party_of(ctx.author.id)
        if not party:
            return await ctx.respond(
                embed=error_embed("你不在任何隊伍。"), ephemeral=True,
            )
        await ctx.respond(
            embed=_party_embed(party),
            view=PartyPanelView(self, party.leader_id),
            ephemeral=True,
        )

    @bridge.bridge_command(name="party_leave", description="🚪 離開當前隊伍（隊長離開會解散）")
    async def party_leave(self, ctx: discord.ApplicationContext) -> None:
        party = self.get_party_of(ctx.author.id)
        if not party:
            return await ctx.respond(
                embed=error_embed("你不在任何隊伍。"), ephemeral=True,
            )
        if party.activity_in_progress:
            return await ctx.respond(
                embed=error_embed("隊伍正在進行活動，無法離開。"), ephemeral=True,
            )

        if ctx.author.id == party.leader_id:
            self.disband(party.leader_id)
            return await ctx.respond(
                embed=success_embed("你是隊長，隊伍已解散。"), ephemeral=True,
            )

        del party.members[ctx.author.id]
        self.user_to_leader.pop(ctx.author.id, None)
        await ctx.respond(embed=success_embed("已離開隊伍。"), ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(PartyCog(bot))
