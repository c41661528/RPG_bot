import asyncio
import logging

import discord
from discord.ext import bridge, commands

from config import DISCORD_TOKEN
from database.session import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rpg_bot")

COGS = [
    "cogs.character",
    "cogs.combat",
    "cogs.shop",
    "cogs.inventory",
    "cogs.exploration",
    "cogs.progression",
    "cogs.quests",
    "cogs.enhance",
    "cogs.dungeon",
    "cogs.achievements",
    "cogs.help",
    "cogs.gear_shop",
    "cogs.titles",
    "cogs.craft",
    "cogs.pvp",
]

intents = discord.Intents.default()
intents.message_content = True
bot = bridge.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    # When replying to a `!` prefix command, don't ping the author.
    allowed_mentions=discord.AllowedMentions(replied_user=False),
)


@bot.event
async def on_ready() -> None:
    guild_ids = [g.id for g in bot.guilds]
    await bot.sync_commands(guild_ids=guild_ids)
    log.info(f"Online as {bot.user}  |  {len(bot.guilds)} guild(s)  |  Synced to {guild_ids}")


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    await bot.sync_commands(guild_ids=[guild.id])
    log.info(f"Joined guild: {guild.name} ({guild.id})  |  Commands synced")


async def main() -> None:
    await init_db()
    log.info("Database initialised")

    for cog in COGS:
        bot.load_extension(cog)
        log.info(f"Loaded: {cog}")

    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
