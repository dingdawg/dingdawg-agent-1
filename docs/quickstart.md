# Quickstart Guide

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (optional, for containerized deployment)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/innovative-systems-global/isg-agent-1.git
cd isg-agent-1
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys and secrets
```

### 3. Start the gateway

```bash
cd gateway
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m isg_agent
```

### 4. Start the dashboard

```bash
cd dashboard
npm install
npm run dev
```

### 5. Verify

Open http://localhost:3000 for the dashboard.
The gateway API docs are at http://localhost:8080/docs.

## Docker Quickstart

```bash
docker-compose up --build
```

This starts all three services (gateway, bridges, dashboard) with a single command.

## Next Steps

- Read [architecture.md](architecture.md) for system design overview
- Read [security-model.md](security-model.md) for security documentation
- Read [constitution-guide.md](constitution-guide.md) to customize agent behavior
- Read [skill-development.md](skill-development.md) to create custom skills
