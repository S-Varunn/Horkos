import logging
from datetime import datetime
import discord
from discord.ext import commands

from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from pipeline.filter import is_commitment_candidate
from bot.ui.embeds import create_commitment_embed
from bot.ui.views import CommitmentActionView

logger = logging.getLogger("CommitmentRadar.Events")


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database, extractor: CommitmentExtractor):
        self.bot = bot
        self.db = db
        self.extractor = extractor

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot:
            return

        # Stage 1: Fast Heuristic Pre-filter (0 tokens, 0ms latency)
        is_candidate, reason = is_commitment_candidate(message.content)
        if not is_candidate:
            return

        logger.info(f"Candidate matched ('{reason}'): {message.author.name}: \"{message.content}\"")

        # Stage 2: Call Hermes Extractor
        try:
            extracted = await self.extractor.extract_commitment(
                message_text=message.content,
                author_name=message.author.display_name,
                reference_time=datetime.utcnow()
            )

            if not extracted.is_commitment:
                logger.info(f"LLM determined non-commitment for: \"{message.content}\"")
                return

            # Parse deadline string to datetime
            deadline_dt = datetime.fromisoformat(extracted.implied_deadline_utc.replace("Z", "+00:00"))
            # Make naive UTC datetime for sqlite consistency
            deadline_dt = deadline_dt.replace(tzinfo=None)

            # Persist to database
            commitment = Commitment(
                user_id=str(message.author.id),
                user_name=message.author.display_name,
                channel_id=str(message.channel.id),
                guild_id=str(message.guild.id) if message.guild else None,
                message_id=str(message.id),
                raw_text=message.content,
                task_title=extracted.task_title,
                recipient=extracted.recipient,
                deadline_utc=deadline_dt,
                relative_deadline_text=extracted.relative_deadline_text,
                context_snippet=extracted.context_snippet,
                status=CommitmentStatus.PENDING
            )
            saved_commitment = await self.db.add_commitment(commitment)
            logger.info(f"Registered commitment #{saved_commitment.id}: '{saved_commitment.task_title}'")

            # Passive UX: Add subtle reaction to the user's message
            try:
                await message.add_reaction("🎯")
            except Exception as re:
                logger.debug(f"Could not add reaction: {re}")

            # Send ephemeral or subtle confirmation embed with quick action buttons
            embed = create_commitment_embed(saved_commitment, is_alert=False)
            view = CommitmentActionView(saved_commitment, self.db, self.extractor)

            # Post confirmation as reply in channel
            await message.reply(embed=embed, view=view, mention_author=False)

        except Exception as e:
            logger.error(f"Error processing message for commitments: {e}", exc_info=True)


async def setup(bot: commands.Bot, db: Database, extractor: CommitmentExtractor):
    await bot.add_cog(EventsCog(bot, db, extractor))
