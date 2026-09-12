import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict
import discord
from discord.ext import commands

from db.database import Database
from db.models import Commitment, CommitmentStatus, DiningInquiry, DiningInquiryStatus
from llm.extractor import CommitmentExtractor
from pipeline.filter import is_commitment_candidate, is_dining_inquiry
from bot.ui.embeds import (
    create_commitment_embed,
    create_dining_prompt_embed,
    create_already_accepted_plan_embed
)
from bot.ui.views import CommitmentActionView
from bot.ui.dining_views import DiningCuisineSelectionView, AlreadyAcceptedPlanView
from config import settings

logger = logging.getLogger("CommitmentRadar.Events")


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database, extractor: CommitmentExtractor):
        self.bot = bot
        self.db = db
        self.extractor = extractor
        self.active_inquiry_timers: Dict[str, asyncio.Task] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot:
            return

        channel_id_str = str(message.channel.id)

        # If someone sends a follow-up message in a channel that has an active waiting inquiry,
        # cancel the auto-intervention timer because human conversation is already active.
        if channel_id_str in self.active_inquiry_timers:
            active_task = self.active_inquiry_timers.pop(channel_id_str, None)
            if active_task and not active_task.done():
                active_task.cancel()
                logger.info(f"Subsequent message in channel {channel_id_str}; cancelled pending dining auto-prompt.")
                # Update status in DB
                inquiry = await self.db.get_active_dining_inquiry_for_channel(channel_id_str)
                if inquiry and inquiry.id is not None:
                    await self.db.update_dining_inquiry_status(inquiry.id, DiningInquiryStatus.ANSWERED)

        # 1. Check for Dining Inquiries (e.g. "where you want to eat", "what is the dinner plan?")
        is_dining, dining_reason = is_dining_inquiry(message.content)
        if is_dining:
            logger.info(f"Dining inquiry detected ('{dining_reason}') from {message.author.name}: \"{message.content}\"")
            try:
                # Add subtle reaction
                try:
                    await message.add_reaction("🍽️")
                except Exception as re:
                    logger.debug(f"Could not add reaction: {re}")

                # Record inquiry in DB
                inquiry = DiningInquiry(
                    channel_id=channel_id_str,
                    message_id=str(message.id),
                    user_id=str(message.author.id),
                    user_name=message.author.display_name,
                    guild_id=str(message.guild.id) if message.guild else None,
                    raw_text=message.content,
                    status=DiningInquiryStatus.WAITING
                )
                saved_inquiry = await self.db.add_dining_inquiry(inquiry)

                # --- Check messages in the last 3 minutes only for an already accepted plan ---
                window_mins = settings.dining_history_window_minutes
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_mins)

                # 1. Check recent chat history in the channel (last 3 minutes only)
                recent_chat = []
                try:
                    async for prev_msg in message.channel.history(limit=25, after=cutoff, oldest_first=True):
                        if not prev_msg.author.bot and prev_msg.id != message.id and prev_msg.content.strip():
                            recent_chat.append(f"{prev_msg.author.display_name}: {prev_msg.content}")
                except Exception as he:
                    logger.debug(f"Could not fetch channel history: {he}")

                # 2. Check recent chat history (last 3 minutes only)
                agreed_plan_name = None
                quote = None
                source_desc = "earlier"

                if recent_chat:
                    plan_check = await self.extractor.check_for_accepted_plan(recent_chat)
                    if plan_check.has_accepted_plan and plan_check.agreed_plan:
                        agreed_plan_name = plan_check.agreed_plan
                        quote = plan_check.context_quote
                        source_desc = f"agreed in chat in the last {window_mins} minutes"

                # 3. Check if an accepted plan was saved in DB for this channel (within last 4 hours)
                if not agreed_plan_name:
                    recent_resolved = await self.db.get_recent_resolved_dining_inquiry(
                        channel_id=channel_id_str,
                        within_minutes=settings.accepted_plan_memory_hours * 60
                    )
                    if recent_resolved and recent_resolved.chosen_cuisine:
                        agreed_plan_name = recent_resolved.chosen_cuisine
                        quote = f"Confirmed previously by {recent_resolved.user_name}: '{recent_resolved.raw_text}'"
                        source_desc = "confirmed earlier today"

                # If an accepted plan was found, bring it back up immediately!
                if agreed_plan_name:
                    logger.info(f"Found accepted dinner plan '{agreed_plan_name}' ({source_desc}) in channel {channel_id_str}. Bringing it up!")
                    embed = create_already_accepted_plan_embed(
                        user_id=str(message.author.id),
                        agreed_plan=agreed_plan_name,
                        quote=quote,
                        source=source_desc
                    )
                    view = AlreadyAcceptedPlanView(
                        inquiry=saved_inquiry,
                        agreed_plan=agreed_plan_name,
                        db=self.db,
                        extractor=self.extractor
                    )
                    await message.reply(embed=embed, view=view, mention_author=False)
                    return

                # Otherwise, start standard silence countdown timer (15s)
                timeout = settings.dining_inquiry_timeout_seconds
                timer_task = asyncio.create_task(
                    self._wait_and_prompt_dining(
                        channel=message.channel,
                        inquiry=saved_inquiry,
                        timeout_seconds=timeout
                    )
                )
                self.active_inquiry_timers[channel_id_str] = timer_task
                logger.info(f"Started {timeout}s countdown for dining inquiry #{saved_inquiry.id} in channel {channel_id_str}")
            except Exception as de:
                logger.error(f"Error handling dining inquiry: {de}", exc_info=True)

        # 2. Check for Commitments (Commitment Radar logic)
        is_candidate, reason = is_commitment_candidate(message.content)
        if not is_candidate:
            return

        logger.info(f"Candidate matched ('{reason}'): {message.author.name}: \"{message.content}\"")

        # Call Hermes Extractor
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
                channel_id=channel_id_str,
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

            # Send confirmation embed with quick action buttons
            embed = create_commitment_embed(saved_commitment, is_alert=False)
            view = CommitmentActionView(saved_commitment, self.db, self.extractor)

            # Post confirmation as reply in channel
            await message.reply(embed=embed, view=view, mention_author=False)

        except Exception as e:
            logger.error(f"Error processing message for commitments: {e}", exc_info=True)

    async def _wait_and_prompt_dining(
        self,
        channel: discord.abc.Messageable,
        inquiry: DiningInquiry,
        timeout_seconds: int
    ):
        """Waits for the timeout and posts the dining assistance prompt if silence persisted."""
        try:
            await asyncio.sleep(timeout_seconds)

            logger.info(f"Silence timeout reached ({timeout_seconds}s) for inquiry #{inquiry.id} in channel {inquiry.channel_id}. Intervening...")
            if inquiry.id is not None:
                await self.db.update_dining_inquiry_status(inquiry.id, DiningInquiryStatus.TIMED_OUT)

            embed = create_dining_prompt_embed(inquiry, timeout_seconds=timeout_seconds)
            view = DiningCuisineSelectionView(inquiry, self.db, self.extractor)

            await channel.send(
                content=f"🔔 <@{inquiry.user_id}>",
                embed=embed,
                view=view
            )
        except asyncio.CancelledError:
            logger.debug(f"Dining silence timer cancelled for channel {inquiry.channel_id}")
        except Exception as e:
            logger.error(f"Error sending dining prompt after timeout: {e}", exc_info=True)
        finally:
            self.active_inquiry_timers.pop(inquiry.channel_id, None)


async def setup(bot: commands.Bot, db: Database, extractor: CommitmentExtractor):
    await bot.add_cog(EventsCog(bot, db, extractor))
