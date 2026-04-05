# Deployment Guide

## Docker Deployment (Recommended)

### Build and run all services

```bash
docker-compose up --build -d
```

### Individual services

```bash
docker-compose up gateway -d
docker-compose up bridges -d
docker-compose up dashboard -d
```

### Environment variables

Copy `.env.example` to `.env` and fill in all required values before running
Docker Compose.

## Manual Deployment

### Gateway

```bash
cd gateway
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m isg_agent
```

### Bridges

```bash
cd bridges
npm ci
npm run build
node dist/index.js
```

### Dashboard

```bash
cd dashboard
npm ci
npm run build
# Serve the dist/ directory with any static file server
npx serve dist -l 3000
```

## Production Considerations

- Use a process manager (systemd, supervisord, PM2) for service lifecycle.
- Place a reverse proxy (nginx, Caddy) in front of the gateway.
- Enable TLS termination at the reverse proxy level.
- Set strong, unique secrets for `ISG_GATEWAY_SECRET` and `ISG_REMOTE_SECRET`.
- Configure log rotation for all services.
- Back up the SQLite database regularly.
- Monitor the `/health` endpoint for availability checks.
