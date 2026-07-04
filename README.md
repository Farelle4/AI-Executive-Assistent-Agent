# AI Executive Assistant Agent

> An AI agent that lives in your Gmail inbox — it reads incoming emails, checks your Google Calendar, drafts professional replies in the sender's language, and creates calendar events automatically once you send the draft.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-ReAct_Agent-1C3C3C?logo=langchain)
![OpenAI](https://img.shields.io/badge/LLM-OpenAI_GPT--4o--mini-412991?logo=openai&logoColor=white)
![Supabase](https://img.shields.io/badge/Memory-Supabase-3ECF8E?logo=supabase)
![Gmail](https://img.shields.io/badge/Gmail_API-integrated-EA4335?logo=gmail)
![Google Calendar](https://img.shields.io/badge/Google_Calendar-integrated-4285F4?logo=googlecalendar)
![Tests](https://img.shields.io/badge/tests-64_passed-brightgreen)

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [How It Works](#how-it-works)
3. [Project Structure](#project-structure)
4. [Tech Stack](#tech-stack)
5. [Setup & Installation](#setup--installation)
6. [Supabase Schema](#supabase-schema)
7. [Running the Agent](#running-the-agent)
8. [Key Technical Decisions](#key-technical-decisions)
9. [Tests](#tests)

---

## What It Does

Managing meeting requests by email is repetitive and time-consuming. Every request requires reading the email, checking your calendar, composing a reply, and later creating the event once confirmed.

This agent automates the full pipeline:

- **Reads** unread emails from your Gmail inbox every 5 minutes
- **Classifies** intent (meeting request, confirmation, cancellation, or other)
- **Checks** your Google Calendar for availability at the requested time
- **Drafts** a reply — accepting, declining with 3 alternative slots, or asking for more details if the date was vague
- **Replies in the sender's language** — French email → French reply, English → English
- **Saves the draft** as a Gmail reply thread (not a new email)
- **Creates the calendar event** automatically once you send the draft

Emails that are not meeting-related are silently ignored (or replied to if the sender is a VIP contact).

---

## How It Works

### Agent Pipeline (9 steps, enforced via system prompt)

```
Incoming email (JSON)
        │
        ▼
STEP 1  check_if_processed(thread_id)
        │ already seen → STOP
        │ new → mark_as_read → continue
        ▼
STEP 2  get_user_context(sender)
        │ → name, is_vip, notes
        ▼
STEP 3  classify_email(subject, sender, body)
        │ → intent, raw_date, start_raw_time, end_raw_time, language
        │   (language detected from body only — never subject or preferences)
        ▼
STEP 4  Route by intent
        │ not meeting + not VIP → save_to_memory(..."IGNORED") → STOP
        ▼
STEP 5  check_calendar(raw_date, start_raw_time, end_raw_time)
        │ → is_free, start_iso, end_iso
        ▼
STEP 6  generate_draft(...)
        │ is_free=True  → acceptance reply with confirmed time
        │ is_free=False → decline + propose 3 alternative slots (spread through day)
        │ start_iso=""  → ask for a more precise date and time
        ▼
STEP 7  save_to_memory(thread_id, ..."DRAFTED")   ← must run BEFORE save_draft
        ▼
STEP 8  save_draft(to, subject, draft_body, thread_id, start_iso, end_iso)
        │ → Gmail draft saved as reply in the original thread
        │ → if start_iso set: pending_event saved to Supabase
        ▼
STEP 9  save_user_memory(sender, name, is_vip, ...)
```

### Calendar Event Creation (run_sent_batch)

```
Every polling pass
        │
        ▼
Fetch last 50 sent emails → deduplicate by thread_id
        │
        ▼
For each unique thread → get_pending_event(thread_id)
        │ no pending event → skip
        │ sent_at < pending_created_at → skip (stale email guard)
        ▼
create_event(title, start_iso, end_iso)
mark_event_created(thread_id)
```

---

## Project Structure

```
agentic-ai-project/
│
├── main.py                        ← CLI entry point (polling loop)
├── config.py                      ← Logging config, .env loader
├── requirements.txt               ← Dependencies + Supabase schema
│
├── src/
│   ├── orchestrator.py            ← AgentOrchestrator: ReAct agent + all tools
│   │                                 run_batch() → process unread emails
│   │                                 run_sent_batch() → create pending calendar events
│   │
│   ├── email_classifier.py        ← EmailClassifier: LLM → structured output (Pydantic)
│   │                                 intent, language, raw_date, start_raw_time, end_raw_time
│   │
│   ├── draft_response.py          ← DraftResponse: build context-aware email replies
│   │                                 _build_start_iso() → 3-step date/time parser
│   │                                 generate_draft_response() → confirmed / busy / vague paths
│   │
│   ├── gmail_client.py            ← GmailClient: fetch unread, save drafts, mark read
│   │                                 get_recently_sent() → detect sent drafts
│   │
│   ├── google_calendar.py         ← GoogleCalendar: free/busy queries, event creation
│   │                                 is_time_free() → checks actual meeting duration
│   │                                 get_free_slots_for_day() → 08:00–18:00 in 30-min slots
│   │
│   ├── memory_client.py           ← MemoryClient: Supabase single-table store
│   │                                 One row per thread (email → pending_event → done)
│   │                                 save_email(), is_processed(), save_pending_event()
│   │                                 get_user(), upsert_user()
│   │
│   └── google_calendar_auth.py    ← OAuth2 credential manager (token.json)
│
├── tests/
│   ├── test_email_classifier.py   ← LLM chain mocked with MagicMock
│   ├── test_draft_response_parsing.py ← Date parsing, slot logic, first-name extraction
│   ├── test_gmail_client.py       ← Draft threading, sent parsing
│   ├── test_google_calendar.py    ← free/busy mocks, slot generation
│   ├── test_memory_client.py      ← Supabase query chain mocks
│   ├── test_orchestrator.py       ← Tool registry, agent wiring
│   └── test_main.py               ← CLI args, polling loop, KeyboardInterrupt
│
├── credentials.json               ← Google OAuth client secrets (not committed)
└── .env                           ← API keys and config (not committed)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent framework | LangChain `create_agent` (ReAct loop) |
| LLM | Openai `gpt-4o-mini` (swappable via `LLM_MODEL` env var) |
| Email classification | LangChain LCEL + `with_structured_output` (Pydantic schema) |
| Draft generation | LangChain LCEL chain + `StrOutputParser` |
| Date/time parsing | `dateparser` with German, English and French format support |
| Gmail | Google Gmail API v1 (OAuth 2.0) |
| Google Calendar | Google Calendar API v3 (free/busy + event creation) |
| Memory / persistence | Supabase (PostgreSQL) — single-table design |
| Testing | `pytest` + `unittest.mock` — 64 tests, no real credentials needed |

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- A Google account with Gmail and Google Calendar
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A [Supabase](https://supabase.com) project (free tier available)

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/agentic-ai-project.git
cd agentic-ai-project
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Google Cloud setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project
3. Enable **Gmail API** and **Google Calendar API**
4. Create OAuth 2.0 credentials → Desktop app
5. Download the JSON file → save as `credentials.json` in the project root
6. Run the agent once — a browser window will open for consent → `token.json` is created automatically

**Required OAuth scopes:**
```
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/calendar
```

### 3. Supabase setup

1. Create a project at [supabase.com](https://supabase.com)
2. Run the SQL in the [Supabase Schema](#supabase-schema) section below in the SQL Editor
3. Copy your **Project URL** and **anon key** from Settings → API

### 4. Environment variables

Create a `.env` file at the project root:

```env
# LLM
OPENAI_API_KEY=sk-...
LLM_MODEL=openai:gpt-4o-mini              

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJ...

```

---

## Supabase Schema

Run this SQL in your Supabase SQL Editor:

```sql
CREATE TABLE memory (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  record_type text        NOT NULL,      -- 'email' | 'pending_event' | 'user'
  message_id  text,                      -- Gmail thread_id  (email / pending_event rows)
  subject     text,                      -- email subject    (email / pending_event rows)
  sender      text,                      -- sender address   (email / pending_event rows)
                                         -- contact address  (user rows)
  language    text,                      -- detected body language
  intent      text,                      -- classifier intent (meeting_request, other, …)
  status      text,                      -- DRAFTED | IGNORED | ERROR | pending | done
  notes       text,                      -- JSON {"start_iso": "…", "end_iso": "…"} for pending_event
                                         -- free-text notes for user rows
  name        text,                      -- display name (user rows)
  is_vip      boolean     DEFAULT false, -- VIP flag (user rows)
  created_at  timestamptz DEFAULT now()
);

-- Prevent duplicate threads
CREATE UNIQUE INDEX memory_message_id_unique
  ON memory (message_id)
  WHERE record_type IN ('email', 'pending_event');
```

**Row lifecycle:**

```
INSERT record_type='email'          ← save_to_memory (Step 7)
   │
   └─ UPDATE record_type='pending_event'  ← save_draft when is_free=True (Step 8)
           │
           └─ UPDATE status='done'        ← run_sent_batch after calendar event created
```

---

## Running the Agent

```bash
# Single pass (process current unread emails + check sent for pending events)
python main.py --once

# Continuous polling every 5 minutes (default)
python main.py

# Custom polling interval (e.g. every 2 minutes)
python main.py --interval 120

# Enable verbose DEBUG logging
python main.py --debug --once
```

### Running automatically on Windows (auto-start on login)

The recommended approach on Windows is to use the **Startup folder** — the agent starts silently in the background every time you log in, with no terminal window.

Two files handle this (already included in the repo):

**`run_agent_background.vbs`** — launches Python with no visible window:
```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd.exe /c ""C:\Python314\python.exe D:\Projekte\Agentic_AI_project\main.py >> D:\Projekte\Agentic_AI_project\agent.log 2>&1""", 0, False
```

**Install** — create a shortcut to the VBS in your Startup folder (run once in PowerShell):
```powershell
$startupFolder = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut("$startupFolder\AI Email Agent.lnk")
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"D:\Projekte\Agentic_AI_project\run_agent_background.vbs`""
$shortcut.WorkingDirectory = "D:\Projekte\Agentic_AI_project"
$shortcut.Save()
```

**Start immediately** (without rebooting):
```powershell
Start-Process "wscript.exe" -ArgumentList "`"D:\Projekte\Agentic_AI_project\run_agent_background.vbs`"" -WindowStyle Hidden
```

**Monitor logs** in real time:
```powershell
Get-Content D:\Projekte\Agentic_AI_project\agent.log -Tail 30 -Wait
```

**Stop the agent**:
```powershell
Get-Process python | Stop-Process -Force
```

> **Note:** the agent only runs while Windows is on and you are logged in. For 24/7 operation without your computer, deploy to a cloud worker (Railway, Render, Fly.io).

---

## Key Technical Decisions

**`mark_as_read` in Step 1, before any LLM call.**
If the agent crashes mid-pipeline or the LLM skips `save_to_memory`, the email stays processed from Gmail's perspective. Without this, the same email would be re-analyzed on every polling pass.

**`save_to_memory` (Step 7) ordered before `save_draft` (Step 8).**
`save_draft` internally calls `save_pending_event`, which does an UPDATE on the `email` row. If that row doesn't exist yet, a second orphaned `pending_event` row gets inserted instead. Strict ordering prevents this.

**Language from the body only — never from subject or stored preferences.**
An early version inherited the language from the user's stored profile. After one French email, all future replies to that contact were in French — regardless of what language they wrote in. The fix: re-detect from the body on every email.

**LLM extracts raw strings; Python parses dates.**
The classifier returns `raw_date="next Friday"` and `start_raw_time="14h30"` as literal text. All actual date parsing — including French `Xh/XhYY` format, relative-word stripping, and a 3-step fallback strategy — happens in `_build_start_iso()` with `dateparser`. This keeps parsing testable and deterministic.


---

## Tests

```bash
# Run full test suite
pytest tests/ -v

# Run a specific module
pytest tests/test_memory_client.py -v
```

All 64 tests run without real credentials — Gmail, Google Calendar, Supabase, and the LLM are fully mocked.

| Module | Tests | What's covered |
|---|---|---|
| `test_email_classifier.py` | 5 | LLM chain mock, structured output, field extraction |
| `test_draft_response_parsing.py` | 19 | Date/time parsing, first-name extraction, French format |
| `test_gmail_client.py` | 7 | Draft threading, sent parsing, mark-as-read |
| `test_google_calendar.py` | 6 | free/busy mock, slot generation, event creation |
| `test_memory_client.py` | 11 | Supabase query chains, dedup, pending event lifecycle |
| `test_orchestrator.py` | 10 | Tool registry, agent wiring, run_sent_batch guards |
| `test_main.py` | 6 | CLI args, polling loop, KeyboardInterrupt handling |
