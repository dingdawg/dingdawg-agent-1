# @dingdawg/cli

**DingDawg Agent CLI** — Talk to your AI agents from the terminal.

*Yeah! We've Got An Agent For That!*

---

## Installation

```bash
# Global install (recommended)
npm install -g @dingdawg/cli

# Or run instantly without installing
npx @dingdawg/cli login
```

Requires **Node.js 18+**. Zero runtime dependencies.

---

## Quick Start

```bash
# Authenticate
dd login                   # Opens browser (OAuth device flow)
dd login --api-key sk_xxx  # Direct API key

# Talk to your agent
dd @mybusiness "schedule an appointment for John at 3pm tomorrow"

# Use a specific skill
dd @mybusiness --skill appointments list

# Check your agents
dd agents list
```

---

## Authentication

### OAuth Device Flow (recommended)

```bash
dd login
```

1. The CLI generates a short code and prints a URL
2. Open the URL in your browser and confirm
3. The CLI polls until you confirm — token is saved to `~/.dingdawg/config.json`

### API Key

```bash
dd login --api-key sk_live_abc123xyz
```

Saves the key directly. Get your API key from your DingDawg dashboard.

---

## Commands

### Agent Interaction

```bash
# Send a message — response streams in real-time
dd @mybusiness "what are my appointments today?"
dd @mygamecoach "what's my win rate this week?"

# Invoke a specific skill
dd @mybusiness --skill appointments list
dd @mybusiness --skill appointments --action create "meeting with Alex"
```

### Authentication

```bash
dd login                          # OAuth device flow
dd login --api-key sk_live_xxx    # Direct API key
dd logout                         # Clear credentials
dd whoami                         # Show current user + default agent
```

### Configuration

```bash
dd config set default-agent @mybusiness  # Set default agent
dd config get default-agent
dd config list                           # Show all config values
```

### Agent Management

```bash
dd agents list                    # List all your agents
dd agents info @mybusiness        # Show agent details
dd agents skills @mybusiness      # List available skills
```

### Status

```bash
dd status @mybusiness             # Agent health + skill count
```

---

## Terminal Output

The CLI renders markdown in the terminal:

```
$ dd @mybusiness "schedule appointment for John at 3pm tomorrow"
  Thinking...
  I've scheduled an appointment for John tomorrow at 3:00 PM.

  Appointment Details:
  ─────────────────────────────────────────
  Contact      John
  Time         March 3, 2026 at 3:00 PM
  Status       scheduled
  ID           a1b2c3d4
  ─────────────────────────────────────────
```

- Spinner while waiting for first token
- Tokens stream in real-time (replace spinner with text)
- Markdown: **bold**, `code`, lists rendered in terminal
- Structured blocks with box-drawing characters
- Colors: green = success, red = error, yellow = warning, cyan = info

---

## Configuration File

Stored at `~/.dingdawg/config.json` (mode 0600):

```json
{
  "api_key": "sk_live_xxx",
  "base_url": "https://api.dingdawg.com",
  "default_agent": "@mybusiness",
  "theme": "dark",
  "user_id": "...",
  "email": "you@example.com"
}
```

---

## Backend

Connects to the DingDawg Agent 1 backend (Railway deployment):

- Default: `https://api.dingdawg.com`
- Override: `dd config set base_url https://your-backend.railway.app`

---

## License

MIT — Innovative Systems Global LLC
