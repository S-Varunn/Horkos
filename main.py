import asyncio
import logging
import os
import signal
import sys
import discord

# Relax token scope checks for Google OAuth
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from config import settings
from db.database import Database
from db.models import Commitment
from llm.extractor import CommitmentExtractor
from scheduler.service import AlertScheduler
from bot.client import CommitmentRadarBot
from bot.ui.embeds import create_commitment_embed
from bot.ui.views import CommitmentActionView
from integrations.calendar_service import GoogleCalendarService
from integrations.oauth_server import OAuthCallbackServer

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("CommitmentRadar.Main")


async def main():
    if not settings.discord_token:
        logger.warning(
            "DISCORD_TOKEN is not set in environment or .env! "
            "Please configure DISCORD_TOKEN to connect to Discord."
        )

    # 1. Initialize Database
    db = Database(settings.database_path)
    logger.info(f"Initializing SQLite database at {settings.database_path}...")
    await db.init_db()

    # 2. Initialize Hermes LLM Extractor
    logger.info(f"Initializing LLM Extractor (Model: {settings.llm_model})...")
    extractor = CommitmentExtractor()

    # 3. Initialize Google Calendar Service (Per-User Manager)
    logger.info("Initializing Google Calendar Service...")
    calendar_service = GoogleCalendarService(db=db)

    # 4. Start embedded OAuth Callback Server for multi-user sign-ins
    oauth_server = OAuthCallbackServer(
        port=settings.google_oauth_port,
        token_handler=calendar_service.handle_oauth_code
    )
    await oauth_server.start()

    # 5. Initialize Discord Bot
    bot = CommitmentRadarBot(db=db, extractor=extractor, calendar_service=calendar_service)

    # 5. Define alert callback when deadline is within advance window (e.g. 30m)
    async def send_deadline_alert(commitment: Commitment):
        logger.info(f"Triggering proactive alert for commitment #{commitment.id}")
        try:
            channel = bot.get_channel(int(commitment.channel_id))
            if not channel:
                try:
                    channel = await bot.fetch_channel(int(commitment.channel_id))
                except Exception as fe:
                    logger.warning(f"Could not fetch channel {commitment.channel_id}: {fe}")
                    return

            embed = create_commitment_embed(commitment, is_alert=True)
            view = CommitmentActionView(commitment, db, extractor, calendar_service)
            
            await channel.send(
                content=f"🔔 <@{commitment.user_id}> Gentle reminder regarding your commitment:",
                embed=embed,
                view=view
            )
        except Exception as e:
            logger.error(f"Failed to deliver alert for commitment #{commitment.id}: {e}", exc_info=True)

    # 5. Initialize Temporal Scheduler
    scheduler = AlertScheduler(
        db=db,
        alert_callback=send_deadline_alert,
        check_interval_seconds=settings.check_interval_seconds,
        alert_advance_minutes=settings.alert_advance_minutes
    )

    # Graceful shutdown handler
    loop = asyncio.get_running_loop()

    def shutdown():
        logger.info("Shutdown signal received. Cleaning up...")
        scheduler.stop()
        asyncio.create_task(oauth_server.stop())
        asyncio.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass  # Signal handlers might not be fully supported on some non-Unix platforms

    # Start the background alert scheduler
    scheduler.start()

    # Start Discord Bot
    if settings.discord_token:
        try:
            await bot.start(settings.discord_token)
        except discord.LoginFailure:
            logger.error("Invalid Discord Token provided. Check your DISCORD_TOKEN setting.")
        except Exception as e:
            logger.error(f"Bot encountered an error: {e}")
        finally:
            scheduler.stop()
            await oauth_server.stop()
    else:
        logger.info("Bot startup bypassed because DISCORD_TOKEN is not set.")
        logger.info("Base app modules (DB, LLM, Filter, Scheduler) are ready for testing.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
        sys.exit(0)
