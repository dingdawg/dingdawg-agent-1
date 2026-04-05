# Constitution Guide

## What Is the Agent Constitution?

The constitution is a YAML file that defines the behavioral rules your agent
must follow. It is evaluated before every action the agent takes, providing
a governance layer between the user's request and the agent's execution.

## Structure

### Absolute Rules (Tier 1)
These rules are **never** violated, regardless of user instructions.
Enforcement mode: `hard_block` -- the action is blocked and the user is
informed why.

### Behavioral Guidelines (Tier 2)
These rules are enforced but have an escalation path.
Enforcement modes:
- `confirm_required` -- user must explicitly approve
- `advisory` -- warning is logged but action proceeds

### Preferences (Tier 3)
Soft guidance that shapes the agent's communication style.
Users can override these by providing alternative instructions.

## Creating Your Own Constitution

1. Copy `config/constitution.example.yaml` to `config/constitution.yaml`.
2. Modify the rules to match your requirements.
3. Restart the gateway to load the new constitution.

## Best Practices

- Keep absolute rules minimal and unambiguous.
- Use behavioral guidelines for context-dependent restrictions.
- Test your constitution with edge cases before deploying.
- Version your constitution file alongside your agent configuration.
