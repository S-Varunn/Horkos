# 🎯 Horkus: the agent that lives where the conversation happens

Built for the Hackathon Challenge: *"Build a working agent that belongs somewhere new."*

Most AI agents wait inside a separate, lonely chat window. This agent lives ambiently inside group chats where conversations and everyday work actually happen. For this hackathon, we built and tested a fully working implementation for **Discord**. While our core architecture is built to support WhatsApp, Slack, and Telegram in the future, Discord is where it lives and operates today. It watches silently, steps in only when human conversation stalls out, and automatically tracks commitments so promises never slip through the cracks.

---

## Project Overview

### What We Built
We built an ambient group chat assistant that pays attention to what people actually say, steps in only when a conversation stalls, and silently keeps track of promises so nothing slips through the cracks.

Most bots are noisy. They barge into channels with giant blocks of text the second anyone types a keyword, which makes people want to kick them out immediately. We built the opposite: a patient, context-aware co-pilot that watches quietly, speaks only when needed, and does the boring administrative work in the background.

### The Problem and Use Case
Imagine a group chat with your friends on Discord (and eventually WhatsApp, Slack, or Telegram).

Someone drops a question: *"Where are we eating tonight?"*

One friend suggests Mexican. Another says they could do sushi. Then work pings someone, somebody gets distracted, and the chat goes dead for twenty minutes. Everyone gets hungry, nobody makes a choice, and the plan slowly dissolves into decision fatigue.

Our agent watches that unfold without interrupting. If the conversation flows naturally and people agree, it leaves everyone alone. But if the thread dies out and nobody replies for fifteen seconds, the bot steps in. It remembers what people were leaning toward, surfaces high-rated spots nearby matching the vibe, and offers quick one-click options so the group can make a decision and move on. If the group had already settled on a plan earlier that afternoon, it even reminds everyone: *"You all agreed on tacos thirty minutes ago, here is the spot."*

### Beyond Dinner Plans: Commitment Tracking
The second half of our agent solves the biggest black hole in every chat: casual promises.

In everyday conversation, people constantly make micro-commitments:
- *"I'll send over the updated slides in two hours."*
- *"I can host the volleyball game at 6pm today."*
- *"Let me review your pull request by tomorrow morning."*

Usually, these promises vanish into the chat scrollback, only to be remembered when someone asks *"Hey, did you ever do that?"* two days later.

Our bot catches these statements in real time. Instead of clogging the channel with an obnoxious message, it keeps the experience ambient: it adds a discreet reaction, extracts the task title and exact deadline, and schedules the event directly into your personal Google Calendar with a custom reminder.

### Why the Context Matters
Chat is where decisions and work actually happen, but modern chat apps are built for ephemeral messaging, not follow-through. Most productivity tools try to pull people out of chat into separate boards, tables, and project management apps that nobody wants to update.

By meeting groups where they already talk, listening for conversational context, and respecting group chat etiquette, our agent turns passive messaging into concrete plans and dependable follow-through without getting in the way.

---

## Key Features

- **Silence-Aware Dining and Plan Rescuer:** Listens for meal and hangout dilemmas. If conversation dies down for 15 seconds without consensus, it intervenes with cuisine buttons, interactive recommendations, and Yelp/Google Maps navigation links. If a consensus was already reached in the last 4 hours or recent chat, it instantly brings it back to avoid looping debates.
- **Context and Pronoun Disambiguation:** Real people say *"I'll finish that by five"* or *"I can take care of it tonight"*. The agent inspects the preceding messages in the channel to figure out what "that" or "it" refers to, ensuring calendar events get accurate, descriptive titles.
- **Auto-Fulfillment Detection:** When you later drop a link, attach a file, or say *"just deployed it"*, the agent evaluates whether your commitment was satisfied, marks it complete, updates your calendar, and adds an acknowledgment reaction.
- **Personal Google Calendar Integration:** Each user links their personal Google Calendar via OAuth 2.0. Events sync directly to their private calendar rather than an annoying shared spam board.
- **Customizable Event Templates:** Supports per-channel and per-user templates (`/channel-template` and `/calendar-template`) using placeholders like `{title}`, `{author}`, and `{channel}` with strict hierarchy resolution.
- **Model Context Protocol (MCP) and Webhooks:** Exposes a native JSON-RPC 2.0 MCP server and real-time webhook dispatcher (`commitment.created`, `commitment.completed`) so external tools, Cursor, Claude, or scripts can inspect and update commitments programmatically.
- **Ambient Reactions Over Message Spam:** Uses subtle emoji reactions on Discord instead of disruptive wall-of-text embeds, keeping conversations clean.

---

## Current Platform Support and Roadmap

### Implemented Today: Discord
For this hackathon, we focused on shipping a sharp, fully functional implementation for **Discord**. Everything documented and demonstrated runs live against the Discord Gateway API with slash commands, interactive buttons, ephemeral error handling, reactions, and conversational history reading.

### Planned for Future Releases: WhatsApp, Slack, and Telegram
Our architecture was intentionally designed with strict separation between the messaging interface and the intelligence pipeline:
- The core logic (`pipeline/filter.py`, `llm/extractor.py`, `db/database.py`, `integrations/calendar_service.py`, `scheduler/service.py`) is completely platform-independent.
- Adding a new messaging platform only requires a gateway adapter to listen for messages and dispatch responses.

Upcoming integrations on our roadmap:
1. **Slack:** Using the Slack Bolt SDK to bring silent commitment tracking and standup accountability to team workspaces and developer channels.
2. **WhatsApp:** Connecting via the Meta Cloud API to rescue dinner dilemmas and track informal promises in everyday friend and family group chats.
3. **Telegram:** Integrating with the Telegram Bot API for study groups, developer collectives, and community channels.

---

## System Architecture and Internals

```
                         [ Discord Gateway / Chat Stream ]
                                         │ (on_message)
                                         ▼
                   ┌───────────────────────────────────────────┐
                   │           pipeline/filter.py              │
                   │     Zero-latency Heuristic Pre-Filter     │
                   └─────┬───────────────────────────────┬─────┘
                         │                               │
        [Dining Dilemma Candidate]             [Commitment Candidate]
                         │                               │
                         ▼                               ▼
       ┌──────────────────────────────────┐    ┌──────────────────────────────────┐
       │     bot/cogs/events.py           │    │       pipeline/filter.py         │
       │  Silence Timeout Engine (15s)    │    │ Preceding Context Disambiguation │
       └───────────────┬──────────────────┘    └─────────────────┬────────────────┘
                       │                                         │
        (Human speaks -> Timer cancelled)                        ▼
        (15s silence  -> AI Suggestion)        ┌──────────────────────────────────┐
                       │                       │        llm/extractor.py          │
                       ▼                       │ Hermes 3 Structured Extractor    │
       ┌──────────────────────────────────┐    └─────────────────┬────────────────┘
       │     bot/ui/dining_views.py       │                      │
       │ Interactive Cuisine Selection    │                      ▼
       │ & Curated Restaurant Cards       │    ┌──────────────────────────────────┐
       └──────────────────────────────────┘    │        db/database.py            │
                                               │   Async SQLite State Store       │
                                               └─────┬──────────────────────┬─────┘
                                                     │                      │
                                                     ▼                      ▼
                                      ┌────────────────────┐  ┌───────────────────┐
                                      │ integrations/      │  │ scheduler/        │
                                      │ calendar_service.py│  │ service.py        │
                                      │ Google Calendar    │  │ APScheduler       │
                                      │ OAuth Sync         │  │ Impending Alerts  │
                                      └────────────────────┘  └───────────────────┘
```

### 1. Two-Stage Ingestion Pipeline
To keep bot response times instant and reduce LLM token costs by over 90%, all messages pass through a two-stage filter:
1. **Stage 1 (Local Regex & Heuristics):** Analyzes the raw text for intent verbs (`"i will"`, `"let me"`, `"i can"`, `"host"`), temporal anchors (`"at 6pm"`, `"by tomorrow"`, `"in 2 hours"`), and action verbs. Messages failing these rules exit immediately in sub-millisecond time.
2. **Stage 2 (Hermes 3 Structured Extraction):** Qualified candidates are evaluated with structured JSON outputs. The LLM extracts the clean task title, recipient, implied local deadline, and ISO-8601 UTC timestamp.

### 2. Silence-Aware Dining Engine
When someone asks an open-ended meal question (*"What's the dinner plan?"*, *"Where should we eat?"*), the bot:
1. Searches the last 3 minutes of chat history for any agreed-upon decision.
2. Checks the database for any resolved plan in that channel from the past 4 hours. If found, it immediately replies with the accepted plan to stop repetitive debate.
3. If undecided, it launches a 15-second countdown timer. If any human speaks in the channel during that window, the timer is aborted immediately. If silence persists for 15 seconds, the bot posts an interactive cuisine picker with direct restaurant suggestions.

### 3. Context & Pronoun Disambiguation
When users say ambiguous phrases like *"I'll review that tonight"*, the engine pulls the preceding 6 messages from the channel history and passes them to Hermes as conversational context. The model resolves the referent (e.g., identifying that "that" is the pull request posted two messages earlier) and generates a concrete calendar title.

### 4. Auto-Fulfillment Detection
Whenever a user sends a message or file attachment, the engine checks if they have active pending commitments. If the message matches fulfillment signals (e.g., file attachments, repo links, or completion phrases like *"here is the deck"*), the LLM compares the message against the active task. On a match, it marks the task complete in SQLite, updates the Google Calendar event title with a completion tag, triggers the webhook dispatcher, and adds a checkmark reaction.

### 5. Google Calendar OAuth & Multi-Tier Templates
- **Individual OAuth Flow:** Users run `/calendar-connect` to receive a Google sign-in link. An embedded local HTTP server handles the OAuth redirect and securely stores tokens per Discord user ID.
- **Template Hierarchy:** Event titles and descriptions resolve in priority order:
  1. Channel-specific template (set via `/channel-template`)
  2. User-specific template (set via `/calendar-template`)
  3. Default fallback template (`Commitment: {title}`)

---

## Project Structure

```
hackathon/
├── .env.example                 # Configuration environment template
├── config.py                    # Typed settings (pydantic-settings)
├── requirements.txt             # Python dependencies
├── main.py                      # Application bootstrap & entry point
├── pytest.ini                   # Pytest test suite configuration
├── credentials.json             # Google OAuth client secrets
│
├── db/                          # Database Layer
│   ├── models.py                # Pydantic schemas (Commitment, DiningInquiry, UserGoogleAuth)
│   └── database.py              # Async SQLite CRUD engine (aiosqlite)
│
├── llm/                         # Hermes 3 AI Integration
│   ├── client.py                # Multi-provider client (OpenRouter, Groq, Ollama)
│   ├── schemas.py               # Structured output Pydantic schemas
│   ├── prompts.py               # System prompts & extraction templates
│   └── extractor.py             # Commitment, dining plan & update drafting logic
│
├── pipeline/                    # Message Processing Pipeline
│   ├── filter.py                # Regex candidate pre-filter & dining inquiry detector
│   └── fulfillment.py           # Auto-fulfillment candidate matcher & evaluator
│
├── integrations/                # External Services & APIs
│   ├── calendar_service.py      # Google Calendar API, OAuth token manager & event sync
│   ├── oauth_server.py          # Asynchronous local OAuth callback listener
│   ├── webhook_service.py       # Webhook dispatcher for real-time external events
│   └── mcp_server.py            # Model Context Protocol (MCP) JSON-RPC 2.0 server
│
├── scheduler/                   # Temporal Alert Engine
│   └── service.py               # APScheduler recurring job for deadline tracking
│
├── bot/                         # Discord Bot Interface
│   ├── client.py                # Bot client initialization & slash command synchronization
│   ├── ui/
│   │   ├── embeds.py            # Embed builders for commitments & dining suggestions
│   │   ├── views.py             # Interactive buttons for manual task resolution
│   │   └── dining_views.py      # Cuisine selectors & pagination for restaurant recommendations
│   └── cogs/
│       ├── events.py            # Gateway event listeners (on_message, dining timer, fulfillment)
│       └── commands.py          # Slash commands (/commitments, /calendar-*, /channel-template)
│
├── simulate.py                  # Standalone CLI simulator for local manual testing
│
└── tests/                       # Automated Test Suite (60 tests across 10 modules)
    ├── test_calendar.py         # Google Calendar sync & mock mode tests
    ├── test_db.py               # Async SQLite database operations
    ├── test_dining.py           # Dining inquiry detection, timeout logic & views
    ├── test_disambiguation.py   # Pronoun resolution with conversational context
    ├── test_extractor.py        # Hermes 3 extraction & output parsing
    ├── test_filter.py           # Regex candidate heuristic tests
    ├── test_fulfillment.py      # Auto-fulfillment detection tests
    ├── test_scheduler.py        # Proactive reminder alert checks
    ├── test_templates.py        # Calendar template formatting & priority hierarchy
    └── test_webhook_mcp.py      # Webhook dispatching & MCP tool-call handling
```

---

## Setup and Installation

### 1. Requirements
- Python 3.10+
- A Discord Bot Token (with Message Content Intent enabled)
- An OpenRouter API Key (or Groq / local Ollama instance running Hermes 3)
- Optional: Google Cloud OAuth 2.0 credentials (`credentials.json`) for calendar sync

### 2. Installation
```bash
git clone https://github.com/S-Varunn/Horkos.git
cd Horkos
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Configure the following variables in `.env`:
```ini
DISCORD_TOKEN=your_discord_bot_token
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=your_openrouter_api_key
LLM_MODEL=nousresearch/hermes-3-llama-3.1-70b
DATABASE_PATH=commitment_radar.db
DEFAULT_TIMEZONE=America/New_York
ALERT_ADVANCE_MINUTES=10
AUTO_SCHEDULE_CALENDAR=true
```

### 4. Run the Automated Tests
Verify all 60 automated unit and integration tests:
```bash
./venv/bin/pytest
```

### 5. Launch the Bot
```bash
./venv/bin/python main.py
```

---

## Slash Commands Reference

| Command | Description |
| :--- | :--- |
| `/commitments` | View your active pending commitments in an interactive dashboard. |
| `/resolve [id]` | Manually mark a commitment as completed. |
| `/radar-status` | Display bot uptime, LLM provider, database health, and latency. |
| `/calendar-connect` | Generate an OAuth link to connect your personal Google Calendar. |
| `/calendar-status` | Check if your personal Google account is linked. |
| `/calendar-disconnect` | Revoke Google Calendar access and remove stored credentials. |
| `/calendar-template` | View or customize your personal calendar event format. |
| `/channel-template` | Set a channel-wide calendar template (requires Manage Channels). |
| `/export format:[markdown\|todoist\|json]` | Export your active commitments to Markdown, Todoist, or JSON. |

---

## Model Context Protocol (MCP) Integration

The bot includes a built-in MCP server (`integrations/mcp_server.py`) conforming to JSON-RPC 2.0. AI agents, IDE assistants (such as Cursor), and scripts can interact with the commitment store programmatically.

Supported tools:
- `list_commitments`: Filter commitments by user ID or status (`pending`, `completed`, `notified`).
- `resolve_commitment`: Mark a commitment complete and trigger downstream calendar updates.
- `create_commitment`: Manually register commitments from outside chat sources.

Run the MCP server over standard I/O:
```bash
./venv/bin/python integrations/mcp_server.py
```
