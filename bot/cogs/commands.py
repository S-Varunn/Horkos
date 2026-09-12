import logging
import discord
from discord import app_commands
from discord.ext import commands

from db.database import Database
from db.models import CommitmentStatus
from llm.extractor import CommitmentExtractor
from bot.ui.embeds import create_commitments_list_embed, create_commitment_embed
from bot.ui.views import CommitmentActionView
from config import settings

logger = logging.getLogger("CommitmentRadar.Commands")


class CommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database, extractor: CommitmentExtractor):
        self.bot = bot
        self.db = db
        self.extractor = extractor

    @app_commands.command(name="commitments", description="View your active micro-commitments")
    async def list_commitments(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        active_commitments = await self.db.get_active_commitments_for_user(user_id)

        embed = create_commitments_list_embed(active_commitments, interaction.user.display_name)
        
        # If there is at least one active commitment, attach a view for the most urgent one
        if active_commitments:
            most_urgent = active_commitments[0]
            view = CommitmentActionView(most_urgent, self.db, self.extractor)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

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
        embed.set_footer(text="Commitment Radar • Hackathon Edition")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot, db: Database, extractor: CommitmentExtractor):
    await bot.add_cog(CommandsCog(bot, db, extractor))
