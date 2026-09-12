import pytest
import discord
from unittest.mock import AsyncMock, MagicMock
from pipeline.filter import is_dining_inquiry
from db.database import Database
from db.models import DiningInquiry, DiningInquiryStatus
from llm.extractor import CommitmentExtractor
from llm.schemas import RestaurantRecommendations


def test_dining_inquiry_detection_positive():
    positives = [
        "where you want to eat",
        "Where do you want to eat?",
        "where should we eat tonight?",
        "what is the dinner plan?",
        "what's the lunch plan?",
        "the plan for dinner?",
        "any dinner plans?",
        "what should we eat",
        "what do you want to eat?",
        "anyone hungry?",
        "where should we grab food?",
        "where to eat?",
        "How about we guys go eat indian tonight?\nMexican food also works for me?\nFor dinner?",
        "How about we guys go eat indian tonight?",
        "how about sushi tonight?",
        "who is down for tacos?",
        "should we go pizza or sushi this time",
        "pizza or sushi?",
        "should we get thai or indian?",
        "do we have a dinner plan ?",
        "do we have any dinner plans?",
        "did we decide on dinner?"
    ]
    for text in positives:
        is_dining, reason = is_dining_inquiry(text)
        assert is_dining is True, f"Expected '{text}' to match dining inquiry, got reason: {reason}"


def test_dining_inquiry_detection_negative():
    negatives = [
        "I'll send the file by 5 PM",
        "Let me review this PR after lunch",
        "Can you fix this bug?",
        "Good morning team!",
        "!dinner",
        "/eat",
        "```where do you want to eat```",
        "eat",  # Too short
    ]
    for text in negatives:
        is_dining, _ = is_dining_inquiry(text)
        assert is_dining is False, f"Expected '{text}' to NOT match dining inquiry"


@pytest.mark.asyncio
async def test_dining_inquiry_db_lifecycle(tmp_path):
    db_file = str(tmp_path / "test_dining.db")
    db = Database(db_path=db_file)
    await db.init_db()

    inquiry = DiningInquiry(
        channel_id="channel_123",
        message_id="msg_999",
        user_id="user_456",
        user_name="Alice",
        raw_text="where you want to eat"
    )

    # 1. Add inquiry
    saved = await db.add_dining_inquiry(inquiry)
    assert saved.id is not None
    assert saved.status == DiningInquiryStatus.WAITING

    # 2. Get active inquiry for channel
    active = await db.get_active_dining_inquiry_for_channel("channel_123")
    assert active is not None
    assert active.id == saved.id
    assert active.raw_text == "where you want to eat"

    # 3. Update status to TIMED_OUT
    updated = await db.update_dining_inquiry_status(saved.id, DiningInquiryStatus.TIMED_OUT)
    assert updated is True

    # After TIMED_OUT, it is no longer WAITING
    active_after = await db.get_active_dining_inquiry_for_channel("channel_123")
    assert active_after is None

    # 4. Update status to RESOLVED with chosen cuisine
    res = await db.update_dining_inquiry_status(
        saved.id,
        DiningInquiryStatus.RESOLVED,
        chosen_cuisine="Sushi / Japanese"
    )
    assert res is True


@pytest.mark.asyncio
async def test_restaurant_suggestions_with_mock():
    mock_client = AsyncMock()
    mock_client.generate_json.return_value = {
        "cuisine": "Tacos",
        "location": "New York, NY",
        "summary": "Crispy carnitas and handmade tortillas nearby!",
        "options": [
            {
                "name": "Los Tacos No. 1",
                "cuisine_type": "Authentic Mexican",
                "price_range": "$",
                "vibe": "Fast-paced, standing room counter",
                "highlight_dish": "Adobada Pork Tacos with Pineapple",
                "why_go": "World-famous tacos served fast and delicious."
            },
            {
                "name": "Tacombi",
                "cuisine_type": "Taqueria & Drinks",
                "price_range": "$$",
                "vibe": "Vibrant VW bus patio",
                "highlight_dish": "Crispy Baja Fish Tacos",
                "why_go": "Great vibe with pitchers of margaritas for the group."
            }
        ]
    }

    extractor = CommitmentExtractor(client=mock_client)
    recs = await extractor.generate_restaurant_suggestions(
        cuisine_or_craving="Tacos",
        location="New York, NY"
    )

    assert isinstance(recs, RestaurantRecommendations)
    assert recs.cuisine == "Tacos"
    assert len(recs.options) == 2
    assert recs.options[0].name == "Los Tacos No. 1"
    assert recs.options[1].highlight_dish == "Crispy Baja Fish Tacos"


@pytest.mark.asyncio
async def test_restaurant_suggestions_fallback_on_error():
    mock_client = AsyncMock()
    mock_client.generate_json.side_effect = RuntimeError("API Rate Limit")

    extractor = CommitmentExtractor(client=mock_client)
    recs = await extractor.generate_restaurant_suggestions(
        cuisine_or_craving="Italian",
        location="Boston, MA"
    )

    # Fallback should kick in gracefully
    assert isinstance(recs, RestaurantRecommendations)
    assert recs.cuisine == "Italian"
    assert len(recs.options) == 3
    assert "Rustic Italian" in recs.options[0].name


@pytest.mark.asyncio
async def test_check_for_accepted_plan_mock():
    mock_client = AsyncMock()
    mock_client.generate_json.return_value = {
        "has_accepted_plan": True,
        "agreed_plan": "Sushi at 7 PM",
        "confidence": 0.95,
        "context_quote": "let's do sushi at 7"
    }

    extractor = CommitmentExtractor(client=mock_client)
    res = await extractor.check_for_accepted_plan([
        "Alice: Where should we eat?",
        "Bob: let's do sushi at 7",
        "Charlie: Sounds great!"
    ])

    assert res.has_accepted_plan is True
    assert res.agreed_plan == "Sushi at 7 PM"
    assert res.context_quote == "let's do sushi at 7"


@pytest.mark.asyncio
async def test_check_for_accepted_plan_fallback():
    mock_client = AsyncMock()
    mock_client.generate_json.side_effect = RuntimeError("Offline")

    extractor = CommitmentExtractor(client=mock_client)
    res = await extractor.check_for_accepted_plan([
        "Alice: Where should we eat?",
        "Bob: agreed on tacos",
        "Charlie: Awesome"
    ])

    assert res.has_accepted_plan is True
    assert "Tacos" in res.agreed_plan


@pytest.mark.asyncio
async def test_recent_resolved_dining_inquiry_db(tmp_path):
    db_file = str(tmp_path / "test_resolved.db")
    db = Database(db_path=db_file)
    await db.init_db()

    inquiry = DiningInquiry(
        channel_id="chan_999",
        message_id="msg_111",
        user_id="user_1",
        user_name="Alice",
        raw_text="dinner plans?",
        status=DiningInquiryStatus.RESOLVED,
        chosen_cuisine="Wood-Fired Pizza"
    )
    saved = await db.add_dining_inquiry(inquiry)

    # Should find it within last 3 minutes
    recent = await db.get_recent_resolved_dining_inquiry("chan_999", within_minutes=3)
    assert recent is not None
    assert recent.chosen_cuisine == "Wood-Fired Pizza"

    # Other channels should return None
    other = await db.get_recent_resolved_dining_inquiry("chan_other", within_minutes=3)
    assert other is None


def test_dining_loading_embed():
    from bot.ui.embeds import create_dining_loading_embed
    embed = create_dining_loading_embed("Pizza / Italian", "Austin, TX")
    assert embed.title == "🍳 AI Concierge is Cooking..."
    assert "Pizza / Italian" in embed.description
    assert "Austin, TX" in embed.description
    assert "Hermes 3" in embed.description
    assert embed.color.value == discord.Color.gold().value


@pytest.mark.asyncio
async def test_dining_cuisine_click_loading_feedback(tmp_path):
    from bot.ui.dining_views import DiningCuisineSelectionView
    from unittest.mock import MagicMock

    db_file = str(tmp_path / "test_views.db")
    db = Database(db_path=db_file)
    await db.init_db()

    mock_client = AsyncMock()
    mock_client.generate_json.return_value = {
        "cuisine": "Pizza / Italian",
        "location": "New York, NY",
        "summary": "Great pizza spots",
        "options": [
            {
                "name": "Joe's Pizza",
                "cuisine_type": "Pizza",
                "price_range": "$",
                "vibe": "Classic NY slice",
                "highlight_dish": "Plain Cheese",
                "why_go": "Iconic slice"
            }
        ]
    }
    extractor = CommitmentExtractor(client=mock_client)

    inquiry = DiningInquiry(
        id=1,
        channel_id="chan_1",
        message_id="msg_1",
        user_id="user_1",
        user_name="Alice",
        raw_text="where to eat?"
    )

    view = DiningCuisineSelectionView(inquiry, db, extractor)

    # Mock interaction
    interaction = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.channel = MagicMock()
    interaction.channel.typing.return_value.__aenter__ = AsyncMock()
    interaction.channel.typing.return_value.__aexit__ = AsyncMock()

    await view._handle_cuisine_click(interaction, "Pizza / Italian")

    # Verify immediate loading feedback was displayed
    interaction.response.edit_message.assert_awaited_once()
    loading_call_kwargs = interaction.response.edit_message.await_args.kwargs
    assert "Contacting AI Concierge" in loading_call_kwargs["content"]
    assert loading_call_kwargs["embed"] is not None
    assert loading_call_kwargs["embed"].title == "🍳 AI Concierge is Cooking..."

    # Verify buttons were disabled during processing
    for btn in view.children:
        assert btn.disabled is True

    # Verify typing indicator was triggered
    interaction.channel.typing.assert_called_once()

    # Verify final result was published via edit_original_response
    interaction.edit_original_response.assert_awaited_once()
    final_kwargs = interaction.edit_original_response.await_args.kwargs
    assert "Here are top picks for **Pizza / Italian**" in final_kwargs["content"]
    assert final_kwargs["embed"] is not None
    assert final_kwargs["embed"].title == "🍴 Top Pizza / Italian Spots in New York, NY"


@pytest.mark.asyncio
async def test_dining_more_options_loading_feedback(tmp_path):
    from bot.ui.dining_views import RestaurantResultView
    from unittest.mock import MagicMock

    db_file = str(tmp_path / "test_more_options.db")
    db = Database(db_path=db_file)
    await db.init_db()

    mock_client = AsyncMock()
    mock_client.generate_json.return_value = {
        "cuisine": "Alternative unique Tacos",
        "location": "Austin, TX",
        "summary": "Great alternative tacos",
        "options": [
            {
                "name": "Torchy's Tacos",
                "cuisine_type": "Tacos",
                "price_range": "$$",
                "vibe": "Funky casual",
                "highlight_dish": "Trailer Park Taco",
                "why_go": "Creative tacos"
            }
        ]
    }
    extractor = CommitmentExtractor(client=mock_client)

    inquiry = DiningInquiry(
        id=1,
        channel_id="chan_1",
        message_id="msg_1",
        user_id="user_1",
        user_name="Alice",
        raw_text="where to eat?"
    )

    view = RestaurantResultView(
        inquiry=inquiry,
        cuisine="Tacos",
        location="Austin, TX",
        db=db,
        extractor=extractor
    )

    interaction = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.channel = MagicMock()
    interaction.channel.typing.return_value.__aenter__ = AsyncMock()
    interaction.channel.typing.return_value.__aexit__ = AsyncMock()

    await view.more_options.callback(interaction)

    # Verify loading response was sent
    interaction.response.edit_message.assert_awaited_once()
    loading_call = interaction.response.edit_message.await_args.kwargs
    assert "Querying AI Concierge for more Tacos" in loading_call["content"]
    assert loading_call["embed"].title == "🍳 AI Concierge is Cooking..."

    # Verify typing called
    interaction.channel.typing.assert_called_once()

    # Verify completion
    interaction.edit_original_response.assert_awaited_once()
    final_kwargs = interaction.edit_original_response.await_args.kwargs
    assert "Fresh options for **Tacos**" in final_kwargs["content"]

