# API Reference

## Base URL

```
http://localhost:8080
```

## Endpoints

### System

| Method | Path      | Description              |
|--------|-----------|--------------------------|
| GET    | `/health` | Gateway health check     |
| GET    | `/docs`   | Interactive API docs     |
| GET    | `/redoc`  | Alternative API docs     |

### Chat (planned)

| Method | Path               | Description                         |
|--------|--------------------|-------------------------------------|
| POST   | `/api/v1/chat`     | Send a message to the agent         |
| GET    | `/api/v1/sessions` | List active conversation sessions   |
| GET    | `/api/v1/sessions/{id}` | Get session history            |
| DELETE | `/api/v1/sessions/{id}` | End a conversation session     |

### Skills (planned)

| Method | Path                | Description                       |
|--------|---------------------|-----------------------------------|
| GET    | `/api/v1/skills`    | List available skills             |
| GET    | `/api/v1/skills/{name}` | Get skill details             |

### WebSocket

| Path       | Description                                    |
|------------|------------------------------------------------|
| `/ws`      | Bridge WebSocket endpoint for real-time comms   |

## Authentication

Include the gateway secret in the WebSocket handshake headers:

```
Authorization: Bearer <ISG_GATEWAY_SECRET>
```

API endpoints requiring authentication use the remote secret:

```
X-ISG-Remote-Secret: <ISG_REMOTE_SECRET>
```

## Response Format

All JSON responses follow the structure:

```json
{
  "status": "ok",
  "data": {}
}
```

Error responses:

```json
{
  "status": "error",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable error description"
  }
}
```
