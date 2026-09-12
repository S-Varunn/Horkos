import asyncio
import sys
from datetime import datetime, timezone
from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from pipeline.filter import is_commitment_candidate, is_dining_inquiry
from db.models import Commitment, CommitmentStatus, DiningInquiry, DiningInquiryStatus
from config import settings


async def run_simulation():
    print("=" * 60)
    print("🎯 Commitment Radar + Ambient Dining: Interactive Simulator")
    print(f"Model: {settings.llm_model} ({settings.llm_base_url})")
    print("Type a message below to test the detection pipelines.")
    print("Type 'exit' or press Ctrl+C to quit.")
    print("=" * 60)

    db = Database(settings.database_path)
    await db.init_db()
    extractor = CommitmentExtractor()

    default_tests = [
        "where you want to eat",                    # Dining inquiry (deadlock candidate)
        "what is the dinner plan?",                  # Dining inquiry
        "I'll send that pitch deck to Sarah by 4 PM",# Commitment
        "Let me review this PR after lunch",         # Commitment
        "Can someone send me the latest invoice?",   # Normal message (ignored)
        "Will push the fix in 30 minutes"            # Commitment
    ]

    print("\n💡 Suggested test phrases:")
    for i, t in enumerate(default_tests, 1):
        print(f"  {i}. \"{t}\"")
    print()

    while True:
        try:
            user_input = input("\n💬 Enter message (or 1-6 for quick test): ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                break
            if user_input in [str(i) for i in range(1, len(default_tests) + 1)]:
                user_input = default_tests[int(user_input) - 1]
                print(f"Testing: \"{user_input}\"")

            print("\n🔍 Stage 1: Running Heuristic Pre-Filters...")
            
            # Check Dining Inquiry
            is_dining, dining_reason = is_dining_inquiry(user_input)
            print(f"   🍽️ Dining Inquiry Match:   {'✅ YES' if is_dining else '❌ NO'} ({dining_reason})")

            # Check Commitment
            is_candidate, reason = is_commitment_candidate(user_input)
            print(f"   🎯 Commitment Match:       {'✅ YES' if is_candidate else '❌ NO'} ({reason})")

            if is_dining:
                # First, check if a plan was already accepted for this meal
                recent_resolved = await db.get_recent_resolved_dining_inquiry(
                    "sim_channel_001",
                    within_minutes=settings.accepted_plan_memory_hours * 60
                )
                if recent_resolved and recent_resolved.chosen_cuisine:
                    print(f"\n💡 CONSENSUS MEMORY TRIGGERED:")
                    print(f"   Bot: \"Hey TestUser! It looks like a dinner plan was already confirmed: '{recent_resolved.chosen_cuisine}'!\"")
                    print(f"   Bot: \"Do you want to [👍 Stick with {recent_resolved.chosen_cuisine}] or [🔄 Pick Somewhere New]?\"")
                    continue

                print(f"\n⏳ Starting {settings.dining_inquiry_timeout_seconds}s Ambient Silence Countdown (Evaluated last {settings.dining_history_window_minutes}m: no prior plan found)...")
                inquiry = DiningInquiry(
                    channel_id="sim_channel_001",
                    message_id=str(int(datetime.now(timezone.utc).timestamp())),
                    user_id="sim_user_1",
                    user_name="TestUser",
                    raw_text=user_input,
                    status=DiningInquiryStatus.WAITING
                )
                saved_inquiry = await db.add_dining_inquiry(inquiry)
                print(f"   💾 Saved Dining Inquiry #{saved_inquiry.id} to DB (status: WAITING)")
                print(f"   [Simulating silence timer... {settings.dining_inquiry_timeout_seconds}s elapsed with no response]")
                await db.update_dining_inquiry_status(saved_inquiry.id, DiningInquiryStatus.TIMED_OUT)
                
                print("\n🛎️ AGENT INTERVENTION TRIGGERED:")
                print(f"   Bot: \"Hey everyone! TestUser asked: '{user_input}', but no one responded in {settings.dining_inquiry_timeout_seconds}s!\"")
                print("   Bot: \"What kind of food are you in the mood for? [🍕 Pizza] [🍣 Sushi] [🌮 Mexican] [🍔 Burgers] [🎲 Surprise Me]\"")
                
                sim_cuisine = "Sushi / Japanese"
                print(f"\n🤖 Simulating User picking '{sim_cuisine}' -> Calling Hermes Restaurant Suggester...")
                start_t = datetime.now(timezone.utc)
                recs = await extractor.generate_restaurant_suggestions(cuisine_or_craving=sim_cuisine, location=settings.default_location)
                elapsed = (datetime.now(timezone.utc) - start_t).total_seconds()
                print(f"   ⏱️ LLM Latency: {elapsed:.2f}s")
                print(f"   Summary: {recs.summary}")
                for idx, opt in enumerate(recs.options, 1):
                    print(f"     {idx}. 📍 {opt.name} ({opt.price_range}) - {opt.vibe}")
                    if opt.highlight_dish:
                        print(f"        ⭐ Must Try: {opt.highlight_dish}")
                    if opt.why_go:
                        print(f"        💡 {opt.why_go}")
                
                await db.update_dining_inquiry_status(saved_inquiry.id, DiningInquiryStatus.RESOLVED, chosen_cuisine=sim_cuisine)
                print(f"\n   ✅ Inquiry #{saved_inquiry.id} marked as RESOLVED (Cuisine: {sim_cuisine})")

            elif is_candidate:
                print("\n🤖 Stage 2: Calling Hermes 3 Extractor...")
                start_t = datetime.now(timezone.utc)
                extracted = await extractor.extract_commitment(
                    message_text=user_input,
                    author_name="TestUser",
                    reference_time=start_t.replace(tzinfo=None)
                )
                elapsed = (datetime.now(timezone.utc) - start_t).total_seconds()
                print(f"   ⏱️ LLM Latency: {elapsed:.2f}s")
                print(f"   Hermes Is Commitment: {'✅ True' if extracted.is_commitment else '❌ False'}")
                print(f"   Task Title:           {extracted.task_title}")
                print(f"   Recipient:            {extracted.recipient}")
                print(f"   Mentioned Timeframe:  \"{extracted.relative_deadline_text}\"")
                print(f"   Calculated UTC:       {extracted.implied_deadline_utc}")
                print(f"   Confidence Score:     {extracted.confidence_score:.2f}")

                if extracted.is_commitment:
                    # Save to database
                    deadline_dt = datetime.fromisoformat(extracted.implied_deadline_utc.replace("Z", "+00:00")).replace(tzinfo=None)
                    commitment = Commitment(
                        user_id="test_user_123",
                        user_name="TestUser",
                        channel_id="test_channel_001",
                        message_id=str(int(datetime.now(timezone.utc).timestamp())),
                        raw_text=user_input,
                        task_title=extracted.task_title,
                        recipient=extracted.recipient,
                        deadline_utc=deadline_dt,
                        relative_deadline_text=extracted.relative_deadline_text,
                        context_snippet=extracted.context_snippet,
                        status=CommitmentStatus.PENDING
                    )
                    saved = await db.add_commitment(commitment)
                    print(f"\n💾 Saved to SQLite DB: Commitment #{saved.id} status: PENDING")

                    # Test Hermes Draft Update
                    print("\n📝 Testing Hermes Contextual Draft Update Generation...")
                    draft = await extractor.generate_resolution_draft(
                        task_title=saved.task_title,
                        recipient=saved.recipient,
                        original_deadline_text=saved.relative_deadline_text,
                        speaker_name=saved.user_name
                    )
                    print(f"   Suggested Reply: \"{draft.suggested_reply}\"")
            else:
                print("   ⏩ Filtered out at Stage 1 (0 tokens consumed, skipped LLM).")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting simulation.")
            break


if __name__ == "__main__":
    asyncio.run(run_simulation())
