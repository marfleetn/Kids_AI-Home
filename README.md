# Kids AI Home

A self-hosted AI chat platform for kids with parental controls, conversation logging, and per-child personality customization. Powered by Ollama serving local LLM models (DeepSeek, Llama, Qwen).

## Features

- **3 LLM Models** — DeepSeek R1 8B, Llama 3.1 8B, Qwen 2.5 7B via Ollama
- **Per-child profiles** — each child has their own login (PIN-based), avatar, and allowed models
- **Custom personalities** — set a unique AI personality/tutor style per child
- **Content filtering** — regex-based input/output filtering blocks inappropriate topics
- **Safety system prompt** — every response is guided by child-safety rules
- **Daily message limits** — configurable per child
- **Conversation logging** — all messages stored in SQLite for parent review
- **Parent dashboard** — view stats, browse full conversation logs, see blocked attempts
- **Streaming responses** — real-time token-by-token chat output

## Requirements

- Docker and Docker Compose
- 64GB RAM recommended (runs 3 x 7-8B models)
- ~25GB disk for model storage

## Quick Start

```bash
# 1. Clone and configure
git clone <this-repo>
cd Kids_AI-Home
cp .env.example .env
# Edit .env — set SECRET_KEY and ADMIN_PASSWORD

# 2. Configure child profiles
# Edit config/children.json — set names, PINs, ages, personalities

# 3. Start everything
docker compose up -d

# 4. Wait for models to download (first run only, check progress with):
docker logs -f model-loader

# 5. Access the app
# Kids login:   http://localhost:8080
# Parent panel:  http://localhost:8080/admin
```

## Configuration

### Child Profiles (`config/children.json`)

Each child entry supports:

| Field | Description |
|---|---|
| `id` | Unique identifier |
| `name` | Display name |
| `age` | Used for context in personality prompts |
| `pin` | Login PIN |
| `avatar` | Emoji avatar |
| `allowed_models` | Which models this child can use |
| `personality` | System prompt defining AI behavior for this child |
| `max_messages_per_day` | Daily message limit |
| `max_message_length` | Max characters per message |
| `session_timeout_minutes` | Session cookie lifetime |

### Content Filter (`config/content_filter.json`)

- `blocked_input_patterns` — regex patterns that block user messages
- `blocked_output_patterns` — regex patterns that filter AI responses
- `system_safety_prompt` — prepended to every conversation
- `blocked_response_message` — shown when content is blocked

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌──────────┐
│   Browser    │────▶│  FastAPI Server   │────▶│  Ollama  │
│  (Kids UI)   │◀────│  (port 8080)      │◀────│ (11434)  │
└──────────────┘     │                    │     └──────────┘
                     │ - Auth (PIN)       │     │ DeepSeek │
                     │ - Content filter   │     │ Llama    │
                     │ - Rate limiting    │     │ Qwen     │
                     │ - Logging (SQLite) │     └──────────┘
                     │ - Personalities    │
                     └──────────────────┘
```

## Hardware Notes (Ryzen AI / 64GB RAM)

- Each 7-8B model uses ~5-8GB RAM when loaded
- Ollama unloads idle models automatically — only the active model is in memory
- The `deploy.resources.limits.memory: 48g` in docker-compose.yml reserves RAM for Ollama
- With 64GB total, you'll have plenty of headroom for the OS + web server + Ollama

## Parent Dashboard

Access at `http://localhost:8080/admin` with your admin password.

- View per-child message counts (today / total / blocked)
- Browse full conversation history with timestamps
- Blocked messages are highlighted in red
- See which model was used for each conversation

## Security Notes

- Change the default `SECRET_KEY` and `ADMIN_PASSWORD` in `.env`
- PINs are simple numeric codes — suitable for home use, not internet-facing
- If exposing to your home network, consider putting behind a reverse proxy with HTTPS
- The SQLite database in `data/` contains all conversation history
