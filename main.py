import asyncio
import hashlib
import json
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

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

SYNC_HASH_KEY = "command_sync_hash"


def _command_hash(tree: discord.app_commands.CommandTree, guild: discord.Object) -> str:
    """Stable hash of the current command tree for a guild. Used to skip unnecessary syncs."""
    cmds = tree.get_commands(guild=guild)
    # Use command names + descriptions as a lightweight stable fingerprint
    payload = sorted(
        [{"name": cmd.name, "description": cmd.description} for cmd in cmds],
        key=lambda c: c["name"]
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class Jarvis(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=">", intents=intents)
        self.db: asyncpg.Pool = None

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

        self.loop.create_task(self._sync_commands())

    async def _sync_commands(self):
        await self.wait_until_ready()

        guild_id = os.getenv("GUILD_ID")
        if not guild_id:
            return

        guild = discord.Object(id=int(guild_id))
        self.tree.copy_global_to(guild=guild)

        # Compute hash of current command tree
        current_hash = _command_hash(self.tree, guild)

        # Check stored hash — skip sync if commands haven't changed
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM bot_state WHERE key = $1", SYNC_HASH_KEY
                )
                stored_hash = row["value"] if row else None
        except Exception:
            stored_hash = None

        if stored_hash == current_hash:
            log.info("Commands unchanged (hash=%s) — skipping sync", current_hash)
            return

        # Also check last sync time — never sync more than once per 10 minutes
        # This prevents any edge case where restarts happen in quick succession
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM bot_state WHERE key = 'last_sync_time'"
                )
                if row:
                    import time
                    last_sync = float(row["value"])
                    elapsed = time.time() - last_sync
                    if elapsed < 600:
                        log.info("Skipping sync — last sync was %.0fs ago (min 600s)", elapsed)
                        return
        except Exception:
            pass

        log.info("Commands changed (old=%s new=%s) — syncing...", stored_hash, current_hash)

        try:
            await self.tree.sync(guild=guild)
            log.info("Commands synced to guild %s", guild_id)
            # Store new hash and sync time only after successful sync
            import time
            async with self.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO bot_state (key, value) VALUES ($1, $2) "
                    "ON CONFLICT (key) DO UPDATE SET value = $2",
                    SYNC_HASH_KEY, current_hash
                )
                await conn.execute(
                    "INSERT INTO bot_state (key, value) VALUES ('last_sync_time', $1) "
                    "ON CONFLICT (key) DO UPDATE SET value = $1",
                    str(time.time())
                )
        except discord.Forbidden:
            log.error(
                "Guild sync forbidden — re-invite bot: "
                "https://discord.com/oauth2/authorize?client_id=%s&permissions=8&scope=bot%%20applications.commands",
                self.application_id
            )
        except discord.HTTPException as e:
            if e.status == 429:
                # Rate limited — do NOT retry here. The hash is not saved, so
                # the next restart will try again. No retry loop, no hammering.
                log.warning(
                    "Guild sync rate limited (429). Will retry on next restart. "
                    "Discord.py retry_after: %s", getattr(e, 'retry_after', 'unknown')
                )
            else:
                log.error("Guild sync failed (%s): %s", e.status, e.text)
        except Exception as e:
            log.error("Guild sync failed: %s", e)

    async def on_guild_join(self, guild: discord.Guild):
        """Sync commands to any new server the bot joins."""
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to new guild: %s (%s)", guild.name, guild.id)
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
