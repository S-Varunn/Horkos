import logging
from datetime import datetime
import discord
from discord.ext import commands

from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from pipeline.filter import is_commitment_candidate
from pipeline.fulfillment import is_fulfillment_candidate, FulfillmentDetector
from bot.ui.embeds import create_commitment_embed
from bot.ui.views import CommitmentActionView
from integrations.calendar_service import GoogleCalendarService
from integrations.webhook_service import WebhookDispatcher
from config import settings

logger = logging.getLogger("CommitmentRadar.Events")


class EventsCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        db: Database,
        extractor: CommitmentExtractor,
        calendar_service: Optional[GoogleCalendarService] = None,
        webhook_dispatcher: Optional[WebhookDispatcher] = None
    ):
        self.bot = bot
        self.db = db
        self.extractor = extractor
        self.calendar_service = calendar_service
        self.fulfillment_detector = FulfillmentDetector(client=extractor.client)
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot:
            return

        # Text command fallbacks (in case slash commands haven't refreshed in Discord client yet)
        content_stripped = message.content.strip()
        lower_content = content_stripped.lower()

        if lower_content in ("/calendar-connect", "!calendar-connect", "!connect", "/connect"):
            if self.calendar_service and self.calendar_service.enabled:
                auth_url = self.calendar_service.get_authorization_url(str(message.author.id))
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Sign In with Google", url=auth_url, emoji="🌐"))
                await message.reply(
                    f"🔗 **Link your personal Google Calendar, {message.author.display_name}:**\n"
                    "1. Click the button below to sign in with Google.\n"
                    "2. Grant calendar permissions to Commitment Radar.\n"
                    "3. Once linked, commitments you make will automatically sync to your personal calendar!\n\n"
                    "*(Or copy the authorization code from Google and type: `!calendar-auth <code>`)*",
                    view=view
                )
            else:
                await message.reply("❌ Google Calendar integration is disabled.")
            return

        if lower_content in ("/calendar-status", "!calendar-status", "!status"):
            user_auth = await self.db.get_user_google_auth(str(message.author.id))
            if user_auth:
                await message.reply(f"🟢 **Google Calendar Connected** ({user_auth.google_email})")
            else:
                await message.reply("🟡 **Google Calendar Not Connected**\nType `/calendar-connect` or `!calendar-connect` to link your calendar.")
            return

        if lower_content.startswith(("/calendar-auth", "!calendar-auth")):
            parts = content_stripped.split(maxsplit=1)
            if len(parts) > 1 and self.calendar_service:
                code = parts[1].strip()
                result = await self.calendar_service.handle_oauth_code(code, str(message.author.id))
                if result.get("success"):
                    email_info = f" ({result['email']})" if result.get("email") else ""
                    await message.reply(f"✅ **Google Calendar Connected!**{email_info}")
                else:
                    await message.reply(f"❌ Failed to connect Google Calendar: {result.get('error', 'Unknown error')}")
            else:
                await message.reply("Usage: `!calendar-auth <authorization_code>`")
            return

        user_id = str(message.author.id)

        # Feature 1: Auto-Fulfillment Detection
        # Check if the message fulfills an existing active commitment
        try:
            active_commitments = await self.db.get_active_commitments_for_user(user_id)
            if active_commitments:
                has_attachments = bool(message.attachments)
                if is_fulfillment_candidate(message.content, has_attachments=has_attachments):
                    attachment_names = [a.filename for a in message.attachments] if has_attachments else None
                    fulfillment_res = await self.fulfillment_detector.evaluate_fulfillment(
                        message_text=message.content,
                        speaker_name=message.author.display_name,
                        pending_commitments=active_commitments,
                        attachments=attachment_names
                    )

                    if fulfillment_res.is_fulfilled and fulfillment_res.matched_commitment_id:
                        matched = next((c for c in active_commitments if c.id == fulfillment_res.matched_commitment_id), None)
                        if matched:
                            logger.info(f"Auto-fulfillment detected: #{matched.id} ('{matched.task_title}') by {message.author.name}")
                            await self.db.update_status(matched.id, CommitmentStatus.COMPLETED)

                            if self.calendar_service and matched.calendar_event_id:
                                try:
                                    await self.calendar_service.complete_event(
                                        event_id=matched.calendar_event_id,
                                        task_title=matched.task_title,
                                        discord_user_id=user_id,
                                        channel_id=str(message.channel.id)
                                    )
                                except Exception as ce:
                                    logger.warning(f"Could not complete calendar event: {ce}")

                            await self.webhook_dispatcher.dispatch(
                                event_type="commitment.completed",
                                commitment=matched,
                                extra_data={"fulfilled_message": message.content, "reason": fulfillment_res.reason}
                            )

                            try:
                                await message.add_reaction("✅")
                            except Exception as re:
                                logger.debug(f"Could not add reaction: {re}")
                            return
        except Exception as fe:
            logger.error(f"Error in auto-fulfillment pipeline: {fe}", exc_info=True)

        # Stage 1: Fast Heuristic Pre-filter (0 tokens, 0ms latency)
        is_candidate, reason = is_commitment_candidate(message.content)
        if not is_candidate:
            return

        logger.info(f"Candidate matched ('{reason}'): {message.author.name}: \"{message.content}\"")

        # Feature 2: Multi-Step Context Disambiguation
        # Fetch preceding channel history to resolve ambiguous pronouns ('that', 'it', 'this')
        context_snippet = None
        try:
            history_lines = []
            async for prev_msg in message.channel.history(limit=6, before=message):
                if prev_msg.author != self.bot.user and prev_msg.content:
                    history_lines.append(f"{prev_msg.author.display_name}: {prev_msg.content}")
            if history_lines:
                history_lines.reverse()
                context_snippet = "\n".join(history_lines)
        except Exception as he:
            logger.debug(f"Could not retrieve channel history: {he}")

        # Stage 2: Call Hermes Extractor with Context
        try:
            extracted = await self.extractor.extract_commitment(
                message_text=message.content,
                author_name=message.author.display_name,
                reference_time=datetime.utcnow(),
                context_snippet=context_snippet
            )

            if not extracted.is_commitment:
                logger.info(f"LLM determined non-commitment for: \"{message.content}\"")
                return

            # Parse deadline string to datetime
            deadline_dt = datetime.fromisoformat(extracted.implied_deadline_utc.replace("Z", "+00:00"))
            # Make naive UTC datetime for sqlite consistency
            deadline_dt = deadline_dt.replace(tzinfo=None)

            # Auto-schedule to Google Calendar if enabled
            cal_id = None
            cal_link = None
            if self.calendar_service and settings.auto_schedule_calendar:
                try:
                    ch_name = getattr(message.channel, "name", "chat")
                    cal_res = await self.calendar_service.schedule_commitment_event(
                        commitment=Commitment(
                            user_id=str(message.author.id),
                            user_name=message.author.display_name,
                            channel_id=str(message.channel.id),
                            channel_name=ch_name,
                            message_id=str(message.id),
                            raw_text=message.content,
                            task_title=extracted.task_title,
                            recipient=extracted.recipient,
                            deadline_utc=deadline_dt,
                            relative_deadline_text=extracted.relative_deadline_text,
                            context_snippet=extracted.context_snippet
                        )
                    )
                    cal_id = cal_res.get("id")
                    cal_link = cal_res.get("htmlLink")
                    logger.info(f"Google Calendar event created: {cal_id}")
                except Exception as ce:
                    logger.warning(f"Could not auto-schedule to Google Calendar: {ce}")

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
                status=CommitmentStatus.PENDING,
                calendar_event_id=cal_id,
                calendar_event_link=cal_link
            )
            saved_commitment = await self.db.add_commitment(commitment)
            logger.info(f"Registered commitment #{saved_commitment.id}: '{saved_commitment.task_title}' (Recipient: {saved_commitment.recipient})")

            # Dispatch webhook
            await self.webhook_dispatcher.dispatch(
                event_type="commitment.created",
                commitment=saved_commitment
            )

            # Ambient UX: Directly add to calendar and acknowledge with subtle emoji reactions (no intrusive chat messages)
            try:
                await message.add_reaction("🎯")
                if cal_id and not str(cal_id).startswith("gcal_sim_"):
                    await message.add_reaction("📅")
            except Exception as re:
                logger.debug(f"Could not add reaction: {re}")

        except Exception as e:
            logger.error(f"Error processing message for commitments: {e}", exc_info=True)


async def setup(
    bot: commands.Bot,
    db: Database,
    extractor: CommitmentExtractor,
    calendar_service: Optional[GoogleCalendarService] = None,
    webhook_dispatcher: Optional[WebhookDispatcher] = None
):
    await bot.add_cog(EventsCog(bot, db, extractor, calendar_service, webhook_dispatcher))
