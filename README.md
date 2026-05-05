# JARVIS

A self-hosted Discord bot running on Raspberry Pi 5 via Docker. Built with discord.py, wavelink, and Lavalink for audio. Uses PostgreSQL for persistence.

## Stack

- Python 3.12 + discord.py 2.7
- Wavelink 3.5 + Lavalink 4 (audio)
- PostgreSQL (shared with other services via db_aksh Docker network)
- Managed via Dockge at `/opt/stacks/discord-bot/`

## Features

### Music
- Play from YouTube, SoundCloud, Spotify URLs
- Queue, skip, pause, seek, loop (track/queue), shuffle
- Audio filters: bassboost, nightcore, 8D, vaporwave, soft, pop
- Lyrics via lyrics.ovh
- DJ role enforcement, 24/7 mode, music channel lockdown

### Community
- XP/leveling system with level-up announcements and level roles
- Economy: coins from chatting, daily reward, slots, blackjack, shop
- Starboard, counting game, media-only channel, anonymous confessions
- Polls, giveaways, birthday tracking

### Games
- Trivia (Open Trivia DB, XP rewards)
- Wordle, Hangman, Tic Tac Toe
- Would You Rather, Truth or Dare

### Moderation
- Warn/kick/ban/timeout/purge with reason logging
- AutoMod: spam detection, link blocking, banned word list
- Mod log channel for message deletes/edits
- Ticket system with private channels

### Utility
- AFK system with ping detection
- Nickname history tracking
- Spotify presence viewer
- Auto-role on join, bump reminder (Disboard)
- Message logger

### Server Setup
- `/setup` builds the full channel structure in one command
- Server stats VCs (member count, bot count, boosts) auto-update every 10 min
- Role menus with dropdowns, color role picker

### Stream
- Dedicated stream VC with auto-announcement when someone goes live
- `/stream hotstar <title>` — search Hotstar
- `/stream yt <query>` — search YouTube

## Setup

### Requirements
- Docker + Docker Compose
- PostgreSQL instance
- Lavalink 4

### Environment Variables

Create `.env` in the stack root:

```
DISCORD_TOKEN=
CLIENT_ID=
GUILD_ID=
DATABASE_URL=postgresql://user:pass@host:5432/discord_bot
ANTHROPIC_API_KEY=        # optional, enables /ask /vibe /tldr and AI channel
SPOTIFY_CLIENT_ID=        # optional, enables Spotify URL playback
SPOTIFY_CLIENT_SECRET=    # optional
```

### Deploy

```bash
cd /opt/stacks/discord-bot
docker compose up -d
```

### First Run

1. Give the bot Administrator role in your server
2. Run `/setup` in any channel to build the full channel structure
3. Run `/communitysetup` to configure starboard, counting, confessions, media channels
4. Run `/setdj` to set a DJ role for music control
5. Run `/setautorole` to auto-assign a Member role on join
6. Run `/setmodlog` to enable mod action logging

### Updating YouTube Token

YouTube periodically blocks bot requests. When songs start failing:

1. Open YouTube in Chrome, open DevTools (F12) → Network tab
2. Click any request → look for `x-goog-visitor-id` in the request headers
3. Copy the value
4. Run `/refreshyt <value>` in Discord — updates config and restarts Lavalink automatically

## Directory Structure

```
discord-bot/
├── compose.yaml
├── .env
├── bot/
│   ├── Dockerfile
│   ├── main.py
│   ├── requirements.txt
│   └── cogs/
│       ├── ai.py
│       ├── automod.py
│       ├── birthdays.py
│       ├── community.py
│       ├── economy.py
│       ├── filters.py
│       ├── fun.py
│       ├── games.py
│       ├── general.py
│       ├── giveaway.py
│       ├── levels.py
│       ├── media.py
│       ├── moderation.py
│       ├── music.py
│       ├── music_extras.py
│       ├── reminders.py
│       ├── roles.py
│       ├── setup.py
│       ├── stream.py
│       ├── tickets.py
│       ├── utility.py
│       └── ytrefresh.py
└── lavalink/
    ├── application.yml
    └── plugins/
```

## Notes

- Bot uses `network_mode: host` for voice UDP to work correctly behind NAT
- Lavalink port (2333) is bound to `127.0.0.1` only — not exposed externally
- DB uses the `discord_bot` database on the shared PostgreSQL instance
- Slash commands sync to all guilds on startup and auto-sync when the bot joins a new server
