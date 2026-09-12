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

        self.tree.on_error = self.on_tree_error

        # Sync commands in background task to prevent blocking gateway login if rate-limited
        asyncio.create_task(self._sync_commands())

    async def on_tree_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        logger.error(f"Command error in {interaction.command}: {error}", exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ Error executing command: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Error executing command: {error}", ephemeral=True)
        except Exception:
            pass

    async def _sync_commands(self):
        try:
            logger.info("Syncing application slash commands globally...")
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} application slash commands globally.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands globally: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds.")
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(f"Instantly synced {len(synced)} slash commands to guild: '{guild.name}' (ID: {guild.id})")
            except Exception as e:
                logger.warning(f"Could not guild-sync to '{guild.name}' ({guild.id}): {e}")

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="chats for micro-commitments"
        )
        await self.change_presence(activity=activity)
