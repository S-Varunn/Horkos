import asyncio
import logging
import discord
from discord.ext import commands

from db.database import Database
from llm.extractor import CommitmentExtractor
from integrations.calendar_service import GoogleCalendarService
from bot.cogs import events, commands as bot_commands

logger = logging.getLogger("CommitmentRadar.Bot")


class CommitmentRadarBot(commands.Bot):
    def __init__(
        self,
        db: Database,
        extractor: CommitmentExtractor,
        calendar_service: Optional[GoogleCalendarService] = None
    ):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self.db = db
        self.extractor = extractor
        self.calendar_service = calendar_service

    async def setup_hook(self):
        """Called automatically before the bot connects to Discord."""
        logger.info("Registering cogs...")
        await events.setup(self, self.db, self.extractor, self.calendar_service)
        await bot_commands.setup(self, self.db, self.extractor, self.calendar_service)

        # Sync commands in background task to prevent blocking gateway login if rate-limited
        asyncio.create_task(self._sync_commands())

    async def _sync_commands(self):
        try:
            logger.info("Syncing application slash commands...")
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} application slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds.")
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="chats for micro-commitments"
        )
        await self.change_presence(activity=activity)
