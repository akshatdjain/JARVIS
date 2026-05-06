import asyncio
import logging
import os
import asyncpg
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("discord.voice_client").setLevel(logging.DEBUG)
logging.getLogger("discord.gateway").setLevel(logging.DEBUG)
log = logging.getLogger("jarvis")

# User-facing cogs — commands go global
COGS = [
    "cogs.help",
    "cogs.music",
    "cogs.filters",
    "cogs.levels",
    "cogs.fun",
    "cogs.reminders",
    "cogs.ai",
    "cogs.tickets",
    "cogs.giveaway",
    "cogs.birthdays",
    "cogs.general",
    "cogs.stream",
    "cogs.games",
    "cogs.economy",
    "cogs.utility",
    "cogs.community",
    "cogs.roles",
]

# Admin/config cogs — commands go guild-only (instant, no global limit usage)
GUILD_COGS = [
    "cogs.setup",
    "cogs.settings",
    "cogs.admin",
    "cogs.mod",
    "cogs.music_extras",
    "cogs.automod",
    "cogs.ytrefresh",
]

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id BIGINT PRIMARY KEY,
    ai_channel_id BIGINT,
    mod_log_channel_id BIGINT,
    dj_role_id BIGINT,
    automod_enabled BOOLEAN DEFAULT TRUE,
    welcome_channel_id BIGINT,
    birthday_channel_id BIGINT
);

CREATE TABLE IF NOT EXISTS levels (
    user_id BIGINT,
    guild_id BIGINT,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS warnings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    moderator_id BIGINT,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    channel_id BIGINT,
    message TEXT,
    remind_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS giveaways (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    prize TEXT,
    ends_at TIMESTAMPTZ,
    winner_count INTEGER DEFAULT 1,
    ended BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS birthdays (
    user_id BIGINT,
    guild_id BIGINT,
    birth_month INTEGER,
    birth_day INTEGER,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    channel_id BIGINT,
    user_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS automod_config (
    guild_id BIGINT PRIMARY KEY,
    spam_threshold INTEGER DEFAULT 5,
    block_links BOOLEAN DEFAULT FALSE,
    banned_words TEXT[] DEFAULT ARRAY[]::TEXT[]
);
"""


class Jarvis(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=">", intents=intents)
        self.db: asyncpg.Pool = None
        self._last_event_seq: int = 0

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(dsn=os.getenv("DATABASE_URL"), min_size=2, max_size=10)
        async with self.db.acquire() as conn:
            await conn.execute(DB_SCHEMA)
        log.info("Database connected and schema ready")

        for cog in COGS + GUILD_COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as e:
                log.error("Failed to load cog %s: %s", cog, e, exc_info=True)

        # Run syncs in background so bot comes online immediately
        self.loop.create_task(self._sync_commands())
        self.loop.create_task(self._gateway_watchdog())

    async def _sync_commands(self):
        await self.wait_until_ready()

        guild_id = os.getenv("GUILD_ID")
        if not guild_id:
            return

        guild = discord.Object(id=int(guild_id))
        self.tree.copy_global_to(guild=guild)

        try:
            await self.tree.sync(guild=guild)
            log.info("Commands synced to guild %s", guild_id)
        except discord.Forbidden:
            log.error("Guild sync forbidden — bot needs re-invite with applications.commands scope: "
                      "https://discord.com/oauth2/authorize?client_id=%s&permissions=8&scope=bot%%20applications.commands",
                      self.application_id)
        except discord.HTTPException as e:
            if e.status == 429:
                # Already rate-limited — discord.py will auto-retry, just log and wait
                log.warning("Guild sync rate limited — discord.py will retry automatically. Commands will appear shortly.")
            else:
                log.error("Guild sync failed: %s", e)
        except Exception as e:
            log.error("Guild sync failed: %s", e)

    async def on_socket_response(self, msg):
        # Track last sequence number to detect truly stale sessions
        if isinstance(msg, dict) and msg.get('s'):
            self._last_event_seq = msg['s']

    async def _gateway_watchdog(self):
        """Reconnect only if sequence number hasn't advanced in 20+ minutes.
        Heartbeat-only sessions keep sequence the same but are NOT stale —
        only reconnect if we're stuck AND not receiving any dispatched events."""
        await self.wait_until_ready()
        import time
        last_checked_seq = self._last_event_seq
        last_advance_time = time.time()
        while not self.is_closed():
            await asyncio.sleep(600)  # check every 10 minutes
            current_seq = self._last_event_seq
            if current_seq == last_checked_seq:
                # Sequence hasn't moved at all in 10 minutes
                if (time.time() - last_advance_time) > 1200:  # 20 minutes total stuck
                    log.warning("Gateway sequence stuck at %s for 20+ minutes, reconnecting...", current_seq)
                    try:
                        await self.close()
                    except Exception:
                        pass
                    return
            else:
                last_checked_seq = current_seq
                last_advance_time = time.time()

    async def on_guild_join(self, guild: discord.Guild):
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Auto-synced to new guild: %s (%s)", guild.name, guild.id)
        except Exception as e:
            log.warning("Failed to sync new guild %s: %s", guild.id, e)

    async def on_ready(self):
        log.info("JARVIS online as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/play | JARVIS",
            )
        )

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set")

    async with Jarvis() as bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
