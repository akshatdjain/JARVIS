import re
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._spam_tracker: dict[tuple, list] = {}  # (user_id, channel_id) -> [timestamps]
        self._config_cache: dict[int, dict] = {}

    async def _get_config(self, guild_id: int) -> dict:
        if guild_id not in self._config_cache:
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT spam_threshold, block_links, banned_words FROM automod_config WHERE guild_id = $1",
                    guild_id
                )
                cfg_row = await conn.fetchrow(
                    "SELECT automod_enabled FROM guild_config WHERE guild_id = $1", guild_id
                )
            self._config_cache[guild_id] = {
                "enabled": cfg_row["automod_enabled"] if cfg_row else True,
                "spam_threshold": row["spam_threshold"] if row else 5,
                "block_links": row["block_links"] if row else False,
                "banned_words": list(row["banned_words"]) if row and row["banned_words"] else [],
            }
        return self._config_cache[guild_id]

    def _bust_cache(self, guild_id: int):
        self._config_cache.pop(guild_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return

        config = await self._get_config(message.guild.id)
        if not config["enabled"]:
            return

        # Spam detection
        import time
        key = (message.author.id, message.channel.id)
        now = time.time()
        timestamps = self._spam_tracker.get(key, [])
        timestamps = [t for t in timestamps if now - t < 5]
        timestamps.append(now)
        self._spam_tracker[key] = timestamps

        if len(timestamps) >= config["spam_threshold"]:
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention}, slow down! (spam detected)", delete_after=5
                )
                await message.author.timeout(
                    discord.utils.utcnow() + __import__("datetime").timedelta(seconds=60),
                    reason="AutoMod: spam"
                )
            except discord.HTTPException:
                pass
            self._spam_tracker[key] = []
            return

        # Link blocking
        if config["block_links"] and URL_PATTERN.search(message.content):
            try:
                await message.delete()
                await message.channel.send(
                    f"🔗 {message.author.mention}, links are not allowed here.", delete_after=5
                )
            except discord.HTTPException:
                pass
            return

        # Banned words
        if config["banned_words"]:
            content_lower = message.content.lower()
            for word in config["banned_words"]:
                if word.lower() in content_lower:
                    try:
                        await message.delete()
                        await message.channel.send(
                            f"🚫 {message.author.mention}, that word is not allowed.", delete_after=5
                        )
                    except discord.HTTPException:
                        pass
                    return

    @app_commands.command(name="automod", description="Configure AutoMod settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(setting=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="Block links: ON", value="links_on"),
        app_commands.Choice(name="Block links: OFF", value="links_off"),
    ])
    async def automod(self, interaction: discord.Interaction, setting: app_commands.Choice[str]):
        async with self.bot.db.acquire() as conn:
            if setting.value == "enable":
                await conn.execute(
                    "INSERT INTO guild_config (guild_id, automod_enabled) VALUES ($1, TRUE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET automod_enabled = TRUE",
                    interaction.guild_id
                )
                msg = "✅ AutoMod **enabled**."
            elif setting.value == "disable":
                await conn.execute(
                    "INSERT INTO guild_config (guild_id, automod_enabled) VALUES ($1, FALSE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET automod_enabled = FALSE",
                    interaction.guild_id
                )
                msg = "✅ AutoMod **disabled**."
            elif setting.value == "links_on":
                await conn.execute(
                    "INSERT INTO automod_config (guild_id, block_links) VALUES ($1, TRUE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET block_links = TRUE",
                    interaction.guild_id
                )
                msg = "✅ Link blocking **enabled**."
            else:
                await conn.execute(
                    "INSERT INTO automod_config (guild_id, block_links) VALUES ($1, FALSE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET block_links = FALSE",
                    interaction.guild_id
                )
                msg = "✅ Link blocking **disabled**."

        self._bust_cache(interaction.guild_id)
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="bannedwords", description="Add or remove a banned word")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def bannedwords(self, interaction: discord.Interaction, action: app_commands.Choice[str], word: str = None):
        async with self.bot.db.acquire() as conn:
            if action.value == "list":
                row = await conn.fetchrow("SELECT banned_words FROM automod_config WHERE guild_id = $1", interaction.guild_id)
                words = list(row["banned_words"]) if row and row["banned_words"] else []
                if not words:
                    return await interaction.response.send_message("No banned words set.", ephemeral=True)
                return await interaction.response.send_message(
                    f"Banned words: {', '.join(f'`{w}`' for w in words)}", ephemeral=True
                )

            if not word:
                return await interaction.response.send_message("❌ Provide a word.", ephemeral=True)

            if action.value == "add":
                await conn.execute(
                    "INSERT INTO automod_config (guild_id, banned_words) VALUES ($1, ARRAY[$2]) "
                    "ON CONFLICT (guild_id) DO UPDATE SET banned_words = array_append(automod_config.banned_words, $2)",
                    interaction.guild_id, word.lower()
                )
                msg = f"✅ Added `{word}` to banned words."
            else:
                await conn.execute(
                    "UPDATE automod_config SET banned_words = array_remove(banned_words, $2) WHERE guild_id = $1",
                    interaction.guild_id, word.lower()
                )
                msg = f"✅ Removed `{word}` from banned words."

        self._bust_cache(interaction.guild_id)
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
