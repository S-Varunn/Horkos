import random
import logging
from typing import Optional
import discord

from db.database import Database
from db.models import DiningInquiry, DiningInquiryStatus
from llm.extractor import CommitmentExtractor
from bot.ui.embeds import create_restaurant_suggestions_embed
from config import settings

logger = logging.getLogger("CommitmentRadar.DiningUI")


class CustomCravingModal(discord.ui.Modal, title="Custom Craving & Location"):
    def __init__(
        self,
        inquiry: DiningInquiry,
        db: Database,
        extractor: CommitmentExtractor
    ):
        super().__init__()
        self.inquiry = inquiry
        self.db = db
        self.extractor = extractor

        self.craving_input = discord.ui.TextInput(
            label="What are you craving?",
            placeholder="e.g. Spicy Thai noodles, craft smash burgers, tapas...",
            style=discord.TextStyle.short,
            max_length=100,
            required=True
        )
        self.location_input = discord.ui.TextInput(
            label="Location / Neighborhood",
            default=settings.default_location,
            placeholder="e.g. Downtown, Brooklyn NY, Austin TX...",
            style=discord.TextStyle.short,
            max_length=100,
            required=False
        )
        self.add_item(self.craving_input)
        self.add_item(self.location_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        craving = self.craving_input.value.strip()
        location = self.location_input.value.strip() or settings.default_location

        try:
            recs = await self.extractor.generate_restaurant_suggestions(
                cuisine_or_craving=craving,
                location=location
            )
            if self.inquiry.id is not None:
                await self.db.update_dining_inquiry_status(
                    self.inquiry.id,
                    DiningInquiryStatus.RESOLVED,
                    chosen_cuisine=craving
                )

            embed = create_restaurant_suggestions_embed(recs)
            view = RestaurantResultView(
                inquiry=self.inquiry,
                cuisine=craving,
                location=location,
                db=self.db,
                extractor=self.extractor
            )
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content=f"🎉 Here are suggestions for **{craving}** in **{location}**:",
                embed=embed,
                view=view
            )
        except Exception as e:
            logger.error(f"Error handling custom craving submission: {e}")
            await interaction.followup.send(f"❌ Error getting suggestions: {e}", ephemeral=True)


class RestaurantResultView(discord.ui.View):
    def __init__(
        self,
        inquiry: DiningInquiry,
        cuisine: str,
        location: str,
        db: Database,
        extractor: CommitmentExtractor,
        timeout: Optional[float] = 3600
    ):
        super().__init__(timeout=timeout)
        self.inquiry = inquiry
        self.cuisine = cuisine
        self.location = location
        self.db = db
        self.extractor = extractor

    @discord.ui.button(label="Lock in a Choice", style=discord.ButtonStyle.success, emoji="✅")
    async def lock_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"🎉 **Decision made!** Enjoy your {self.cuisine}! Bon appétit! 🍽️",
            view=self
        )

    @discord.ui.button(label="More Options", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def more_options(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        recs = await self.extractor.generate_restaurant_suggestions(
            cuisine_or_craving=f"Alternative unique {self.cuisine}",
            location=self.location
        )
        embed = create_restaurant_suggestions_embed(recs)
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content=f"🔄 Fresh options for **{self.cuisine}** in **{self.location}**:",
            embed=embed,
            view=self
        )

    @discord.ui.button(label="Back to Cuisines", style=discord.ButtonStyle.primary, emoji="🔙")
    async def back_to_cuisines(self, interaction: discord.Interaction, button: discord.ui.Button):
        from bot.ui.embeds import create_dining_prompt_embed
        prompt_embed = create_dining_prompt_embed(self.inquiry, timeout_seconds=settings.dining_inquiry_timeout_seconds)
        view = DiningCuisineSelectionView(self.inquiry, self.db, self.extractor)
        await interaction.response.edit_message(
            content=None,
            embed=prompt_embed,
            view=view
        )


class DiningCuisineSelectionView(discord.ui.View):
    def __init__(
        self,
        inquiry: DiningInquiry,
        db: Database,
        extractor: CommitmentExtractor,
        timeout: Optional[float] = 3600
    ):
        super().__init__(timeout=timeout)
        self.inquiry = inquiry
        self.db = db
        self.extractor = extractor

    async def _handle_cuisine_click(self, interaction: discord.Interaction, cuisine: str):
        await interaction.response.defer()
        location = settings.default_location
        try:
            recs = await self.extractor.generate_restaurant_suggestions(
                cuisine_or_craving=cuisine,
                location=location
            )
            if self.inquiry.id is not None:
                await self.db.update_dining_inquiry_status(
                    self.inquiry.id,
                    DiningInquiryStatus.RESOLVED,
                    chosen_cuisine=cuisine
                )

            embed = create_restaurant_suggestions_embed(recs)
            view = RestaurantResultView(
                inquiry=self.inquiry,
                cuisine=cuisine,
                location=location,
                db=self.db,
                extractor=self.extractor
            )
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content=f"🎉 Here are top picks for **{cuisine}** in **{location}**:",
                embed=embed,
                view=view
            )
        except Exception as e:
            logger.error(f"Error fetching restaurant recommendations: {e}")
            await interaction.followup.send(f"❌ Failed to fetch recommendations: {e}", ephemeral=True)

    @discord.ui.button(label="Pizza / Italian", style=discord.ButtonStyle.secondary, emoji="🍕", row=0)
    async def pizza(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_cuisine_click(interaction, "Pizza / Italian")

    @discord.ui.button(label="Sushi / Japanese", style=discord.ButtonStyle.secondary, emoji="🍣", row=0)
    async def sushi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_cuisine_click(interaction, "Sushi / Japanese")

    @discord.ui.button(label="Mexican / Tacos", style=discord.ButtonStyle.secondary, emoji="🌮", row=0)
    async def mexican(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_cuisine_click(interaction, "Mexican / Tacos")

    @discord.ui.button(label="Burgers / American", style=discord.ButtonStyle.secondary, emoji="🍔", row=1)
    async def burgers(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_cuisine_click(interaction, "Burgers / American")

    @discord.ui.button(label="Healthy / Bowls", style=discord.ButtonStyle.secondary, emoji="🥗", row=1)
    async def healthy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_cuisine_click(interaction, "Healthy / Salads & Bowls")

    @discord.ui.button(label="Surprise Me!", style=discord.ButtonStyle.primary, emoji="🎲", row=1)
    async def surprise(self, interaction: discord.Interaction, button: discord.ui.Button):
        random_cuisine = random.choice([
            "Korean BBQ",
            "Thai Street Food",
            "Mediterranean / Shawarma",
            "Authentic Ramen",
            "Artisanal Tacos",
            "Wood-Fired Neapolitan Pizza",
            "Vietnamese Pho & Banh Mi"
        ])
        await self._handle_cuisine_click(interaction, random_cuisine)

    @discord.ui.button(label="Custom Craving / City", style=discord.ButtonStyle.success, emoji="✍️", row=2)
    async def custom_craving(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CustomCravingModal(self.inquiry, self.db, self.extractor)
        await interaction.response.send_modal(modal)


class AlreadyAcceptedPlanView(discord.ui.View):
    def __init__(
        self,
        inquiry: DiningInquiry,
        agreed_plan: str,
        db: Database,
        extractor: CommitmentExtractor,
        timeout: Optional[float] = 3600
    ):
        super().__init__(timeout=timeout)
        self.inquiry = inquiry
        self.agreed_plan = agreed_plan
        self.db = db
        self.extractor = extractor

    @discord.ui.button(label="Stick with It", style=discord.ButtonStyle.success, emoji="👍")
    async def stick_with_it(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        if self.inquiry.id is not None:
            await self.db.update_dining_inquiry_status(
                self.inquiry.id,
                DiningInquiryStatus.RESOLVED,
                chosen_cuisine=self.agreed_plan
            )
        await interaction.response.edit_message(
            content=f"🎉 **Locked in!** Sticking with **{self.agreed_plan}**. Enjoy dinner! 🍽️",
            view=self
        )

    @discord.ui.button(label="Pick Somewhere New", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def pick_somewhere_new(self, interaction: discord.Interaction, button: discord.ui.Button):
        from bot.ui.embeds import create_dining_prompt_embed
        prompt_embed = create_dining_prompt_embed(self.inquiry, timeout_seconds=settings.dining_inquiry_timeout_seconds)
        view = DiningCuisineSelectionView(self.inquiry, self.db, self.extractor)
        await interaction.response.edit_message(
            content=None,
            embed=prompt_embed,
            view=view
        )
