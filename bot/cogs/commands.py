import logging
import json
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
from integrations.calendar_service import GoogleCalendarService, render_calendar_template
from integrations.mcp_server import format_commitments_markdown, format_commitments_todoist
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

    @app_commands.command(name="calendar-connect", description="Connect your personal Google Calendar to Commitment Radar")
    async def calendar_connect(self, interaction: discord.Interaction):
        if not self.calendar_service or not self.calendar_service.enabled:
            await interaction.response.send_message("❌ Google Calendar integration is disabled.", ephemeral=True)
            return

        try:
            auth_url = self.calendar_service.get_authorization_url(str(interaction.user.id))
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Sign In with Google", url=auth_url, emoji="🌐"))
            await interaction.response.send_message(
                "🔗 **Link your personal Google Calendar:**\n"
                "1. Click the button below to sign in with Google.\n"
                "2. Grant calendar permissions to Commitment Radar.\n"
                "3. Once linked, the bot will automatically book your micro-commitments to your personal calendar with reminder popups!\n\n"
                "*(If you copy the authorization code manually, you can also run `/calendar-auth code:<code>`)*",
                view=view,
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not create authorization link: {e}", ephemeral=True)

    @app_commands.command(name="calendar-auth", description="Complete Google Calendar connection using an authorization code")
    @app_commands.describe(code="The authorization code provided by Google")
    async def calendar_auth(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        if not self.calendar_service:
            await interaction.followup.send("❌ Google Calendar integration is not active.", ephemeral=True)
            return

        result = await self.calendar_service.handle_oauth_code(code.strip(), str(interaction.user.id))
        if result.get("success"):
            email_info = f" ({result['email']})" if result.get("email") else ""
            await interaction.followup.send(
                f"✅ **Google Calendar Connected!**{email_info}\n"
                "Your promises and tasks will now be automatically booked onto your Google Calendar with native reminder notifications.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ Failed to connect Google Calendar: {result.get('error', 'Unknown error')}\n"
                "Please run `/calendar-connect` to get a fresh link.",
                ephemeral=True
            )

    @app_commands.command(name="calendar-disconnect", description="Disconnect your personal Google Calendar")
    async def calendar_disconnect(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        deleted = await self.db.delete_user_google_auth(user_id)
        if self.calendar_service:
            self.calendar_service._user_services.pop(user_id, None)

        if deleted:
            await interaction.followup.send("✅ Disconnected your Google Calendar from Commitment Radar.", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ You did not have a connected Google Calendar.", ephemeral=True)

    @app_commands.command(name="calendar-status", description="Check if your personal Google Calendar is connected")
    async def calendar_user_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        user_auth = await self.db.get_user_google_auth(user_id)

        embed = discord.Embed(
            title="📅 Your Google Calendar Status",
            color=discord.Color.green() if user_auth else discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        if user_auth:
            embed.description = "🟢 **Connected**\nYour commitments will be scheduled directly into your calendar."
            if user_auth.google_email:
                embed.add_field(name="Google Account", value=user_auth.google_email, inline=False)
            embed.add_field(name="Connected Since", value=user_auth.created_at.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
        else:
            embed.description = (
                "🟡 **Not Connected**\n"
                "Use `/calendar-connect` to link your Google Calendar so the agent can autonomously book events and set reminders on your devices."
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

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
        if self.calendar_service and self.calendar_service.enabled:
            cal_desc = f"🟢 Active (Multi-User OAuth)\nRedirect: `{settings.google_oauth_redirect_uri}`\nReminders: `{settings.calendar_reminder_minutes}m`"
        else:
            cal_desc = "⚪ Disabled"

        embed.add_field(
            name="📅 Google Calendar Integration",
            value=cal_desc,
            inline=False
        )

        embed.set_footer(text="Commitment Radar • Hackathon Edition")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="export", description="Export your active commitments in Markdown, JSON, or Todoist format")
    @app_commands.describe(format="Export format (markdown, json, or todoist)")
    @app_commands.choices(format=[
        app_commands.Choice(name="Markdown Checklist", value="markdown"),
        app_commands.Choice(name="Todoist API Payload", value="todoist"),
        app_commands.Choice(name="Raw JSON", value="json")
    ])
    async def export_commitments(self, interaction: discord.Interaction, format: str = "markdown"):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        commitments = await self.db.get_active_commitments_for_user(user_id)

        if not commitments:
            await interaction.followup.send("ℹ️ You have no active commitments to export.", ephemeral=True)
            return

        if format == "markdown":
            md_content = format_commitments_markdown(commitments, title=f"Commitments for {interaction.user.display_name}")
            await interaction.followup.send(f"```markdown\n{md_content}\n```", ephemeral=True)
        elif format == "todoist":
            tasks = format_commitments_todoist(commitments)
            await interaction.followup.send(f"```json\n{json.dumps(tasks, indent=2)}\n```", ephemeral=True)
        else:
            data = [
                {
                    "id": c.id,
                    "task": c.task_title,
                    "recipient": c.recipient,
                    "deadline_utc": c.deadline_utc.isoformat() if c.deadline_utc else None,
                    "calendar_link": c.calendar_event_link
                }
                for c in commitments
            ]
            await interaction.followup.send(f"```json\n{json.dumps(data, indent=2)}\n```", ephemeral=True)

    calendar_template = app_commands.Group(
        name="calendar-template",
        description="Customize how your tasks look on Google Calendar"
    )

    @calendar_template.command(name="set", description="Set your custom Google Calendar task title and description templates")
    @app_commands.describe(
        title="Title template (e.g. 'Reminder: {task}' or '!!Reminder!! {task}')",
        completed="Completed title template (e.g. '[Done] {task}' or 'COMPLETED: {task}')",
        description="Optional custom description template"
    )
    async def template_set(
        self,
        interaction: discord.Interaction,
        title: str,
        completed: Optional[str] = None,
        description: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        comp_tpl = completed or "[Done] {task}"

        saved = await self.db.save_user_calendar_template(
            discord_user_id=user_id,
            title_template=title,
            completed_template=comp_tpl,
            description_template=description
        )

        sample_context = {
            "task": "Update project documentation",
            "task_title": "Update project documentation",
            "author": interaction.user.display_name,
            "user_name": interaction.user.display_name,
            "recipient": "Sarah",
            "timeframe": "by 5 PM",
            "context": "Sarah requested update on docs",
            "raw_text": "I'll update the project documentation by 5 PM"
        }

        title_preview = render_calendar_template(saved.title_template, sample_context)
        comp_preview = render_calendar_template(saved.completed_template, sample_context)
        desc_preview = render_calendar_template(saved.description_template, sample_context) if saved.description_template else "Standard clean metadata"

        embed = discord.Embed(
            title="Custom Calendar Template Saved",
            description="Your personal Google Calendar event format has been saved!",
            color=discord.Color.brand_green()
        )
        embed.add_field(name="Task Title Format", value=f"`{saved.title_template}`\n👉 **Preview**: {title_preview}", inline=False)
        embed.add_field(name="Completed Format", value=f"`{saved.completed_template}`\n👉 **Preview**: {comp_preview}", inline=False)
        if saved.description_template:
            embed.add_field(name="Description Format", value=f"```text\n{desc_preview}\n```", inline=False)
        embed.set_footer(text="Available variables: {task}, {author}, {recipient}, {timeframe}, {context}, {raw_text}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @calendar_template.command(name="view", description="View your active Google Calendar task template")
    async def template_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        tpl = await self.db.get_user_calendar_template(user_id)

        sample_context = {
            "task": "Update project documentation",
            "task_title": "Update project documentation",
            "author": interaction.user.display_name,
            "user_name": interaction.user.display_name,
            "recipient": "Sarah",
            "timeframe": "by 5 PM",
            "context": "Sarah requested update on docs",
            "raw_text": "I'll update the project documentation by 5 PM"
        }

        embed = discord.Embed(
            title="Your Google Calendar Template Settings",
            color=discord.Color.blue()
        )

        if tpl:
            title_prev = render_calendar_template(tpl.title_template, sample_context)
            comp_prev = render_calendar_template(tpl.completed_template, sample_context)
            embed.add_field(name="Title Template", value=f"`{tpl.title_template}`\n👉 Preview: {title_prev}", inline=False)
            embed.add_field(name="Completed Template", value=f"`{tpl.completed_template}`\n👉 Preview: {comp_prev}", inline=False)
            if tpl.description_template:
                desc_prev = render_calendar_template(tpl.description_template, sample_context)
                embed.add_field(name="Description Template", value=f"```text\n{desc_prev}\n```", inline=False)
            else:
                embed.add_field(name="Description Template", value="*Clean default metadata*", inline=False)
        else:
            embed.description = "You are currently using the **Clean Minimalist Default** (no emojis or clutter)."
            embed.add_field(name="Default Title", value="`{task}`\n👉 Preview: Update project documentation", inline=False)
            embed.add_field(name="Default Completed", value="`[Done] {task}`\n👉 Preview: [Done] Update project documentation", inline=False)

        embed.add_field(
            name="Available Variables",
            value="`{task}` - Task description\n`{author}` - Your name\n`{recipient}` - Recipient or Team\n`{timeframe}` - Deadline text\n`{context}` - Conversation snippet\n`{raw_text}` - Original chat message",
            inline=False
        )
        embed.set_footer(text="Use /calendar-template set to change or /calendar-template reset to clear")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @calendar_template.command(name="reset", description="Reset your Google Calendar templates to default clean formatting")
    async def template_reset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        deleted = await self.db.delete_user_calendar_template(user_id)

        if deleted:
            await interaction.followup.send("Your calendar template has been reset to the clean default format (`{task}`).", ephemeral=True)
        else:
            await interaction.followup.send("You are already using the clean default template.", ephemeral=True)

    channel_template = app_commands.Group(
        name="channel-template",
        description="Customize how tasks created in this channel look on Google Calendar"
    )

    @channel_template.command(name="set", description="Set custom calendar task templates for this channel")
    @app_commands.describe(
        title="Title template for this channel (e.g. '[DEV] {task}' or '!!BugFix!! {task}')",
        completed="Completed title template for this channel (e.g. '[RESOLVED] {task}')",
        description="Optional custom description template for this channel"
    )
    async def channel_template_set(
        self,
        interaction: discord.Interaction,
        title: str,
        completed: Optional[str] = None,
        description: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        guild_id = str(interaction.guild_id) if interaction.guild_id else None
        ch_name = getattr(interaction.channel, "name", "channel")
        comp_tpl = completed or "[Done] {task}"

        saved = await self.db.save_channel_calendar_template(
            channel_id=channel_id,
            title_template=title,
            completed_template=comp_tpl,
            description_template=description,
            guild_id=guild_id,
            channel_name=ch_name
        )

        sample_context = {
            "task": "Review pull request #42",
            "task_title": "Review pull request #42",
            "author": interaction.user.display_name,
            "user_name": interaction.user.display_name,
            "recipient": "Sarah",
            "timeframe": "by 5 PM",
            "context": "Sarah requested review on PR #42",
            "raw_text": "I'll review PR #42 by 5 PM",
            "channel": ch_name
        }

        title_preview = render_calendar_template(saved.title_template, sample_context)
        comp_preview = render_calendar_template(saved.completed_template, sample_context)
        desc_preview = render_calendar_template(saved.description_template, sample_context) if saved.description_template else "Standard channel metadata"

        embed = discord.Embed(
            title=f"Channel Calendar Template Saved for #{ch_name}",
            description=f"Commitments made in this channel will now use this format by default!",
            color=discord.Color.gold()
        )
        embed.add_field(name="Task Title Format", value=f"`{saved.title_template}`\n👉 **Preview**: {title_preview}", inline=False)
        embed.add_field(name="Completed Format", value=f"`{saved.completed_template}`\n👉 **Preview**: {comp_preview}", inline=False)
        if saved.description_template:
            embed.add_field(name="Description Format", value=f"```text\n{desc_preview}\n```", inline=False)
        embed.set_footer(text="Available variables: {task}, {channel}, {author}, {recipient}, {timeframe}, {context}, {raw_text}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @channel_template.command(name="view", description="View active Google Calendar task template for this channel")
    async def channel_template_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        ch_name = getattr(interaction.channel, "name", "channel")
        tpl = await self.db.get_channel_calendar_template(channel_id)

        sample_context = {
            "task": "Review pull request #42",
            "task_title": "Review pull request #42",
            "author": interaction.user.display_name,
            "user_name": interaction.user.display_name,
            "recipient": "Sarah",
            "timeframe": "by 5 PM",
            "context": "Sarah requested review",
            "raw_text": "I'll review PR #42 by 5 PM",
            "channel": ch_name
        }

        embed = discord.Embed(
            title=f"Calendar Template for #{ch_name}",
            color=discord.Color.purple()
        )

        if tpl:
            title_prev = render_calendar_template(tpl.title_template, sample_context)
            comp_prev = render_calendar_template(tpl.completed_template, sample_context)
            embed.description = "This channel has an **active custom template override**."
            embed.add_field(name="Channel Title Template", value=f"`{tpl.title_template}`\n👉 Preview: {title_prev}", inline=False)
            embed.add_field(name="Channel Completed Template", value=f"`{tpl.completed_template}`\n👉 Preview: {comp_prev}", inline=False)
            if tpl.description_template:
                desc_prev = render_calendar_template(tpl.description_template, sample_context)
                embed.add_field(name="Description Template", value=f"```text\n{desc_prev}\n```", inline=False)
        else:
            embed.description = f"No custom channel template is set for #{ch_name}.\nCommitments in this channel fall back to each user's **personal `/calendar-template`** (or clean default)."

        embed.add_field(
            name="Available Variables",
            value="`{task}` - Task description\n`{channel}` - Channel name\n`{author}` - Your name\n`{recipient}` - Recipient or Team\n`{timeframe}` - Deadline text\n`{context}` - Conversation snippet\n`{raw_text}` - Original chat message",
            inline=False
        )
        embed.set_footer(text="Use /channel-template set to configure or /channel-template reset to clear")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @channel_template.command(name="reset", description="Reset this channel's calendar template back to user/default fallback")
    async def channel_template_reset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        ch_name = getattr(interaction.channel, "name", "channel")
        deleted = await self.db.delete_channel_calendar_template(channel_id)

        if deleted:
            await interaction.followup.send(f"Calendar template for #{ch_name} has been cleared. Commitments will now fall back to user templates.", ephemeral=True)
        else:
            await interaction.followup.send(f"No custom template was active for #{ch_name}.", ephemeral=True)



async def setup(
    bot: commands.Bot,
    db: Database,
    extractor: CommitmentExtractor,
    calendar_service: Optional[GoogleCalendarService] = None
):
    await bot.add_cog(CommandsCog(bot, db, extractor, calendar_service))
