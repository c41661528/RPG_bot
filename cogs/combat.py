import json
import random
from pathlib import Path

import discord
from discord.ext import commands
from sqlalchemy import select

from config import (
    ADRENALINE_ATK_MULT,
    ADRENALINE_DURATION,
    CLASS_SKILLS,
    COMBO_BONUS,
    COMBO_MAX,
    CORROSIVE_VIAL_PCT,
    CORROSIVE_VIAL_TURNS,
    DEFEND_ENERGY_COST,
    EMP_GRENADE_STUN,
    ENERGY_CELL_RESTORE,
    MAX_LEVEL,
    MEDKIT_HEAL_PCT,
    NANO_REPAIR_PCT,
    NANO_REPAIR_TURNS,
    STAT_POINTS_PER_LEVEL,
    STIMULANT_ENERGY,
    STIMULANT_HEAL_PCT,
    exp_for_next_level,
)
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.achievement_service import check_achievements
from services.combat_service import (
    CombatState,
    add_status,
    derive_player_stats,
    fmt_statuses,
    has_status,
    is_immobilised,
    roll_damage,
    tick_statuses,
)
from services.equipment_service import equipped_bonuses, try_drop, try_drop_material
from services.quest_service import update_quest_progress, update_weekly_quest_progress
from ui.combat_view import CombatView
from utils.embeds import combat_embed, end_combat_embed, error_embed

_INVENTORY_LIMIT = 20


def _load_enemies() -> list[dict]:
    path = Path(__file__).parent.parent / "data" / "enemies" / "common.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_ENEMIES: list[dict] = _load_enemies()


def _pick_enemy(player_level: int) -> dict:
    same  = [e for e in _ENEMIES if e["level"] == player_level]
    lower = [e for e in _ENEMIES if e["level"] < player_level]
    pool  = same or lower or _ENEMIES
    return random.choice(pool).copy()


class CombatCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.active_combats: dict[int, CombatState] = {}

    # ── Commands ─────────────────────────────────────────────────

    @discord.slash_command(name="fight", description="⚔️ 在當前區域尋找並挑戰敵人")
    async def fight(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)
        if char.is_in_combat or char.id in self.active_combats:
            return await ctx.respond(embed=error_embed("你已經在戰鬥中！"), ephemeral=True)
        if char.hp_current <= 0:
            return await ctx.respond(
                embed=error_embed("HP 歸零，無法戰鬥。使用 `/rest` 恢復體力。"), ephemeral=True
            )

        enemy = _pick_enemy(char.level)
        atk_b, def_b, hp_b, energy_b, crit_b = equipped_bonuses(
            char.equipped_weapon, char.equipped_armor,
            char.item_enhancements,
            char.equipped_helmet, char.equipped_accessory,
            char.custom_items,
        )
        base_atk, base_def = derive_player_stats(
            char.class_type, char.stat_vitality, char.stat_reflex, char.stat_tech, char.level
        )

        state = CombatState(
            discord_user_id=ctx.author.id,
            character_id=char.id,
            char_name=char.name,
            char_class=char.class_type.value,
            char_level=char.level,
            hp=char.hp_current,
            hp_max=char.hp_max,
            energy=char.energy_current,
            energy_max=char.energy_max,
            atk=base_atk + atk_b,
            def_=base_def + def_b,
            crit_bonus=crit_b,
            enemy=enemy,
            enemy_hp=enemy["hp"],
            medkits=char.medkits,
            energy_cells_in_combat=char.energy_cells,
            consumables_in_combat=dict(char.consumables or {}),
        )
        self.active_combats[char.id] = state

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == char.id))
            char_db = result.scalar_one()
            char_db.is_in_combat = True
            await session.commit()

        await ctx.respond(embed=combat_embed(state), view=CombatView(self, char.id, state))

    # ── Turn processing ──────────────────────────────────────────

    async def process_turn(
        self, interaction: discord.Interaction, character_id: int, action: str
    ) -> None:
        state = self.active_combats.get(character_id)
        if not state or state.is_over:
            return

        if interaction.user.id != state.discord_user_id:
            return await interaction.response.send_message("這不是你的戰鬥！", ephemeral=True)

        state.turn += 1
        logs: list[str] = []

        # Check enemy stun BEFORE ticking so the result isn't lost
        enemy_immobilised = is_immobilised(state.enemy_statuses) or state.enemy_stunned
        state.enemy_stunned = False

        # ── Tick enemy status effects (poison/burn/shock damage) ─
        state.enemy_hp, tick_logs = tick_statuses(
            state.enemy_statuses, state.enemy_hp, state.enemy["hp"]
        )
        for tl in tick_logs:
            logs.append(f"  {tl}")
        if state.enemy_hp <= 0:
            state.last_log = logs
            state.is_over  = True
            state.player_won = True
            await self._end_combat(interaction, state, "win")
            return

        enemy_acts = not enemy_immobilised

        # ── Process player action ────────────────────────────────
        if action == "flee":
            dodge_chance = 0.95 if has_status(state.player_statuses, "dodge_next") else 0.55
            # remove dodge_next
            state.player_statuses = [s for s in state.player_statuses if s["type"] != "dodge_next"]
            if random.random() < dodge_chance:
                state.last_log = ["成功逃脫！"]
                state.is_over  = True
                await self._end_combat(interaction, state, "flee")
                return
            logs.append("⚡ 逃跑失敗！")
            state.combo = 0

        elif action == "attack":
            # Apply ATK buff if active
            atk_mult = 1.0
            for s in state.player_statuses:
                if s["type"] == "atk_buff":
                    atk_mult = s["value"]
                    break

            # Combo bonus
            combo_mult = 1.0 + state.combo * COMBO_BONUS
            effective_atk = int(state.atk * atk_mult * combo_mult)

            dmg, crit = roll_damage(effective_atk, state.enemy["defense"], state.crit_bonus)
            state.enemy_hp    = max(0, state.enemy_hp - dmg)
            state.damage_dealt += dmg
            if crit:
                state.crits_landed += 1

            combo_txt = f"  🔥 連擊 ×{state.combo + 1}！" if state.combo >= 1 else ""
            crit_txt  = "  **💥 暴擊！**" if crit else ""
            logs.append(
                f"你攻擊 {state.enemy['emoji']} **{state.enemy['name']}**，"
                f"造成 **{dmg}** 點傷害！{crit_txt}{combo_txt}"
            )
            state.combo = min(COMBO_MAX, state.combo + 1)

            if state.enemy_hp <= 0:
                state.last_log = logs
                state.is_over  = True
                state.player_won = True
                await self._end_combat(interaction, state, "win")
                return

        elif action == "defend":
            if state.energy < DEFEND_ENERGY_COST:
                return await interaction.response.send_message("能量不足！", ephemeral=True)
            state.energy -= DEFEND_ENERGY_COST
            add_status(state.player_statuses, "defending", 1, 0.7)   # 70% damage reduction this turn
            logs.append(f"🛡️ 進入防禦姿態！（消耗 {DEFEND_ENERGY_COST} 能量，本回合受傷 -70%）")
            state.combo = 0

        elif action.startswith("skill_"):
            skill_id = action[len("skill_"):]
            skills   = CLASS_SKILLS[state.char_class]
            skill    = next((s for s in skills if s["id"] == skill_id), None)
            if not skill:
                return await interaction.response.send_message("技能不存在！", ephemeral=True)
            if state.energy < skill["energy_cost"]:
                return await interaction.response.send_message(
                    f"能量不足！需要 {skill['energy_cost']} 能量。", ephemeral=True
                )
            state.energy -= skill["energy_cost"]
            state.skills_used += 1
            logs.append(f"💠 使用技能 **{skill['name']}** {skill['emoji']}！（消耗 {skill['energy_cost']} 能量）")
            skill_logs, dmg_dealt, crit_count = _apply_skill(state, skill)
            logs.extend(skill_logs)
            state.damage_dealt += dmg_dealt
            state.crits_landed += crit_count
            state.combo = 0  # skills reset combo
            if state.enemy_hp <= 0:
                state.last_log = logs
                state.is_over  = True
                state.player_won = True
                await self._end_combat(interaction, state, "win")
                return

        elif action == "item_medkit":
            if state.medkits <= 0:
                return await interaction.response.send_message("沒有急救包！", ephemeral=True)
            heal = max(1, int(state.hp_max * MEDKIT_HEAL_PCT))
            state.hp = min(state.hp_max, state.hp + heal)
            state.medkits -= 1
            state.items_used_in_fight += 1
            logs.append(f"🩹 使用急救包，恢復 **{heal}** HP！（剩餘 {state.medkits} 個）")
            state.combo = 0

        elif action == "item_energy":
            if state.energy_cells_in_combat <= 0:
                return await interaction.response.send_message("沒有能量電池！", ephemeral=True)
            restore = min(ENERGY_CELL_RESTORE, state.energy_max - state.energy)
            state.energy = min(state.energy_max, state.energy + ENERGY_CELL_RESTORE)
            state.energy_cells_in_combat -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"🔋 使用能量電池，恢復 **{restore}** 能量！"
                f"（剩餘 {state.energy_cells_in_combat} 個）"
            )

        elif action == "item_stimulant":
            count = state.consumables_in_combat.get("stimulant", 0)
            if count <= 0:
                return await interaction.response.send_message("沒有興奮劑！", ephemeral=True)
            heal    = max(1, int(state.hp_max * STIMULANT_HEAL_PCT))
            restore = min(STIMULANT_ENERGY, state.energy_max - state.energy)
            state.hp     = min(state.hp_max, state.hp + heal)
            state.energy = min(state.energy_max, state.energy + STIMULANT_ENERGY)
            state.consumables_in_combat["stimulant"] -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"💉 使用興奮劑，恢復 **{heal}** HP + **{restore}** 能量！"
                f"（剩餘 {state.consumables_in_combat['stimulant']} 個）"
            )
            state.combo = 0

        elif action == "item_nano_repair":
            count = state.consumables_in_combat.get("nano_repair", 0)
            if count <= 0:
                return await interaction.response.send_message("沒有奈米修復劑！", ephemeral=True)
            add_status(state.player_statuses, "regen", NANO_REPAIR_TURNS, NANO_REPAIR_PCT)
            state.consumables_in_combat["nano_repair"] -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"🧬 啟動奈米修復劑！每回合恢復 {int(NANO_REPAIR_PCT * 100)}% HP，"
                f"持續 {NANO_REPAIR_TURNS} 回合！"
                f"（剩餘 {state.consumables_in_combat['nano_repair']} 個）"
            )
            state.combo = 0

        elif action == "item_adrenaline":
            count = state.consumables_in_combat.get("adrenaline", 0)
            if count <= 0:
                return await interaction.response.send_message("沒有腎上腺素！", ephemeral=True)
            add_status(state.player_statuses, "atk_buff", ADRENALINE_DURATION, ADRENALINE_ATK_MULT)
            state.consumables_in_combat["adrenaline"] -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"💊 注射腎上腺素！ATK +{int((ADRENALINE_ATK_MULT - 1) * 100)}%，"
                f"持續 {ADRENALINE_DURATION} 回合！"
                f"（剩餘 {state.consumables_in_combat['adrenaline']} 個）"
            )
            state.combo = 0

        elif action == "item_shield_chip":
            count = state.consumables_in_combat.get("shield_chip", 0)
            if count <= 0:
                return await interaction.response.send_message("沒有護盾晶片！", ephemeral=True)
            add_status(state.player_statuses, "dodge_next", 1, 0.0)
            state.consumables_in_combat["shield_chip"] -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"🔰 啟動護盾晶片，將抵擋下一次敵人攻擊！"
                f"（剩餘 {state.consumables_in_combat['shield_chip']} 個）"
            )
            state.combo = 0

        elif action == "item_corrosive_vial":
            count = state.consumables_in_combat.get("corrosive_vial", 0)
            if count <= 0:
                return await interaction.response.send_message("沒有腐蝕瓶！", ephemeral=True)
            add_status(state.enemy_statuses, "poison", CORROSIVE_VIAL_TURNS, CORROSIVE_VIAL_PCT)
            state.consumables_in_combat["corrosive_vial"] -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"🧪 投擲腐蝕瓶！{state.enemy['emoji']} **{state.enemy['name']}** 中毒 "
                f"{CORROSIVE_VIAL_TURNS} 回合！"
                f"（剩餘 {state.consumables_in_combat['corrosive_vial']} 個）"
            )
            state.combo = 0

        elif action == "item_emp_grenade":
            count = state.consumables_in_combat.get("emp_grenade", 0)
            if count <= 0:
                return await interaction.response.send_message("沒有電磁脈衝彈！", ephemeral=True)
            add_status(state.enemy_statuses, "stun", EMP_GRENADE_STUN, 0.0)
            state.consumables_in_combat["emp_grenade"] -= 1
            state.items_used_in_fight += 1
            logs.append(
                f"⚡ 引爆電磁脈衝彈！{state.enemy['emoji']} **{state.enemy['name']}** "
                f"被癱瘓 {EMP_GRENADE_STUN} 回合！"
                f"（剩餘 {state.consumables_in_combat['emp_grenade']} 個）"
            )
            state.combo = 0

        # ── Enemy counter-attack (check player buffs BEFORE ticking) ─
        if enemy_immobilised:
            logs.append(
                f"{state.enemy['emoji']} **{state.enemy['name']}** 系統被癱瘓，本回合無法行動！"
            )
        elif enemy_acts:
            e_dmg, e_crit = roll_damage(state.enemy["attack"], state.def_)

            # Check player defending (must be checked before tick removes it)
            defending = any(s["type"] == "defending" for s in state.player_statuses)
            if defending:
                reduction = next(s["value"] for s in state.player_statuses if s["type"] == "defending")
                e_dmg_reduced = max(1, int(e_dmg * (1.0 - reduction)))
                counter_dmg, _ = roll_damage(int(state.atk * 0.5), state.enemy["defense"])
                state.enemy_hp = max(0, state.enemy_hp - counter_dmg)
                state.damage_dealt += counter_dmg
                logs.append(
                    f"{state.enemy['emoji']} **{state.enemy['name']}** 攻擊你，"
                    f"傷害 **{e_dmg}** → 防禦後僅 **{e_dmg_reduced}**！"
                    f"🛡️ 反擊 **{counter_dmg}** 傷害！"
                )
                e_dmg = e_dmg_reduced
                state.player_statuses = [s for s in state.player_statuses if s["type"] != "defending"]
            elif has_status(state.player_statuses, "dodge_next"):
                e_dmg = 0
                logs.append(
                    f"{state.enemy['emoji']} **{state.enemy['name']}** 攻擊你，**閃避成功！**"
                )
                state.player_statuses = [s for s in state.player_statuses if s["type"] != "dodge_next"]
            else:
                e_crit_txt = "  **💥 暴擊！**" if e_crit else ""
                logs.append(
                    f"{state.enemy['emoji']} **{state.enemy['name']}** 攻擊你，"
                    f"造成 **{e_dmg}** 點傷害！{e_crit_txt}"
                )

            state.hp = max(0, state.hp - e_dmg)
            if state.enemy_hp <= 0:
                state.last_log = logs
                state.is_over  = True
                state.player_won = True
                await self._end_combat(interaction, state, "win")
                return

        # ── Tick player status effects (ATK buff, etc.) ──────────
        state.hp, p_tick_logs = tick_statuses(
            state.player_statuses, state.hp, state.hp_max
        )
        for tl in p_tick_logs:
            logs.append(f"  {tl}")

        state.last_log = logs

        if state.hp <= 0:
            state.is_over = True
            await self._end_combat(interaction, state, "lose")
            return

        await interaction.response.edit_message(
            embed=combat_embed(state), view=CombatView(self, character_id, state)
        )

    # ── Timeout handler ──────────────────────────────────────────

    async def handle_timeout(self, character_id: int) -> None:
        state = self.active_combats.pop(character_id, None)
        if not state:
            return
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == character_id))
            char = result.scalar_one_or_none()
            if char:
                char.is_in_combat = False
                await session.commit()

    # ── End combat ───────────────────────────────────────────────

    async def _end_combat(
        self, interaction: discord.Interaction, state: CombatState, outcome: str
    ) -> None:
        exp_gain = credits_gain = 0
        leveled_up = False
        new_level  = state.char_level
        drop: dict | None   = None
        mat_drop: dict | None = None
        new_achievements: list[str] = []

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == state.character_id))
            char = result.scalar_one()
            char.is_in_combat   = False
            char.hp_current     = max(1, state.hp)
            char.energy_current = state.energy
            char.medkits        = state.medkits
            char.energy_cells   = state.energy_cells_in_combat
            char.consumables    = state.consumables_in_combat

            # ── Quest / weekly updates (batch) ────────────────────
            def _q(t: str, n: int) -> None:
                update_quest_progress(char, t, n)
                update_weekly_quest_progress(char, t, n)

            if state.damage_dealt > 0:
                _q("deal_damage", state.damage_dealt)
            if state.crits_landed > 0:
                _q("land_crits", state.crits_landed)
            if state.skills_used > 0:
                _q("use_skill", state.skills_used)
            if state.items_used_in_fight > 0:
                _q("use_items_combat", state.items_used_in_fight)

            if outcome == "win":
                exp_gain     = state.enemy["exp_reward"]
                credits_gain = random.randint(state.enemy["credits_min"], state.enemy["credits_max"])
                char.exp     += exp_gain
                char.credits += credits_gain
                char.kills   += 1

                _q("kill_enemies", 1)
                _q("earn_credits", credits_gain)
                if state.items_used_in_fight == 0:
                    _q("win_without_items", 1)

                # Equipment drop
                drop = try_drop(state.enemy["level"])
                if drop:
                    inv = list(char.inventory or [])
                    if len(inv) < _INVENTORY_LIMIT:
                        inv.append(drop["id"])
                        char.inventory = inv
                        _q("loot_equipment", 1)
                    else:
                        drop = None

                # Material drop
                mat_drop = try_drop_material(state.enemy["level"])
                if mat_drop:
                    mats = dict(char.materials or {})
                    mats[mat_drop["id"]] = mats.get(mat_drop["id"], 0) + 1
                    char.materials = mats

                while char.exp >= exp_for_next_level(char.level) and char.level < MAX_LEVEL:
                    char.exp -= exp_for_next_level(char.level)
                    char.level += 1
                    char.stat_points_avail += STAT_POINTS_PER_LEVEL
                    char.hp_max     += 10
                    char.energy_max += 5
                    char.hp_current  = char.hp_max
                    leveled_up = True
                    new_level  = char.level

            elif outcome == "flee":
                _q("flee_success", 1)

            elif outcome == "lose":
                char.hp_current = max(1, char.hp_max // 4)

            # ── Check achievements ────────────────────────────────
            new_achievements = check_achievements(char)

            await session.commit()

        self.active_combats.pop(state.character_id, None)
        embed = end_combat_embed(
            state, outcome, exp_gain, credits_gain, leveled_up, new_level,
            drop, mat_drop, new_achievements
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ── Skill dispatch ───────────────────────────────────────────────

def _apply_skill(
    state: CombatState, skill: dict
) -> tuple[list[str], int, int]:
    """Returns (log_lines, total_damage, crit_count).
    Status effects are applied directly to state; immobilise goes via enemy_statuses.
    """
    logs:       list[str] = []
    total_dmg  = 0
    crit_count = 0
    sid        = skill["id"]
    name       = skill["name"]

    # ── Street Samurai ───────────────────────────────────────────
    if sid == "berserker_slash":
        dmg, _ = roll_damage(state.atk * 2, state.enemy["defense"], state.crit_bonus)
        state.enemy_hp = max(0, state.enemy_hp - dmg)
        total_dmg = dmg
        logs.append(
            f"🗡️ **{name}**：對 {state.enemy['emoji']} **{state.enemy['name']}** 造成 **{dmg}** 點傷害！"
        )

    elif sid == "iron_wall":
        add_status(state.player_statuses, "defending", 1, 0.7)
        # Counter-attack at 50% ATK
        counter_dmg, _ = roll_damage(int(state.atk * 0.5), state.enemy["defense"])
        state.enemy_hp  = max(0, state.enemy_hp - counter_dmg)
        state.damage_dealt += counter_dmg
        total_dmg = counter_dmg
        logs.append(
            f"🛡️ **{name}**：防禦姿態啟動！本回合傷害 -70%，反擊 **{counter_dmg}** 傷害。"
        )

    elif sid == "cyber_overdrive":
        # ATK × 1.5 for 3 turns
        add_status(state.player_statuses, "atk_buff", 3, 1.5)
        logs.append(
            f"⚡ **{name}**：義體超頻！ATK ×1.5，持續 **3 回合**。"
        )

    # ── Netrunner ────────────────────────────────────────────────
    elif sid == "neural_hack":
        dmg, crit = roll_damage(state.atk, state.enemy["defense"], state.crit_bonus)
        state.enemy_hp = max(0, state.enemy_hp - dmg)
        total_dmg  = dmg
        crit_count = 1 if crit else 0
        add_status(state.enemy_statuses, "stun_hack", 1, 0.0)   # prevents next-turn attack
        crit_txt = "  **💥 暴擊！**" if crit else ""
        logs.append(
            f"💀 **{name}**：造成 **{dmg}** 點傷害！{crit_txt} 敵人系統被駭入——**下回合無法行動**！"
        )

    elif sid == "virus_inject":
        # Poison for 3 turns, 8% HP/turn
        add_status(state.enemy_statuses, "poison", 3, 0.08)
        logs.append(
            f"🦠 **{name}**：病毒植入成功！敵人每回合損失 **8%** HP，持續 **3 回合**。"
        )

    elif sid == "emp_blast":
        dmg, crit = roll_damage(int(state.atk * 1.5), state.enemy["defense"], state.crit_bonus)
        state.enemy_hp = max(0, state.enemy_hp - dmg)
        total_dmg  = dmg
        crit_count = 1 if crit else 0
        # Shock: 2 turns, 5% HP/turn
        add_status(state.enemy_statuses, "shock", 2, 0.05)
        crit_txt = "  **💥 暴擊！**" if crit else ""
        logs.append(
            f"🔌 **{name}**：造成 **{dmg}** 點傷害！{crit_txt} 感電 2 回合（每回合 -5% HP）。"
        )

    # ── Scavenger ────────────────────────────────────────────────
    elif sid == "quick_strike":
        dmg1, c1 = roll_damage(state.atk, state.enemy["defense"], state.crit_bonus)
        dmg2, c2 = roll_damage(state.atk, state.enemy["defense"], state.crit_bonus)
        state.enemy_hp = max(0, state.enemy_hp - dmg1 - dmg2)
        total_dmg  = dmg1 + dmg2
        crit_count = (1 if c1 else 0) + (1 if c2 else 0)
        c1_txt = " 💥" if c1 else ""
        c2_txt = " 💥" if c2 else ""
        logs.append(
            f"⚡ **{name}**：兩段連擊！"
            f"第一擊 **{dmg1}**{c1_txt} + 第二擊 **{dmg2}**{c2_txt} = 總計 **{total_dmg}** 傷害！"
        )

    elif sid == "smoke_bomb":
        add_status(state.player_statuses, "dodge_next", 1, 0.0)
        logs.append(
            f"💨 **{name}**：投出煙霧彈！規避下次攻擊，逃跑成功率提升至 **95%**。"
        )

    elif sid == "poison_blade":
        dmg, crit = roll_damage(state.atk, state.enemy["defense"], state.crit_bonus)
        state.enemy_hp = max(0, state.enemy_hp - dmg)
        total_dmg  = dmg
        crit_count = 1 if crit else 0
        add_status(state.enemy_statuses, "poison", 3, 0.06)
        crit_txt = "  **💥 暴擊！**" if crit else ""
        logs.append(
            f"🗡️ **{name}**：造成 **{dmg}** 點傷害！{crit_txt} 敵人中毒 3 回合（每回合 -6% HP）。"
        )

    return logs, total_dmg, crit_count


def setup(bot: discord.Bot) -> None:
    bot.add_cog(CombatCog(bot))
