import os
import sys

# Ensure current project directory is in python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import asyncio
import logging
from typing import List

import discord
from discord.ext import commands

from core.config import TOKEN
from core.database import (
    load_guild_configs_from_supabase,
    load_all_tournaments_from_supabase,
    load_all_staff_stats_from_supabase,
    load_all_deadlines_from_supabase,
    load_scheduled_deadlines
)



# Set Windows-compatible asyncio loop policy
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as e:
        print(f"Warning: Could not set WindowsProactorEventLoopPolicy: {e}")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tournament_bot")

# Intents configuration
intents = discord.Intents.all()

class TournamentBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self.initial_extensions: List[str] = [
            "cogs.utilities",
            "cogs.settings",
            "cogs.staff",
            "cogs.tournaments",
            "cogs.events",
            "cogs.listeners"
        ]

    async def setup_hook(self):
        """Called automatically before the bot connects to Discord."""
        logger.info("⏳ Initializing database cache from Supabase...")
        try:
            load_scheduled_deadlines()
            await load_guild_configs_from_supabase()
            await load_all_tournaments_from_supabase()
            await load_all_staff_stats_from_supabase()
            await load_all_deadlines_from_supabase()
            logger.info("✅ Database caches loaded successfully.")
        except Exception as e:
            logger.warning(f"⚠️ Could not load remote cache from Supabase: {e}")

        logger.info("🔌 Loading Cogs and Extensions...")
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"  └─ Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"  └─ Failed to load extension {ext}: {e}", exc_info=True)

def main():

    if not TOKEN:
        logger.error("❌ DISCORD_BOT_TOKEN / DISCORD_TOKEN is not set in environment or config!")
        sys.exit(1)

    bot = TournamentBot()
    logger.info("🚀 Starting Tournament Bot...")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
