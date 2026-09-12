import discord
from datetime import datetime, timedelta
from typing import Optional

from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from bot.ui.embeds import create_commitment_embed, create_resolution_embed
from integrations.calendar_service import GoogleCalendarService


class DraftUpdateModal(discord.ui.Modal, title="Draft Status Update"):
    def __init__(self, default_text: str, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel
        self.message_input = discord.ui.TextInput(
            label="Message to send to channel",
            style=discord.TextStyle.paragraph,
            default=default_text,
            max_length=1000,
            required=True
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        # Post the message to the original channel
        try:
            await self.channel.send(f"{self.message_input.value}")
            await interaction.response.send_message("✅ Update posted to channel!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to post message: {e}", ephemeral=True)


class CommitmentActionView(discord.ui.View):
    def __init__(
        self,
        commitment: Commitment,
        db: Database,
        extractor: CommitmentExtractor,
        calendar_service: Optional[GoogleCalendarService] = None,
        timeout: Optional[float] = 86400  # 24 hours
    ):
        super().__init__(timeout=timeout)
        self.commitment = commitment
        self.db = db
        self.extractor = extractor
        self.calendar_service = calendar_service

        # If a Google Calendar event link exists, add a direct link button
        if self.commitment.calendar_event_link:
            self.add_item(
                discord.ui.Button(
                    label="Calendar",
                    url=self.commitment.calendar_event_link,
                    emoji="📅",
                    row=1
                )
            )

    @discord.ui.button(label="Mark Done", style=discord.ButtonStyle.success, emoji="✅")
    async def mark_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check permissions: only the commitment owner or admin can resolve
        if str(interaction.user.id) != self.commitment.user_id:
            await interaction.response.send_message("You can only resolve your own commitments.", ephemeral=True)
            return

        if self.commitment.id is not None:
            await self.db.update_status(self.commitment.id, CommitmentStatus.COMPLETED)
            self.commitment.status = CommitmentStatus.COMPLETED

            # Sync with Google Calendar
            if self.calendar_service and self.commitment.calendar_event_id:
                try:
                    await self.calendar_service.complete_event(
                        event_id=self.commitment.calendar_event_id,
                        task_title=self.commitment.task_title,
                        discord_user_id=self.commitment.user_id
                    )
                except Exception:
                    pass

        # Disable buttons
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

        embed = create_resolution_embed(self.commitment, "Completed")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Push 1 Hour", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def push_one_hour(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.commitment.user_id:
            await interaction.response.send_message("You can only adjust your own commitments.", ephemeral=True)
            return

        new_deadline = datetime.utcnow() + timedelta(hours=1)
        if self.commitment.id is not None:
            await self.db.update_deadline(self.commitment.id, new_deadline)
            self.commitment.deadline_utc = new_deadline
            self.commitment.status = CommitmentStatus.PENDING

            # Sync updated deadline to Google Calendar
            if self.calendar_service and self.commitment.calendar_event_id:
                try:
                    await self.calendar_service.update_event_time(
                        event_id=self.commitment.calendar_event_id,
                        new_deadline=new_deadline,
                        discord_user_id=self.commitment.user_id
                    )
                except Exception:
                    pass

        embed = create_commitment_embed(self.commitment, is_alert=False)
        await interaction.response.edit_message(
            content="⏱️ Deadline postponed by 1 hour!",
            embed=embed,
            view=self
        )

    @discord.ui.button(label="Connect Calendar", style=discord.ButtonStyle.secondary, emoji="🔗", row=1)
    async def connect_calendar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.calendar_service:
            await interaction.response.send_message("Google Calendar integration is not active.", ephemeral=True)
            return
        try:
            auth_url = self.calendar_service.get_authorization_url(str(interaction.user.id))
            link_view = discord.ui.View()
            link_view.add_item(discord.ui.Button(label="Open Google Sign-In", url=auth_url, emoji="🌐"))
            await interaction.response.send_message(
                "🔗 **Connect your personal Google Calendar:**\n"
                "Click below to authorize your Google account. Your promises will automatically sync to your calendar with notification popups!\n\n"
                "*(You can also use `/calendar-auth code:<code>` if copy-pasting an authorization code)*",
                view=link_view,
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not generate authorization link: {e}", ephemeral=True)

    @discord.ui.button(label="Draft Update", style=discord.ButtonStyle.primary, emoji="📝")
    async def draft_update(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.commitment.user_id:
            await interaction.response.send_message("Only the commitment owner can draft updates.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Call Hermes to generate contextual update
        draft = await self.extractor.generate_resolution_draft(
            task_title=self.commitment.task_title,
            recipient=self.commitment.recipient,
            original_deadline_text=self.commitment.relative_deadline_text,
            speaker_name=self.commitment.user_name
        )

        modal = DraftUpdateModal(
            default_text=draft.suggested_reply,
            channel=interaction.channel
        )
        await interaction.followup.send_modal(modal)
