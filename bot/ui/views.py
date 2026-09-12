import discord
from datetime import datetime, timedelta
from typing import Optional

from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from bot.ui.embeds import create_commitment_embed, create_resolution_embed


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


class PostDraftView(discord.ui.View):
    def __init__(self, draft_text: str, channel: discord.TextChannel, timeout: Optional[float] = 300):
        super().__init__(timeout=timeout)
        self.draft_text = draft_text
        self.channel = channel

    @discord.ui.button(label="Post to Channel", style=discord.ButtonStyle.success, emoji="📤")
    async def post_to_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        try:
            if self.channel:
                await self.channel.send(self.draft_text)
            await interaction.response.edit_message(
                content="✅ **Update posted to channel!**",
                embed=None,
                view=self
            )
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Failed to post update: {e}",
                embed=None,
                view=self
            )


class CommitmentActionView(discord.ui.View):
    def __init__(
        self,
        commitment: Commitment,
        db: Database,
        extractor: CommitmentExtractor,
        timeout: Optional[float] = 86400  # 24 hours
    ):
        super().__init__(timeout=timeout)
        self.commitment = commitment
        self.db = db
        self.extractor = extractor

    @discord.ui.button(label="Mark Done", style=discord.ButtonStyle.success, emoji="✅")
    async def mark_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check permissions: only the commitment owner or admin can resolve
        if str(interaction.user.id) != self.commitment.user_id:
            await interaction.response.send_message("You can only resolve your own commitments.", ephemeral=True)
            return

        if self.commitment.id is not None:
            await self.db.update_status(self.commitment.id, CommitmentStatus.COMPLETED)
            self.commitment.status = CommitmentStatus.COMPLETED

        # Disable buttons
        for item in self.children:
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

        embed = create_commitment_embed(self.commitment, is_alert=False)
        await interaction.response.edit_message(
            content="⏱️ Deadline postponed by 1 hour!",
            embed=embed,
            view=self
        )

    @discord.ui.button(label="Draft Update", style=discord.ButtonStyle.primary, emoji="📝")
    async def draft_update(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.commitment.user_id:
            await interaction.response.send_message("Only the commitment owner can draft updates.", ephemeral=True)
            return

        # Show immediate visual loading feedback on button click
        await interaction.response.send_message(
            "⏳ **Calling Hermes AI via OpenRouter to draft an update...**",
            ephemeral=True
        )

        try:
            draft = await self.extractor.generate_resolution_draft(
                task_title=self.commitment.task_title,
                recipient=self.commitment.recipient,
                original_deadline_text=self.commitment.relative_deadline_text,
                speaker_name=self.commitment.user_name
            )

            post_view = PostDraftView(
                draft_text=draft.suggested_reply,
                channel=interaction.channel
            )
            draft_embed = discord.Embed(
                title="📝 AI-Generated Status Update",
                description=f"> *\"{draft.suggested_reply}\"*",
                color=discord.Color.blurple()
            )
            draft_embed.set_footer(text="Click below to post this update to the channel.")
            await interaction.edit_original_response(
                content="✨ **Here is your AI-drafted update:**",
                embed=draft_embed,
                view=post_view
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Failed to generate draft update: {e}",
                embed=None,
                view=None
            )
