from collections import Counter

import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from config import ENHANCE_BONUS_PER_LV
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.equipment_service import (
    enhance_level, get_item,
    is_accessory, is_armor, is_helmet, is_weapon,
    item_slot, sell_value,
)
from utils.embeds import C_INFO, C_WARNING, error_embed, success_embed

_INVENTORY_LIMIT = 20

RARITY_EMOJI = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣"}

# Slot attr names
_SLOT_ATTR = {
    "武器": "equipped_weapon",
    "護甲": "equipped_armor",
    "頭盔": "equipped_helmet",
    "配件": "equipped_accessory",
}


def _fmt_item(item: dict, enh_level: int = 0) -> str:
    tier_e  = RARITY_EMOJI.get(item.get("tier", 1), "⚪")
    enh_b   = enh_level * ENHANCE_BONUS_PER_LV
    parts: list[str] = []
    if item.get("atk_bonus", 0):
        total = item["atk_bonus"] + enh_b
        parts.append(f"+{total} ATK" + (f"(🔨+{enh_b})" if enh_b else ""))
    if item.get("def_bonus", 0):
        total = item["def_bonus"] + enh_b
        parts.append(f"+{total} DEF" + (f"(🔨+{enh_b})" if enh_b else ""))
    if item.get("hp_bonus",     0):   parts.append(f"+{item['hp_bonus']} HP")
    if item.get("energy_bonus", 0):   parts.append(f"+{item['energy_bonus']} ⚡")
    if item.get("crit_bonus",   0.0): parts.append(f"+{int(item['crit_bonus']*100)}% 暴擊")
    bonus = " / ".join(parts) if parts else "?"
    return f"{tier_e} {item['emoji']} **{item['name']}** `{bonus}`"


def _inventory_embed(char: Character) -> discord.Embed:
    ci  = char.custom_items or {}
    enh = char.item_enhancements or {}
    w   = get_item(char.equipped_weapon,    ci) if char.equipped_weapon    else None
    a   = get_item(char.equipped_armor,     ci) if char.equipped_armor     else None
    h   = get_item(char.equipped_helmet,    ci) if char.equipped_helmet    else None
    acc = get_item(char.equipped_accessory, ci) if char.equipped_accessory else None

    equipped_lines = [
        f"⚔️  武器：{_fmt_item(w,   enhance_level(char.equipped_weapon,    enh)) if w   else '`空`'}",
        f"🛡️  護甲：{_fmt_item(a,   enhance_level(char.equipped_armor,     enh)) if a   else '`空`'}",
        f"⛑️  頭盔：{_fmt_item(h,   enhance_level(char.equipped_helmet,    enh)) if h   else '`空`'}",
        f"💠  配件：{_fmt_item(acc, enhance_level(char.equipped_accessory, enh)) if acc else '`空`'}",
    ]

    # Materials
    mats = char.materials or {}
    if mats:
        from services.equipment_service import get_material
        mat_parts = []
        for mid, qty in mats.items():
            m = get_material(mid)
            if m:
                mat_parts.append(f"{m['emoji']} {m['name']} ×{qty}")
        mat_text = "  ".join(mat_parts) if mat_parts else "`無`"
    else:
        mat_text = "`無`"

    # Bag — group duplicates
    inv: list[str] = list(char.inventory or [])
    count = Counter(inv)
    bag_lines: list[str] = []
    seen: set[str] = set()
    for item_id in inv:
        if item_id in seen:
            continue
        seen.add(item_id)
        item = get_item(item_id, ci)
        if not item:
            continue
        qty     = count[item_id]
        qty_txt = f" ×{qty}" if qty > 1 else ""
        bag_lines.append(f"{_fmt_item(item)}{qty_txt}")

    bag_text = "\n".join(bag_lines) if bag_lines else "`背包是空的`"
    used = len(inv)

    embed = discord.Embed(
        title=f"🎒  {char.name} 的裝備欄",
        color=C_INFO,
    )
    embed.add_field(name="▸ 已裝備", value="\n".join(equipped_lines), inline=False)
    embed.add_field(name="▸ 材料",   value=mat_text,                  inline=False)
    embed.add_field(name=f"▸ 背包　{used}/{_INVENTORY_LIMIT}", value=bag_text, inline=False)
    embed.set_footer(text="使用下方選單裝備物品  ·  /unequip 卸下裝備")
    return embed


class EquipSelect(discord.ui.Select):
    def __init__(self, char: Character) -> None:
        self.char_id     = char.id
        self.custom_items = char.custom_items or {}
        ci = self.custom_items
        inv: list[str] = list(char.inventory or [])
        seen: set[str] = set()
        options: list[discord.SelectOption] = []

        for item_id in inv:
            if item_id in seen or len(options) >= 25:
                continue
            seen.add(item_id)
            item = get_item(item_id, ci)
            if not item:
                continue
            slot   = item_slot(item_id)
            if "atk_bonus" in item:
                bonus = f"+{item['atk_bonus']} ATK"
            elif "def_bonus" in item and "hp_bonus" in item:
                bonus = f"+{item['def_bonus']} DEF +{item['hp_bonus']} HP"
            elif "def_bonus" in item:
                bonus = f"+{item['def_bonus']} DEF"
            elif "energy_bonus" in item:
                bonus = f"+{item['energy_bonus']} ⚡"
            else:
                bonus = "?"
            options.append(
                discord.SelectOption(
                    label=f"{item['name']}  {bonus}",
                    value=item_id,
                    emoji=item["emoji"],
                    description=f"{slot} · {item['desc'][:40]}",
                )
            )

        if not options:
            options = [discord.SelectOption(label="背包是空的", value="__empty__")]

        super().__init__(
            placeholder="選擇要裝備的物品...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.char_id         = char.id
        self.discord_user_id = char.id  # will be overridden in view

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "__empty__":
            return await interaction.response.send_message("背包是空的。", ephemeral=True)

        ci      = self.custom_items
        item_id = self.values[0]
        item    = get_item(item_id, ci)
        if not item:
            return await interaction.response.send_message("找不到該物品。", ephemeral=True)

        slot      = item_slot(item_id)
        attr      = _SLOT_ATTR.get(slot)
        if not attr:
            return await interaction.response.send_message("無法辨別裝備槽位。", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()
            ci     = char.custom_items or {}

            inv = list(char.inventory or [])
            if item_id not in inv:
                return await interaction.response.send_message("背包中沒有該物品。", ephemeral=True)

            inv.remove(item_id)
            old = getattr(char, attr)
            setattr(char, attr, item_id)
            if old:
                inv.append(old)

            char.inventory = inv
            await session.commit()
            await session.refresh(char)

        old_item = get_item(old, ci) if old else None
        old_txt  = f"（替換 {old_item['emoji']} **{old_item['name']}**，已放回背包）" if old_item else ""
        await interaction.response.edit_message(
            embed=_inventory_embed(char),
            view=InventoryView(char),
        )
        await interaction.followup.send(
            embed=success_embed(
                f"已裝備 {item['emoji']} **{item['name']}** 至 **{slot}** 欄位。{old_txt}"
            ),
            ephemeral=True,
        )


class InventoryView(discord.ui.View):
    def __init__(self, char: Character) -> None:
        super().__init__(timeout=120)
        sel = EquipSelect(char)
        self.add_item(sel)


class InventoryCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="inventory", description="🎒 查看背包與裝備欄位")
    async def inventory(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)

        await ctx.respond(embed=_inventory_embed(char), view=InventoryView(char), ephemeral=True)

    @bridge.bridge_command(name="unequip", description="🔓 卸下當前裝備的物品")
    async def unequip(
        self,
        ctx: discord.ApplicationContext,
        slot: discord.Option(str, description="要卸下的欄位", choices=["武器", "護甲", "頭盔", "配件"]),
    ) -> None:
        attr = _SLOT_ATTR[slot]

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
                return await ctx.respond(embed=error_embed("無法在戰鬥中卸裝！"), ephemeral=True)

            item_id = getattr(char, attr)
            if not item_id:
                return await ctx.respond(embed=error_embed(f"{slot}欄位是空的。"), ephemeral=True)

            ci = char.custom_items or {}
            setattr(char, attr, None)
            inv = list(char.inventory or [])
            if len(inv) < _INVENTORY_LIMIT:
                inv.append(item_id)
                char.inventory = inv
                msg = "已放回背包。"
            else:
                msg = "背包已滿，裝備已丟棄。"

            await session.commit()

        item = get_item(item_id, ci)
        name = f"{item['emoji']} **{item['name']}**" if item else item_id
        await ctx.respond(embed=success_embed(f"卸下 {name}。{msg}"), ephemeral=True)

    @bridge.bridge_command(name="sell", description="💰 出售背包中的裝備換取信用點")
    async def sell(self, ctx: discord.ApplicationContext) -> None:
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
            return await ctx.respond(embed=error_embed("無法在戰鬥中出售裝備！"), ephemeral=True)

        inv = list(char.inventory or [])
        if not inv:
            return await ctx.respond(embed=error_embed("背包是空的，沒有可出售的裝備。"), ephemeral=True)

        view = SellSelectView(char, ctx.author.id)
        await ctx.respond(embed=_sell_embed(char), view=view, ephemeral=True)


# ── Sell helpers ─────────────────────────────────────────────────

def _sell_embed(
    char: Character,
    selected_id: str = "",
    price: int = 0,
    sold_msg: str = "",
) -> discord.Embed:
    ci  = char.custom_items or {}
    inv = list(char.inventory or [])
    enh = char.item_enhancements or {}

    if selected_id:
        item = get_item(selected_id, ci)
        lv   = enhance_level(selected_id, enh)
        name = f"{item['emoji']} **{item['name']}**" if item else selected_id
        lv_txt = f" `+{lv}`" if lv > 0 else ""
        desc = (
            f"確定要出售 {name}{lv_txt}？\n\n"
            f"💰 售價：**{price:,}** 信用點\n"
            f"⚠️ 出售後無法復原。"
        )
        color = 0xFFAA00
    else:
        lines: list[str] = []
        seen: set[str] = set()
        for item_id in inv:
            if item_id in seen:
                continue
            seen.add(item_id)
            item = get_item(item_id, ci)
            if not item:
                continue
            lv  = enhance_level(item_id, enh)
            val = sell_value(item_id, lv, ci)
            lv_txt  = f" `+{lv}`" if lv > 0 else ""
            tier_e  = RARITY_EMOJI.get(item.get("tier", 1), "⚪")
            lines.append(f"{tier_e} {item['emoji']} **{item['name']}**{lv_txt}　→ **{val:,}** 💰")
        body  = "\n".join(lines) if lines else "`背包是空的`"
        desc  = f"{sold_msg}\n\n{body}" if sold_msg else body
        color = 0x2ECC71 if sold_msg else C_INFO

    embed = discord.Embed(
        title="🏪  黑市回收站",
        description=desc,
        color=color,
    )
    embed.set_footer(text=f"💰 現有信用點：{char.credits:,}")
    return embed


class SellSelectView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int) -> None:
        super().__init__(timeout=120)
        self.discord_user_id = discord_user_id
        self.add_item(_SellSelect(char))


class _SellSelect(discord.ui.Select):
    def __init__(self, char: Character) -> None:
        self.char_id     = char.id
        self.custom_items = char.custom_items or {}
        ci  = self.custom_items
        inv  = list(char.inventory or [])
        enh  = char.item_enhancements or {}
        seen: set[str] = set()
        options: list[discord.SelectOption] = []

        for item_id in inv:
            if item_id in seen or len(options) >= 25:
                continue
            seen.add(item_id)
            item = get_item(item_id, ci)
            if not item:
                continue
            lv  = enhance_level(item_id, enh)
            val = sell_value(item_id, lv, ci)
            lv_txt = f" +{lv}" if lv > 0 else ""
            options.append(
                discord.SelectOption(
                    label=f"{item['name']}{lv_txt}　{val:,} 💰",
                    value=item_id,
                    emoji=item["emoji"],
                    description=f"{item_slot(item_id)} · tier {item.get('tier',1)}",
                )
            )

        if not options:
            options = [discord.SelectOption(label="背包是空的", value="__empty__")]

        super().__init__(
            placeholder="選擇要出售的裝備...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent: SellSelectView = self.view  # type: ignore[assignment]
        if interaction.user.id != parent.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        item_id = self.values[0]
        if item_id == "__empty__":
            return await interaction.response.send_message("背包是空的。", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

        ci    = char.custom_items or {}
        enh   = char.item_enhancements or {}
        lv    = enhance_level(item_id, enh)
        price = sell_value(item_id, lv, ci)

        confirm_view = _ConfirmSellView(char, parent.discord_user_id, item_id, price)
        await interaction.response.edit_message(
            embed=_sell_embed(char, item_id, price),
            view=confirm_view,
        )


class _ConfirmSellView(discord.ui.View):
    def __init__(
        self, char: Character, discord_user_id: int, item_id: str, price: int
    ) -> None:
        super().__init__(timeout=60)
        self.char_id         = char.id
        self.discord_user_id = discord_user_id
        self.item_id         = item_id
        self.price           = price

    @discord.ui.button(label="確認出售", emoji="💰", style=discord.ButtonStyle.danger)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

            inv = list(char.inventory or [])
            if self.item_id not in inv:
                return await interaction.response.send_message(
                    "背包中找不到該物品（可能已售出）。", ephemeral=True
                )

            inv.remove(self.item_id)
            char.inventory = inv
            char.credits  += self.price

            # Remove enhance and custom data for sold item if no more copies
            if self.item_id not in inv:
                enh = dict(char.item_enhancements or {})
                enh.pop(self.item_id, None)
                char.item_enhancements = enh

                if self.item_id.startswith("ci_"):
                    ci = dict(char.custom_items or {})
                    ci.pop(self.item_id, None)
                    char.custom_items = ci

            await session.commit()
            await session.refresh(char)

        item     = get_item(self.item_id, char.custom_items or {})
        name     = f"{item['emoji']} **{item['name']}**" if item else self.item_id
        sold_msg = f"✅ 出售 {name}，獲得 **+{self.price:,}** 💰"

        await interaction.response.edit_message(
            embed=_sell_embed(char, sold_msg=sold_msg),
            view=SellSelectView(char, self.discord_user_id) if char.inventory else None,
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

        await interaction.response.edit_message(
            embed=_sell_embed(char),
            view=SellSelectView(char, self.discord_user_id),
        )


def setup(bot: discord.Bot) -> None:
    bot.add_cog(InventoryCog(bot))
