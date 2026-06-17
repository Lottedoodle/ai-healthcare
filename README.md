# AI HealthCare — Medical Triage Assistant

> A physician-facing clinical decision support chatbot powered by LangGraph, FastAPI, and Next.js 15.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-agent-blueviolet)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Backend](#backend)
  - [Frontend](#frontend)
  - [Database](#database)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [CLI Usage](#cli-usage)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**AI HealthCare** is a conversational medical triage assistant designed for hospital physicians. Doctors can interact with the system in **Thai or English** to quickly look up clinical information, check drug interactions, calculate dosages, and retrieve patient lab results — all through a secure, chat-based interface.

The agent uses an intent-based triage pipeline backed by **AWS Bedrock Knowledge Base** (RAG over drug labels and clinical guidelines), integrated with a **Supabase** Postgres backend for patient data, chat history, and authentication.

---

## Features

- **Intent Triage** — Classifies each query into one of five clinical intents:
  - `medical_knowledge` — Drug labels, clinical guidelines (RAG via AWS Bedrock KB)
  - `patient_data` — Lab results and vitals (HN-based lookup)
  - `dose_calculation` — Weight/renal-adjusted drug dosing with audit log
  - `drug_interaction` — DDI checks with structured reasoning
  - `emergency` — Emergency protocol guidance
- **Adaptive Routing** — Dynamically selects execution strategy per complexity: FAST / ReAct / Pipeline / Plan+Execute
- **Multi-turn Conversations** — Prompts for missing clinical fields (HN, weight, renal function) in Thai before executing
- **RAG** — AWS Bedrock Knowledge Base with LLM query rewriting and S3 lexical fallback
- **SSE Streaming** — Token-by-token responses with Thai status updates
- **Conversation Summarization** — Rolling summary to reduce token usage on long sessions
- **Auth & RLS** — Supabase JWT authentication with per-user row-level security
- **Persisted State** — LangGraph agent state stored in Postgres per session

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                               │
│              Next.js 15 Chat UI (Port 3000)                  │
│         Supabase Auth · SSE Streaming · Tailwind CSS         │
└────────────────────────┬────────────────────────────────────┘
                         │  Bearer JWT (HTTPS)
┌────────────────────────▼────────────────────────────────────┐
│                  FastAPI Backend (Port 8001)                  │
│               Auth middleware · REST + SSE                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │             LangGraph Agent (graph.py)                │   │
│  │  Triage → Field Validation → Route → Tools → Answer  │   │
│  └──────────┬───────────────────────┬───────────────────┘   │
│             │                       │                        │
│  ┌──────────▼──────┐    ┌──────────▼──────────────────┐    │
│  │ AWS Bedrock KB  │    │   Supabase / Postgres        │    │
│  │ (RAG + S3 fallb)│    │ Chat · Sessions · Lab Results│    │
│  └─────────────────┘    └─────────────────────────────-┘    │
└─────────────────────────────────────────────────────────────┘
```

### Agent Pipeline

```
User Message
    │
    ▼
[Triage Node] ──► Intent + Field Extraction
    │
    ▼
[Clarification] ──► Ask for HN / Weight / Renal (if missing)
    │
    ▼
[Router] ──► FAST | ReAct | Pipeline | Plan+Execute
    │
    ▼
[Tools] ──► search_medical_knowledge | get_patient_labs
         ──► check_drug_interaction | emergency_protocol
    │
    ▼
[Response] ──► Thai clinical summary + metadata
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent | LangGraph, LangChain, OpenAI / OpenRouter |
| Backend | FastAPI, Uvicorn, Pydantic |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS 4 |
| Auth & Database | Supabase (Auth + PostgREST + Postgres) |
| RAG | AWS Bedrock Knowledge Base, S3, boto3 |
| Package Manager | [uv](https://github.com/astral-sh/uv) (Python), npm (Node) |
| Python Version | 3.13 |

---

## Prerequisites

Before you begin, ensure you have:

- **Python 3.13** and [**uv**](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 18+** and npm
- A **Supabase** project (free tier works)
- An **OpenAI** or **OpenRouter** API key
- **AWS credentials** with access to Bedrock Knowledge Base (for medical knowledge search)

---

## Installation

### Backend

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/AI_HealthCare.git
cd AI_HealthCare

# 2. Install Python dependencies
uv sync

# 3. Set up environment variables (see Configuration section)
cp .env.example .env
# Edit .env with your keys
```

### Frontend

```bash
cd web/medical-chat-ui

# Install dependencies
npm install

# Set up environment variables
cp .env.local.example .env.local
# Edit .env.local with your Supabase + API URL
```

### Database

Run the SQL migration files **in order** on your Supabase project (SQL Editor):

```
database/schema.sql                    # Core tables: sessions, messages
database/002_rag_vector.sql            # Vector extension
database/003_bedrock_cohere_v3.sql     # Bedrock embedding config
database/004_lab_rls_read.sql          # RLS for lab data
database/005_conversation_summary.sql  # Conversation summary table
```

Optionally seed test lab data:

```
database/seed_labs_only.sql
```

---

## Configuration

### Backend — `.env`

Create a `.env` file in the project root:

```env
# ── LLM (pick one) ────────────────────────────────────────────
OPENAI_API_KEY=sk-...
# --- OR OpenRouter ---
# OPEN_ROUTER_KEY=sk-or-...
# OPEN_ROUTER_BASE=https://openrouter.ai/api/v1

OPENAI_MODEL_NAME=gpt-4o-mini        # default: gpt-4o-mini

# ── Supabase ──────────────────────────────────────────────────
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# ── Database (direct Postgres for lab queries) ────────────────
DATABASE_URL=postgresql://postgres:<password>@db.<project>.supabase.co:5432/postgres
# OR individual fields:
# PG_HOST=db.<project>.supabase.co
# PG_USER=postgres
# PG_PASSWORD=...
# PG_PORT=5432
# PG_DATABASE=postgres

# ── AWS Bedrock Knowledge Base ────────────────────────────────
AWS_KNOWLEDGE_BASE_ID=your-kb-id
AWS_REGION=ap-southeast-1             # default: ap-southeast-1

# (optional RAG tuning)
AWS_KB_NUMBER_OF_RESULTS=5
AWS_KB_QUERY_REWRITE=true
AWS_KB_QUERY_VARIANTS=3

# ── API ───────────────────────────────────────────────────────
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# ── Conversation Summary (optional) ──────────────────────────
CHAT_SUMMARY_ENABLED=true
CHAT_SUMMARY_RECENT_MESSAGES=10
CHAT_SUMMARY_MIN_BATCH=5
```

### Frontend — `web/medical-chat-ui/.env.local`

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_OR_ANON_KEY=eyJ...
NEXT_PUBLIC_API_URL=http://localhost:8001
```

---

## Running the Application

### Start Backend (FastAPI)

```bash
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8001
```

API available at `http://localhost:8001`  
Interactive docs at `http://localhost:8001/docs`

### Start Frontend (Next.js)

```bash
cd web/medical-chat-ui
npm run dev
```

Web UI available at `http://localhost:3000`

---

## CLI Usage

For quick testing without the web UI or authentication:

```bash
uv run python run_agent_cli.py
```

This opens an interactive terminal chat directly against the LangGraph agent.

---

## API Reference

All endpoints require `Authorization: Bearer <supabase-jwt>` except `/health`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/me` | Current authenticated user |
| `GET` | `/api/sessions` | List all chat sessions |
| `POST` | `/api/sessions` | Create a new session |
| `DELETE` | `/api/sessions` | Delete all sessions |
| `GET` | `/api/sessions/{id}` | Get session + message history |
| `POST` | `/api/sessions/{id}/messages` | Send message (sync response) |
| `POST` | `/api/sessions/{id}/messages/stream` | Send message (SSE streaming) |

Full interactive docs: `http://localhost:8001/docs`

---

## Project Structure

```
AI_HealthCare/
├── backend/
│   ├── main.py                  # FastAPI application & routes
│   ├── service.py               # Chat orchestration & SSE streaming
│   ├── auth.py                  # Supabase JWT validation middleware
│   ├── schemas.py               # Pydantic request/response models
│   ├── context.py               # Request-scoped context vars
│   ├── agent/
│   │   └── graph.py             # LangGraph agent (triage, routing, tools)
│   ├── data/
│   │   ├── chat_store.py        # Chat session/message persistence
│   │   ├── labs.py              # Patient lab result queries
│   │   └── conversation_summary.py
│   └── rag/
│       └── knowledge_base.py    # AWS Bedrock KB search + S3 fallback
├── database/
│   ├── schema.sql               # Core schema migration
│   ├── 002_rag_vector.sql
│   ├── 003_bedrock_cohere_v3.sql
│   ├── 004_lab_rls_read.sql
│   ├── 005_conversation_summary.sql
│   └── seed_labs_only.sql
├── web/medical-chat-ui/         # Next.js 15 frontend
│   ├── src/app/                 # Pages: /, /login, /chat
│   ├── src/components/          # ChatApp, sidebar, messages, input
│   ├── src/contexts/            # Auth context provider
│   └── src/lib/                 # API client, SSE stream, Supabase
├── run_agent_cli.py             # CLI entry point
├── pyproject.toml               # Python dependencies
├── uv.lock                      # Locked dependency versions
└── .python-version              # Python 3.13
```

---

## Roadmap

- [ ] Add unit and integration tests
- [ ] Docker & docker-compose setup
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] `.env.example` file at root
- [ ] Replace mock tools (vitals, drug interaction, emergency) with real integrations
- [ ] Patient HN lookup across hospital HIS
- [ ] Role-based access control (physician vs. nurse)
- [ ] Audit logging for clinical safety compliance
- [ ] Multi-hospital support

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Commit your changes: `git commit -m 'feat: add some feature'`
4. Push to the branch: `git push origin feature/your-feature-name`
5. Open a Pull Request

Please follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---


> **Note:** This project is under active development (v0.1.0). Some clinical tools (vitals, drug interaction, emergency protocols) currently return mock data and are not yet connected to live hospital systems. Do not use in production clinical environments without proper validation.
