import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from typing import Optional
from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from bot.ui.embeds import create_commitments_list_embed, create_commitment_embed
from bot.ui.views import CommitmentActionView
from integrations.calendar_service import GoogleCalendarService
from config import settings

logger = logging.getLogger("CommitmentRadar.Commands")


class CommandsCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        db: Database,
        extractor: CommitmentExtractor,
        calendar_service: Optional[GoogleCalendarService] = None
    ):
        self.bot = bot
        self.db = db
        self.extractor = extractor
        self.calendar_service = calendar_service

    @app_commands.command(name="commitments", description="View your active micro-commitments")
    async def list_commitments(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        active_commitments = await self.db.get_active_commitments_for_user(user_id)

        embed = create_commitments_list_embed(active_commitments, interaction.user.display_name)
        
        # If there is at least one active commitment, attach a view for the most urgent one
        if active_commitments:
            most_urgent = active_commitments[0]
            view = CommitmentActionView(most_urgent, self.db, self.extractor, self.calendar_service)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="schedule", description="Directly schedule a task to Commitment Radar and Google Calendar")
    @app_commands.describe(
        task="The task to perform (e.g. 'Review architecture doc')",
        timeframe="Deadline (e.g. 'by 4 PM', 'in 45 mins', 'tomorrow 10am')",
        recipient="Optional person or team this is for"
    )
    async def schedule_task(
        self,
        interaction: discord.Interaction,
        task: str,
        timeframe: str,
        recipient: Optional[str] = None
    ):
        await interaction.response.defer()
        prompt_text = f"I will {task} {timeframe}"
        if recipient:
            prompt_text += f" for {recipient}"

        extracted = await self.extractor.extract_commitment(
            message_text=prompt_text,
            author_name=interaction.user.display_name,
            reference_time=datetime.now(timezone.utc).replace(tzinfo=None)
        )

        deadline_dt = datetime.fromisoformat(
            (extracted.implied_deadline_utc or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
        ).replace(tzinfo=None)

        cal_id = None
        cal_link = None
        if self.calendar_service and settings.auto_schedule_calendar:
            try:
                temp_commitment = Commitment(
                    user_id=str(interaction.user.id),
                    user_name=interaction.user.display_name,
                    channel_id=str(interaction.channel_id or ""),
                    message_id=str(interaction.id),
                    raw_text=prompt_text,
                    task_title=extracted.task_title or task,
                    recipient=extracted.recipient or recipient,
                    deadline_utc=deadline_dt,
                    relative_deadline_text=extracted.relative_deadline_text or timeframe
                )
                cal_res = await self.calendar_service.schedule_commitment_event(temp_commitment)
                cal_id = cal_res.get("id")
                cal_link = cal_res.get("htmlLink")
            except Exception as ce:
                logger.warning(f"Could not schedule to Google Calendar: {ce}")

        commitment = Commitment(
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
            channel_id=str(interaction.channel_id or ""),
            guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            message_id=str(interaction.id),
            raw_text=prompt_text,
            task_title=extracted.task_title or task,
            recipient=extracted.recipient or recipient,
            deadline_utc=deadline_dt,
            relative_deadline_text=extracted.relative_deadline_text or timeframe,
            context_snippet="Scheduled directly via /schedule",
            status=CommitmentStatus.PENDING,
            calendar_event_id=cal_id,
            calendar_event_link=cal_link
        )
        saved = await self.db.add_commitment(commitment)
        embed = create_commitment_embed(saved, is_alert=False)
        view = CommitmentActionView(saved, self.db, self.extractor, self.calendar_service)
        await interaction.followup.send(
            content=f"📅 Scheduled task for <@{interaction.user.id}>!",
            embed=embed,
            view=view
        )

    @app_commands.command(name="resolve", description="Mark a specific commitment as completed")
    @app_commands.describe(commitment_id="The ID number of the commitment (e.g. 1)")
    async def resolve_commitment(self, interaction: discord.Interaction, commitment_id: int):
        await interaction.response.defer(ephemeral=True)
        commitment = await self.db.get_commitment_by_id(commitment_id)

        if not commitment:
            await interaction.followup.send(f"❌ Commitment #{commitment_id} not found.", ephemeral=True)
            return

        if commitment.user_id != str(interaction.user.id):
            await interaction.followup.send("❌ You can only resolve your own commitments.", ephemeral=True)
            return

        await self.db.update_status(commitment_id, CommitmentStatus.COMPLETED)

        # Sync to Google Calendar
        if self.calendar_service and commitment.calendar_event_id:
            try:
                await self.calendar_service.complete_event(commitment.calendar_event_id, commitment.task_title)
            except Exception:
                pass

        await interaction.followup.send(
            f"✅ Marked commitment **#{commitment_id} ({commitment.task_title})** as completed!",
            ephemeral=True
        )

    @app_commands.command(name="radar-status", description="Show Commitment Radar agent status and settings")
    async def radar_status(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛰️ Commitment Radar Agent Status",
            color=discord.Color.teal()
        )
        embed.add_field(name="Model", value=f"`{settings.llm_model}`", inline=False)
        embed.add_field(name="LLM Endpoint", value=f"`{settings.llm_base_url}`", inline=False)
        embed.add_field(name="Alert Advance Window", value=f"{settings.alert_advance_minutes} minutes", inline=True)
        embed.add_field(name="Scheduler Interval", value=f"{settings.check_interval_seconds} seconds", inline=True)
        embed.add_field(name="Timezone", value=settings.default_timezone, inline=True)

        # Google Calendar Status
        if self.calendar_service and not self.calendar_service.is_mock:
            cal_desc = "🟢 Connected (Live API)"
        elif settings.google_calendar_enabled:
            cal_desc = "🟡 Connected (Simulation / Mock Mode)"
        else:
            cal_desc = "⚪ Disabled"

        embed.add_field(
            name="📅 Google Calendar",
            value=f"{cal_desc}\nAuto-Schedule: `{settings.auto_schedule_calendar}`\nReminders: `{settings.calendar_reminder_minutes}m`",
            inline=False
        )

        embed.set_footer(text="Commitment Radar • Hackathon Edition")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(
    bot: commands.Bot,
    db: Database,
    extractor: CommitmentExtractor,
    calendar_service: Optional[GoogleCalendarService] = None
):
    await bot.add_cog(CommandsCog(bot, db, extractor, calendar_service))
