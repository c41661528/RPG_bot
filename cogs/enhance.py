import random

import discord
from discord.ext import bridge, commands
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from config import ENHANCE_BONUS_PER_LV, ENHANCE_COSTS, ENHANCE_RATES, MAX_ENHANCE
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.equipment_service import can_enhance, enhance_level, get_item, get_material, all_materials
from utils.embeds import C_DANGER, C_INFO, C_PRIMARY, C_WARNING, error_embed

# All equippable slots that can be enhanced
_SLOT_ATTR = {
    "武器": "equipped_weapon",
    "護甲": "equipped_armor",
    "頭盔": "equipped_helmet",
    "配件": "equipped_accessory",
}


def _stat_label(item: dict) -> str:
    if "atk_bonus" in item:
        return "ATK", item["atk_bonus"]
    if "def_bonus" in item:
        return "DEF", item["def_bonus"]
    if "energy_bonus" in item:
        return "⚡", item["energy_bonus"]
    return "?", 0


def _enhance_embed(char: Character) -> discord.Embed:
    lines: list[str] = []
    for slot, attr in _SLOT_ATTR.items():
        item_id = getattr(char, attr)
        item    = get_item(item_id) if item_id else None
        emoji   = {"武器": "⚔️", "護甲": "🛡️", "頭盔": "⛑️", "配件": "💠"}[slot]
        if not item:
            lines.append(f"{emoji} **{slot}**：`空`")
            continue
        lv    = enhance_level(item_id, char.item_enhancements or {})
        stat_name, base = _stat_label(item)
        total = base + lv * ENHANCE_BONUS_PER_LV
        if lv < MAX_ENHANCE:
            cost = ENHANCE_COSTS[lv]
            rate = int(ENHANCE_RATES[lv] * 100)
            next_info = f"費用 **{cost:,}** 💰　成功率 **{rate}%**　→ +{total + ENHANCE_BONUS_PER_LV} {stat_name}"
        else:
            next_info = "已達最大強化等級"
        lines.append(
            f"{emoji} **{slot}**：{item['emoji']} {item['name']}"
            f"  `+{lv}` → **{total} {stat_name}**\n> {next_info}"
        )

    # Show available materials
    mats = char.materials or {}
    mat_parts: list[str] = []
    for m in all_materials():
        qty = mats.get(m["id"], 0)
        if qty > 0:
            mat_parts.append(f"{m['emoji']} {m['name']} ×{qty}（+{int(m['enhance_bonus']*100)}%）")
    mat_text = "\n".join(mat_parts) if mat_parts else "`無材料`"

    embed = discord.Embed(
        title=f"🔨  裝備強化  —  {char.name}",
        description="\n\n".join(lines) + f"\n\n💰 **信用點：** {char.credits:,}",
        color=C_INFO,
    )
    embed.add_field(name="🧪 可用材料（消耗後提升成功率）", value=mat_text, inline=False)
    embed.set_footer(text=f"失敗仍扣費  ·  最高 +{MAX_ENHANCE}  ·  材料可提升成功率")
    return embed


class MaterialSelect(discord.ui.Select):
    """Lets the player pick a material to use (or none)."""

    def __init__(self, char: Character) -> None:
        mats  = char.materials or {}
        options = [
            discord.SelectOption(label="不使用材料", value="__none__", emoji="❌"),
        ]
        for m in all_materials():
            qty = mats.get(m["id"], 0)
            if qty > 0:
                options.append(
                    discord.SelectOption(
                        label=f"{m['name']} ×{qty}  (+{int(m['enhance_bonus']*100)}% 成功率)",
                        value=m["id"],
                        emoji=m["emoji"],
                    )
                )
        super().__init__(
            placeholder="選擇強化材料（可選）...",
            options=options,
            min_values=1,
            max_values=1,
            row=2,
        )
        self.char_id    = char.id
        self.parent_view = None   # set by EnhanceView after add_item

    async def callback(self, interaction: discord.Interaction) -> None:
        # Just acknowledge; the button handler reads self.values
        await interaction.response.defer()


class EnhanceView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.char_id         = char.id
        self.discord_user_id = discord_user_id
        enh = char.item_enhancements or {}

        # Buttons from decorators land first in children[0..3]:
        #   [0]=weapon [1]=armor [2]=helmet [3]=accessory
        # Then add material select as children[4]
        self.mat_select = MaterialSelect(char)
        self.mat_select.parent_view = self  # type: ignore[attr-defined]
        self.add_item(self.mat_select)

        # Disable slot buttons if nothing equipped / maxed / can't afford
        for slot, attr, idx in [
            ("武器", "equipped_weapon",    0),
            ("護甲", "equipped_armor",     1),
            ("頭盔", "equipped_helmet",    2),
            ("配件", "equipped_accessory", 3),
        ]:
            item_id = getattr(char, attr)
            self.children[idx].disabled = (
                not item_id
                or not can_enhance(item_id, enh)
                or char.credits < ENHANCE_COSTS[enhance_level(item_id, enh)]
            )

    async def _do_enhance(
        self, interaction: discord.Interaction, slot: str
    ) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        attr = _SLOT_ATTR[slot]

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

            item_id = getattr(char, attr)
            if not item_id:
                return await interaction.response.send_message(f"沒有裝備{slot}。", ephemeral=True)

            enh = dict(char.item_enhancements or {})
            lv  = enh.get(item_id, 0)

            if lv >= MAX_ENHANCE:
                return await interaction.response.send_message("已達最大強化等級。", ephemeral=True)

            cost = ENHANCE_COSTS[lv]
            if char.credits < cost:
                return await interaction.response.send_message(
                    f"信用點不足（需要 {cost:,}）。", ephemeral=True
                )

            # Resolve material bonus (read from select's current values)
            mat_bonus = 0.0
            mat_name  = ""
            mat_id    = (self.mat_select.values[0]
                         if self.mat_select.values else "__none__")
            if mat_id and mat_id != "__none__":
                mats_owned = dict(char.materials or {})
                if mats_owned.get(mat_id, 0) > 0:
                    mat = get_material(mat_id)
                    if mat:
                        mat_bonus = mat["enhance_bonus"]
                        mat_name  = f"{mat['emoji']} {mat['name']}"
                        mats_owned[mat_id] -= 1
                        if mats_owned[mat_id] <= 0:
                            del mats_owned[mat_id]
                        char.materials = mats_owned
                        flag_modified(char, "materials")

            char.credits -= cost
            rate    = min(0.99, ENHANCE_RATES[lv] + mat_bonus)
            success = random.random() < rate
            mat_txt = f"  （使用 {mat_name}，成功率 +{int(mat_bonus*100)}%→{int(rate*100)}%）" if mat_name else ""

            if success:
                enh[item_id] = lv + 1
                char.item_enhancements = enh
                flag_modified(char, "item_enhancements")
                result_txt = f"✅ 強化成功！**+{lv} → +{lv+1}**{mat_txt}"
                color      = C_PRIMARY
            else:
                result_txt = f"❌ 強化失敗，裝備維持 **+{lv}**。{mat_txt}"
                color      = C_DANGER

            await session.commit()
            await session.refresh(char)

        new_view = EnhanceView(char, self.discord_user_id)
        await interaction.response.edit_message(embed=_enhance_embed(char), view=new_view)
        await interaction.followup.send(
            embed=discord.Embed(description=result_txt, color=color),
            ephemeral=True,
        )

    @discord.ui.button(label="強化武器", emoji="⚔️", style=discord.ButtonStyle.primary, row=0)
    async def enhance_weapon(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._do_enhance(interaction, "武器")

    @discord.ui.button(label="強化護甲", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def enhance_armor(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._do_enhance(interaction, "護甲")

    @discord.ui.button(label="強化頭盔", emoji="⛑️", style=discord.ButtonStyle.primary, row=1)
    async def enhance_helmet(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._do_enhance(interaction, "頭盔")

    @discord.ui.button(label="強化配件", emoji="💠", style=discord.ButtonStyle.primary, row=1)
    async def enhance_accessory(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await self._do_enhance(interaction, "配件")

    # Material select callback wires selected_mat
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True  # allow all; individual handlers check ownership


class EnhanceCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="enhance", description="🔨 強化已裝備的武器、護甲、頭盔或配件")
    async def enhance(self, ctx: discord.ApplicationContext) -> None:
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
            return await ctx.respond(embed=error_embed("無法在戰鬥中強化裝備！"), ephemeral=True)

        has_any = any([
            char.equipped_weapon, char.equipped_armor,
            char.equipped_helmet, char.equipped_accessory,
        ])
        if not has_any:
            return await ctx.respond(
                embed=error_embed("沒有裝備任何物品。使用 `/inventory` 先裝備物品。"),
                ephemeral=True,
            )

        view = EnhanceView(char, ctx.author.id)
        await ctx.respond(embed=_enhance_embed(char), view=view, ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(EnhanceCog(bot))
