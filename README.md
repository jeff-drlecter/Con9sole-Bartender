# Con9sole-Bartender

A Python Discord bot for the Con9sole community.

## Overview

Con9sole-Bartender is a Discord bot project used to support community features and server automation for the Con9sole Discord server.

Current repository structure suggests the bot is built with `discord.py`, uses cog-based command modules, and is deployed with Fly.io.

## Repository structure

```text
.
├── bot.py                 # Main bot entry point and cog loader
├── config.py              # Runtime configuration
├── cogs/                  # Discord cog modules
├── core/                  # Shared core logic and persistence helpers
├── data/                  # Runtime or configuration data
├── features/              # Feature-specific views and UI logic
├── assets/                # Static assets
├── fly.toml               # Fly.io deployment config
├── Dockerfile             # Container build file
├── Procfile               # Process definition
└── requirements.txt       # Python dependencies
```

## Development notes

- Do not commit secrets, bot tokens, or production environment variables.
- Prefer feature branches and pull requests instead of pushing directly to `main`.
- Test slash command changes in the guild-scoped environment before wider rollout.
- Keep runtime database files and generated state files out of git.

## Deployment

This project appears to be configured for Fly.io deployment.

Before deployment, confirm:

1. Required environment variables are set in Fly.io secrets.
2. Discord bot token is not stored in the repository.
3. The bot has the required Discord intents enabled.
4. Slash commands are synced to the intended guild.

## Suggested future improvements

- Document available slash commands.
- Add setup instructions for local development.
- Add `.env.example` for required environment variables.
- Add basic health check or startup diagnostics.
- Add a changelog for production deployments.
