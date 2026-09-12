import asyncio
import sys
from datetime import datetime, timezone
from db.database import Database
from db.models import Commitment, CommitmentStatus
from llm.extractor import CommitmentExtractor
from pipeline.filter import is_commitment_candidate
from integrations.calendar_service import GoogleCalendarService
from config import settings


async def run_simulation():
    print("=" * 60)
    print("🎯 Commitment Radar: Interactive Terminal Test")
    print(f"Model: {settings.llm_model} ({settings.llm_base_url})")
    print("Type a message below to test the detection pipeline.")
    print("Type 'exit' or press Ctrl+C to quit.")
    print("=" * 60)

    db = Database(settings.database_path)
    await db.init_db()
    extractor = CommitmentExtractor()
    cal_service = GoogleCalendarService()

    default_tests = [
        "I'll send that pitch deck to Sarah by 4 PM",
        "Let me review this PR after lunch",
        "Can someone send me the latest invoice?",  # Non-commitment
        "Will push the fix in 30 minutes"
    ]

    print("\n💡 Suggested test phrases:")
    for i, t in enumerate(default_tests, 1):
        print(f"  {i}. \"{t}\"")
    print()

    while True:
        try:
            user_input = input("\n💬 Enter message (or 1-4 for quick test): ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                break
            if user_input in ("1", "2", "3", "4"):
                user_input = default_tests[int(user_input) - 1]
                print(f"Testing: \"{user_input}\"")

            print("\n🔍 Stage 1: Running Heuristic Pre-Filter...")
            is_candidate, reason = is_commitment_candidate(user_input)
            print(f"   Candidate Match: {'✅ YES' if is_candidate else '❌ NO'} (Reason: {reason})")

            if not is_candidate:
                print("   ⏩ Filtered out at Stage 1 (0 tokens consumed, skipped LLM).")
                continue

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
                # Schedule Google Calendar event
                deadline_dt = datetime.fromisoformat(extracted.implied_deadline_utc.replace("Z", "+00:00")).replace(tzinfo=None)
                
                temp_commitment = Commitment(
                    user_id="test_user_123",
                    user_name="TestUser",
                    channel_id="test_channel_001",
                    message_id=str(int(datetime.now(timezone.utc).timestamp())),
                    raw_text=user_input,
                    task_title=extracted.task_title,
                    recipient=extracted.recipient,
                    deadline_utc=deadline_dt,
                    relative_deadline_text=extracted.relative_deadline_text,
                    context_snippet=extracted.context_snippet
                )

                cal_res = await cal_service.schedule_commitment_event(temp_commitment)
                cal_id = cal_res.get("id")
                cal_link = cal_res.get("htmlLink")

                print(f"\n📅 Google Calendar Scheduled:")
                print(f"   Event ID: {cal_id}")
                print(f"   Mode:     {'Mock / Simulated Link' if cal_res.get('is_mock') else 'Live Google Calendar'}")
                print(f"   Web Link: {cal_link}")
                print(f"   Popups:   {cal_service.default_reminders} minutes before deadline")

                # Save to database
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
                    status=CommitmentStatus.PENDING,
                    calendar_event_id=cal_id,
                    calendar_event_link=cal_link
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

        except (KeyboardInterrupt, EOFError):
            print("\nExiting simulation.")
            break


if __name__ == "__main__":
    asyncio.run(run_simulation())
