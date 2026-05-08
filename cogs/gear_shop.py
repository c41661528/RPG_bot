import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from config import MATERIAL_PRICES
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.equipment_service import all_materials, get_item
from services.gear_gen import generate_shop_stock
from services.quest_service import update_quest_progress
from utils.embeds import C_INFO, error_embed, success_embed

_SLOT_LABEL = {"ci_w": "武器", "ci_a": "護甲", "ci_h": "頭盔", "ci_ac": "配件"}
_RARITY     = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣"}

_INVENTORY_LIMIT = 20


def _item_prefix(item_id: str) -> str:
    for p in ("ci_ac", "ci_w", "ci_a", "ci_h"):
        if item_id.startswith(p + "_"):
            return p
    return ""


def _fmt_stats(item: dict) -> str:
    parts: list[str] = []
    if item.get("atk_bonus",    0):   parts.append(f"ATK +{item['atk_bonus']}")
    if item.get("def_bonus",    0):   parts.append(f"DEF +{item['def_bonus']}")
    if item.get("hp_bonus",     0):   parts.append(f"HP +{item['hp_bonus']}")
    if item.get("energy_bonus", 0):   parts.append(f"能量 +{item['energy_bonus']}")
    if item.get("crit_bonus",   0.0): parts.append(f"爆擊 +{int(item['crit_bonus']*100)}%")
    return " / ".join(parts) if parts else "—"


def _gear_embed(char: Character) -> discord.Embed:
    stock = char.shop_stock or {}
    ci    = char.custom_items or {}
    items = stock.get("items", [])
    gen_lv = stock.get("gen_level", 0)

    lv_note = (
        f"庫存適合 Lv.**{gen_lv}** 角色"
        + ("（已是最新）" if gen_lv == char.level else f"　→ 下次 `/gear_shop` 將自動更新至 Lv.**{char.level}**")
    )

    embed = discord.Embed(
        title="🔧  黑市裝備行",
        description=(
            "昏暗倉庫裡擺著今天到貨的貨物，商人懶洋洋地嗑著菸。\n\n"
            f"💰 你的信用點：**{char.credits:,}**\n"
            f"📦 {lv_note}"
        ),
        color=C_INFO,
    )

    if not items:
        embed.add_field(name="庫存", value="今日無貨，請再試一次。", inline=False)
        embed.set_footer(text="使用 /buy_gear <編號> 購買裝備")
        return embed

    lines: list[str] = []
    for idx, entry in enumerate(items, start=1):
        iid   = entry["item_id"]
        price = entry["price"]
        item  = get_item(iid, ci)
        if not item:
            continue
        prefix = _item_prefix(iid)
        slot   = _SLOT_LABEL.get(prefix, "?")
        tier_e = _RARITY.get(item.get("tier", 1), "⚪")
        stats  = _fmt_stats(item)
        lines.append(
            f"`{idx}.` {tier_e} {item['emoji']} **{item['name']}**　[{slot}]\n"
            f"　　{stats}　→　**{price:,}** 💰"
        )

    embed.add_field(name="今日庫存", value="\n".join(lines), inline=False)
    embed.set_footer(text="使用 /buy_gear <編號1-6> 購買裝備  ·  升級後庫存自動刷新")
    return embed


def _mat_embed(char: Character) -> discord.Embed:
    mats = all_materials()
    owned = char.materials or {}
    lines: list[str] = []
    for m in mats:
        price = MATERIAL_PRICES.get(m["id"], 0)
        qty   = owned.get(m["id"], 0)
        lines.append(
            f"{m['emoji']} **{m['name']}**　**{price:,}** 💰　`×{qty} 持有`\n"
            f"　強化加成 +{int(m['enhance_bonus']*100)}%"
        )
    embed = discord.Embed(
        title="🔩  強化材料行",
        description=(
            f"💰 你的信用點：**{char.credits:,}**\n\n"
            + "\n".join(lines)
        ),
        color=C_INFO,
    )
    embed.set_footer(text="使用 /buy_material <材料名稱> [數量] 購買")
    return embed


class GearShopCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    # ── /gear_shop ───────────────────────────────────────────────

    @bridge.bridge_command(name="gear_shop", description="🔧 查看黑市裝備行（等級縮放隨機裝備）")
    async def gear_shop(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()
            if char is None:
                return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)

            stock = char.shop_stock or {}
            if stock.get("gen_level") != char.level or not stock.get("items"):
                new_stock, new_ci = generate_shop_stock(char.level)
                # Merge new custom items; keep existing ones for equipped/bag items
                ci = dict(char.custom_items or {})
                ci.update(new_ci)
                char.custom_items = ci
                char.shop_stock   = new_stock
                await session.commit()
                await session.refresh(char)

        await ctx.respond(embed=_gear_embed(char), ephemeral=True)

    # ── /buy_gear ────────────────────────────────────────────────

    @bridge.bridge_command(name="buy_gear", description="🛒 購買裝備行中的裝備")
    async def buy_gear(
        self,
        ctx: discord.ApplicationContext,
        slot: discord.Option(int, description="裝備編號（1–6）", min_value=1, max_value=6),
    ) -> None:
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
                return await ctx.respond(embed=error_embed("無法在戰鬥中購物！"), ephemeral=True)

            stock = char.shop_stock or {}
            items = stock.get("items", [])
            if not items or slot > len(items):
                return await ctx.respond(embed=error_embed("裝備編號無效，請先使用 `/gear_shop` 查看庫存。"), ephemeral=True)

            entry  = items[slot - 1]
            iid    = entry["item_id"]
            price  = entry["price"]
            ci     = char.custom_items or {}
            item   = get_item(iid, ci)
            if not item:
                return await ctx.respond(embed=error_embed("該裝備不存在，請重新整理商店。"), ephemeral=True)

            if char.credits < price:
                return await ctx.respond(
                    embed=error_embed(f"信用點不足。需要 **{price:,}** 💰（現有：{char.credits:,}）。"),
                    ephemeral=True,
                )

            inv = list(char.inventory or [])
            if len(inv) >= _INVENTORY_LIMIT:
                return await ctx.respond(embed=error_embed("背包已滿（20/20），請先出售或裝備物品。"), ephemeral=True)

            # Deduct cost, add to inventory, remove from stock
            char.credits -= price
            inv.append(iid)
            char.inventory = inv

            new_items = [e for e in items if e["item_id"] != iid]
            char.shop_stock = {**stock, "items": new_items}

            update_quest_progress(char, "buy_items", 1)
            await session.commit()

        prefix = _item_prefix(iid)
        slot_name = _SLOT_LABEL.get(prefix, "裝備")
        tier_e    = _RARITY.get(item.get("tier", 1), "⚪")
        stats     = _fmt_stats(item)
        await ctx.respond(
            embed=success_embed(
                f"購買了 {tier_e} {item['emoji']} **{item['name']}** [{slot_name}]，"
                f"花費 **{price:,}** 💰\n"
                f"屬性：{stats}\n"
                f"剩餘信用點：**{char.credits:,}**\n"
                f"裝備已放入背包，使用 `/inventory` 裝備它。"
            ),
            ephemeral=True,
        )

    # ── /mat_shop ────────────────────────────────────────────────

    @bridge.bridge_command(name="mat_shop", description="🔩 查看強化材料行")
    async def mat_shop(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()
        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)
        await ctx.respond(embed=_mat_embed(char), ephemeral=True)

    # ── /buy_material ────────────────────────────────────────────

    @bridge.bridge_command(name="buy_material", description="🔩 購買強化材料")
    async def buy_material(
        self,
        ctx: discord.ApplicationContext,
        material: discord.Option(
            str,
            description="材料名稱",
            choices=["廢棄金屬", "電路板", "能量核心", "奈米纖維", "量子晶片"],
        ),
        quantity: discord.Option(
            int,
            description="購買數量（預設 1）",
            min_value=1,
            max_value=20,
            default=1,
        ),
    ) -> None:
        name_to_id = {
            "廢棄金屬": "scrap_metal",
            "電路板":   "circuit_board",
            "能量核心": "energy_core",
            "奈米纖維": "nano_fiber",
            "量子晶片": "quantum_chip",
        }
        mat_id     = name_to_id[material]
        price_each = MATERIAL_PRICES[mat_id]
        total_cost = price_each * quantity

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
                return await ctx.respond(embed=error_embed("無法在戰鬥中購物！"), ephemeral=True)
            if char.credits < total_cost:
                return await ctx.respond(
                    embed=error_embed(
                        f"信用點不足。需要 **{total_cost:,}** 💰（現有：{char.credits:,}）。"
                    ),
                    ephemeral=True,
                )

            char.credits -= total_cost
            mats = dict(char.materials or {})
            mats[mat_id] = mats.get(mat_id, 0) + quantity
            char.materials = mats
            new_qty = mats[mat_id]
            await session.commit()

        from services.equipment_service import get_material
        mat = get_material(mat_id)
        emoji = mat["emoji"] if mat else "🔩"
        await ctx.respond(
            embed=success_embed(
                f"購買了 **{quantity}** 個 {emoji} **{material}**，"
                f"花費 **{total_cost:,}** 💰\n"
                f"現有存量：**{new_qty}** 個　│　剩餘信用點：**{char.credits:,}**"
            ),
            ephemeral=True,
        )


def setup(bot: discord.Bot) -> None:
    bot.add_cog(GearShopCog(bot))
