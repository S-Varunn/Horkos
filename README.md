# 🎯 Commitment Radar: Ambient Discord Agent

> **Built for the Hackathon Challenge: *"Build a working agent that belongs somewhere new."***

Most AI agents wait inside a separate, lonely chat window. **Commitment Radar** lives ambiently inside Discord channels where conversations and work naturally happen. It passively detects implicit micro-commitments, tracks deadlines, and surfaces one-click resolution controls right before promises slip through the cracks.

---

## ⚡ The Problem & Solution

- **The Problem**: People constantly make informal micro-commitments in chat (*"I'll send that PDF later tonight"*, *"Let me look at this after lunch"*, *"Will review by EOD"*) without ever logging them as calendar events or tickets.
- **Where it lives**: An ambient listener inside Discord.
- **The UX**:
  1. **Passive Tracking**: Detects micro-commitments in real-time. Quietly adds a `🎯` reaction and registers the task.
  2. **Proactive Alerts**: 30 minutes before the implied deadline, surfaces an interactive Discord message with action buttons:
     - `[✅ Mark Done]`
     - `[⏳ Push 1 Hour]`
     - `[📝 Draft Update]` (Powered by Hermes AI to draft an authentic status update)

---

## 🏗️ Modular Architecture

```
                         [ Discord Gateway ]
                                  │ (on_message event stream)
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ pipeline/filter.py                                                     │
│ Stage 1: Local Regex & Heuristic Pre-Filter (0 tokens, 0ms latency)    │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ (Candidate matches only)
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ llm/extractor.py                                                       │
│ Stage 2: Hermes Agent Structured Extractor (Tool-Calling / JSON)       │
│ - Disambiguates task, recipient, context, relative deadline to UTC     │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ (Structured Commitment Object)
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ db/database.py & db/models.py                                          │
│ SQLite Async State Store (aiosqlite / Pydantic)                        │
│ - Stores commitments: PENDING, NOTIFIED, COMPLETED, SNOOZED            │
└───────────────────────┬────────────────────────┬───────────────────────┘
                        │                        │
         (Passive background check)       (Interactive user actions)
                        ▼                        ▼
┌────────────────────────────────┐      ┌────────────────────────────────┐
│ scheduler/service.py           │      │ bot/ui/views.py & commands.py  │
│ APScheduler (AsyncIO Loop)     │      │ Discord UI Components          │
│ - Triggers alert at T - 30m    │      │ - [✅ Mark Done]               │
│ - Triggers alert at deadline   │      │ - [⏳ Push 1 Hour]             │
└───────────────┬────────────────┘      │ - [📝 Draft Update Modal]      │
                │                       └────────────────────────────────┘
                └───────────────► Discord Interactive Embed ◄─────────────┘
```

---

## 📂 Project Structure

```
hackathon/
├── .env.example                 # Configuration template
├── config.py                    # Typed settings (pydantic-settings)
├── requirements.txt             # Project dependencies
├── main.py                      # Application entry point
├── pytest.ini                   # Pytest test runner config
│
├── db/                          # Database & State Store
│   ├── models.py                # Pydantic data schemas
│   └── database.py              # Async SQLite CRUD engine
│
├── llm/                         # Hermes LLM Integration
│   ├── client.py                # Provider-agnostic client (OpenRouter/Groq/Ollama)
│   ├── schemas.py               # Structured output definitions
│   ├── prompts.py               # Hermes system prompts
│   └── extractor.py             # Commitment extraction & drafting logic
│
├── pipeline/                    # Traffic Ingestion & Filtering
│   └── filter.py                # 2-stage heuristic pre-filter (saves 90% API tokens)
│
├── scheduler/                   # Temporal Alert Engine
│   └── service.py               # APScheduler async background task
│
├── bot/                         # Discord Interface Layer
│   ├── client.py                # Discord bot client & intents
│   ├── ui/
│   │   ├── embeds.py            # Rich Discord embed formatters
│   │   └── views.py             # Interactive buttons & modals
│   └── cogs/
│       ├── events.py            # on_message listener & event routing
│       └── commands.py          # Slash commands (/commitments, /radar-status)
│
└── tests/                       # Automated Test Suite (27 passing tests)
    ├── test_filter.py           # Pre-filter heuristic verification
    ├── test_db.py               # Async SQLite database testing
    ├── test_extractor.py        # LLM parsing with mock client
    └── test_scheduler.py        # Proactive alert trigger tests
```

---

## 🚀 Getting Started

### 1. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in:
- `DISCORD_TOKEN`: Your bot token from [Discord Developer Portal](https://discord.com/developers/applications).
  > **Crucial**: Ensure **Message Content Intent** is enabled under the Bot tab!
- `LLM_API_KEY`: Your OpenRouter or Groq API key (or leave empty if using local Ollama).
- `LLM_MODEL`: `nousresearch/hermes-3-llama-3.1-8b:free` (or local `hermes3`).

### 3. Run Automated Tests
```bash
./venv/bin/pytest -v
```

### 4. Start the Agent
```bash
./venv/bin/python main.py
```

---

## 🎮 Discord Commands & Interaction

- **Passive Detection**: Say in any channel: *"I'll send that updated PDF to Sarah by 4 PM"*.
  - Commitment Radar will react with `🎯` and reply with an action card.
- **/commitments**: Opens your active commitments dashboard.
- **/resolve [id]**: Manually marks a commitment as completed.
- **/radar-status**: Displays health, latency, model parameters, and connection status.

---

## 🔮 Roadmap (Phase 2: Killer Features)

- [ ] **🌟 Auto-Fulfillment Detection**: When a user drops a file or follow-up (*"Here's the PDF"*) in the same channel, the agent automatically detects fulfillment and marks the commitment resolved without bothering the user.
- [ ] **🌟 Multi-step Context Disambiguation**: Autonomously fetch prior channel history to resolve ambiguous pronouns (*"I'll send that over soon"* -> fetches context to identify the file).
- [ ] **🌟 Bi-directional Sync**: One-click webhook export to Google Calendar, Todoist, or Notion via Model Context Protocol (MCP).
