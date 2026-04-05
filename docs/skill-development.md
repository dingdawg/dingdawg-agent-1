# Skill Development Guide

## Skill Structure

Each skill is a directory under `skills/` containing:

```
skills/my-skill/
  manifest.json    # Skill metadata, parameters, capabilities
  skill.py         # Python implementation
  SKILL.md         # Human-readable documentation
```

## Manifest Format

```json
{
  "name": "my-skill",
  "version": "0.1.0",
  "description": "What this skill does.",
  "author": "Your Name",
  "license": "MIT",
  "entrypoint": "skill.py",
  "capabilities": ["network_read"],
  "parameters": {
    "param_name": {
      "type": "string",
      "required": true,
      "description": "What this parameter does."
    }
  },
  "returns": {
    "type": "object",
    "properties": {}
  }
}
```

## Capabilities

Skills declare what system resources they need:
- `network_read` -- make HTTP requests
- `filesystem_read` -- read files in the workspace
- `filesystem_write` -- write files in the workspace
- `code_execution` -- run code in a sandbox
- `database_write` -- write to the agent database

## Security

- Skills run in a sandboxed context.
- Filesystem operations are jailed to the workspace.
- Network access must be explicitly declared.
- Skills requiring confirmation are paused until the user approves.

## Testing

Place tests in `skills/my-skill/tests/` and run with pytest.
