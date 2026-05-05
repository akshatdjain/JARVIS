"""
/mod — guild-only subcommand group for moderation.
Replaces: warn, warnings, clearwarnings, kick, ban, unban,
          timeout, untimeout, purge, lock, unlock, slowmode,
          automod, bannedwords, nickhistory
"""
import datetime
import discord
from discord.ext import commands
from discord import app_commands


async def _post_mod_log(client, guild: discord.Guild, embed: discord.Embed):
    async with client.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mod_log_channel_id FROM guild_config WHERE guild_id = $1", guild.id
        )
    if not row or not row["mod_log_channel_id"]:
        return
    ch = guild.get_channel(row["mod_log_channel_id"])
    if ch:
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass


def _mod_embed(action: str, target: discord.Member, mod: discord.Member, reason: str, color: int) -> discord.Embed:
    embed = discord.Embed(title=action, color=color, timestamp=datetime.datetime.now())
    embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=True)
    embed.add_field(name="Moderator", value=mod.mention, inline=True)
    embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    return embed


class ModGroup(app_commands.Group):
    """Moderation commands."""

    # ── /mod warn ──────────────────────────────────────────────────────────────
    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO warnings (user_id, guild_id, moderator_id, reason) VALUES ($1, $2, $3, $4)",
                user.id, interaction.guild_id, interaction.user.id, reason
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM warnings WHERE user_id = $1 AND guild_id = $2",
                user.id, interaction.guild_id
            )
        embed = _mod_embed("Warning Issued", user, interaction.user, reason, 0xF39C12)
        embed.add_field(name="Total Warnings", value=f"`{count}`")
        await interaction.response.send_message(embed=embed)
        try:
            await user.send(f"You were warned in **{interaction.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await _post_mod_log(interaction.client, interaction.guild, embed)

    @app_commands.command(name="warnings", description="View warnings for a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, user: discord.Member):
        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT reason, created_at, moderator_id FROM warnings "
                "WHERE user_id = $1 AND guild_id = $2 ORDER BY created_at DESC LIMIT 10",
                user.id, interaction.guild_id
            )
        if not rows:
            return await interaction.response.send_message(f"{user.mention} has no warnings.", ephemeral=True)
        embed = discord.Embed(title=f"Warnings — {user.display_name}", color=0xF39C12)
        for i, row in enumerate(rows, 1):
            ts = int(row["created_at"].timestamp())
            embed.add_field(name=f"#{i}", value=f"{row['reason']}\n<t:{ts}:R> by <@{row['moderator_id']}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def clearwarnings(self, interaction: discord.Interaction, user: discord.Member):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM warnings WHERE user_id = $1 AND guild_id = $2", user.id, interaction.guild_id
            )
        await interaction.response.send_message(f"Cleared all warnings for {user.mention}.", ephemeral=True)

    # ── /mod kick ──────────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Kick a member")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        embed = _mod_embed("Member Kicked", user, interaction.user, reason, 0xE67E22)
        try:
            await user.send(f"You were kicked from **{interaction.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await user.kick(reason=reason)
        await interaction.followup.send(embed=embed)
        await _post_mod_log(interaction.client, interaction.guild, embed)

    # ── /mod ban ───────────────────────────────────────────────────────────────
    @app_commands.command(name="ban", description="Ban a member")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        embed = _mod_embed("Member Banned", user, interaction.user, reason, 0xE74C3C)
        try:
            await user.send(f"You were banned from **{interaction.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await user.ban(reason=reason)
        await interaction.followup.send(embed=embed)
        await _post_mod_log(interaction.client, interaction.guild, embed)

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        await interaction.response.defer()
        try:
            user = await interaction.client.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
            await interaction.followup.send(f"Unbanned **{user}**.")
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}")

    # ── /mod timeout ───────────────────────────────────────────────────────────
    @app_commands.command(name="timeout", description="Timeout a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.choices(duration=[
        app_commands.Choice(name="60 seconds", value=60),
        app_commands.Choice(name="5 minutes", value=300),
        app_commands.Choice(name="10 minutes", value=600),
        app_commands.Choice(name="1 hour", value=3600),
        app_commands.Choice(name="1 day", value=86400),
        app_commands.Choice(name="1 week", value=604800),
    ])
    async def timeout(self, interaction: discord.Interaction, user: discord.Member, duration: app_commands.Choice[int], reason: str = "No reason provided"):
        until = discord.utils.utcnow() + datetime.timedelta(seconds=duration.value)
        await user.timeout(until, reason=reason)
        embed = _mod_embed(f"Timed Out ({duration.name})", user, interaction.user, reason, 0x9B59B6)
        await interaction.response.send_message(embed=embed)
        await _post_mod_log(interaction.client, interaction.guild, embed)

    @app_commands.command(name="untimeout", description="Remove a timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, user: discord.Member):
        await user.timeout(None)
        await interaction.response.send_message(f"Removed timeout from {user.mention}.")

    # ── /mod purge ─────────────────────────────────────────────────────────────
    @app_commands.command(name="purge", description="Bulk delete messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Deleted **{len(deleted)}** messages.", ephemeral=True)

    # ── /mod lock / unlock / slowmode ──────────────────────────────────────────
    @app_commands.command(name="lock", description="Lock a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        ow = ch.overwrites_for(interaction.guild.default_role)
        ow.send_messages = False
        await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message(f"Locked {ch.mention}.")

    @app_commands.command(name="unlock", description="Unlock a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        ow = ch.overwrites_for(interaction.guild.default_role)
        ow.send_messages = None
        await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message(f"Unlocked {ch.mention}.")

    @app_commands.command(name="slowmode", description="Set slowmode (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(
            f"Slowmode set to `{seconds}s`." if seconds else "Slowmode disabled."
        )

    # ── /mod automod ───────────────────────────────────────────────────────────
    @app_commands.command(name="automod", description="Configure AutoMod settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(setting=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="Block links: ON", value="links_on"),
        app_commands.Choice(name="Block links: OFF", value="links_off"),
    ])
    async def automod(self, interaction: discord.Interaction, setting: app_commands.Choice[str]):
        async with interaction.client.db.acquire() as conn:
            if setting.value == "enable":
                await conn.execute(
                    "INSERT INTO guild_config (guild_id, automod_enabled) VALUES ($1, TRUE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET automod_enabled = TRUE", interaction.guild_id
                )
                msg = "AutoMod enabled."
            elif setting.value == "disable":
                await conn.execute(
                    "INSERT INTO guild_config (guild_id, automod_enabled) VALUES ($1, FALSE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET automod_enabled = FALSE", interaction.guild_id
                )
                msg = "AutoMod disabled."
            elif setting.value == "links_on":
                await conn.execute(
                    "INSERT INTO automod_config (guild_id, block_links) VALUES ($1, TRUE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET block_links = TRUE", interaction.guild_id
                )
                msg = "Link blocking enabled."
            else:
                await conn.execute(
                    "INSERT INTO automod_config (guild_id, block_links) VALUES ($1, FALSE) "
                    "ON CONFLICT (guild_id) DO UPDATE SET block_links = FALSE", interaction.guild_id
                )
                msg = "Link blocking disabled."

        # Bust automod cache
        automod_cog = interaction.client.cogs.get("AutoMod")
        if automod_cog:
            automod_cog._config_cache.pop(interaction.guild_id, None)
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="bannedwords", description="Manage the banned word list")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def bannedwords(self, interaction: discord.Interaction, action: app_commands.Choice[str], word: str = None):
        async with interaction.client.db.acquire() as conn:
            if action.value == "list":
                row = await conn.fetchrow("SELECT banned_words FROM automod_config WHERE guild_id = $1", interaction.guild_id)
                words = list(row["banned_words"]) if row and row["banned_words"] else []
                return await interaction.response.send_message(
                    f"Banned words: {', '.join(f'`{w}`' for w in words) or 'none'}", ephemeral=True
                )
            if not word:
                return await interaction.response.send_message("Provide a word.", ephemeral=True)
            if action.value == "add":
                await conn.execute(
                    "INSERT INTO automod_config (guild_id, banned_words) VALUES ($1, ARRAY[$2]) "
                    "ON CONFLICT (guild_id) DO UPDATE SET banned_words = array_append(automod_config.banned_words, $2)",
                    interaction.guild_id, word.lower()
                )
                msg = f"Added `{word}` to banned words."
            else:
                await conn.execute(
                    "UPDATE automod_config SET banned_words = array_remove(banned_words, $2) WHERE guild_id = $1",
                    interaction.guild_id, word.lower()
                )
                msg = f"Removed `{word}` from banned words."
        automod_cog = interaction.client.cogs.get("AutoMod")
        if automod_cog:
            automod_cog._config_cache.pop(interaction.guild_id, None)
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="nickhistory", description="View nickname history for a member")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def nickhistory(self, interaction: discord.Interaction, user: discord.Member):
        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT old_nick, new_nick, changed_at FROM nickname_history "
                "WHERE user_id = $1 AND guild_id = $2 ORDER BY changed_at DESC LIMIT 10",
                user.id, interaction.guild_id
            )
        if not rows:
            return await interaction.response.send_message(f"No nickname history for {user.mention}.", ephemeral=True)
        embed = discord.Embed(title=f"Nickname History — {user.display_name}", color=0x2B2D31)
        for row in rows:
            ts = int(row["changed_at"].timestamp())
            embed.add_field(
                name=f"`{row['old_nick'] or 'None'}` → `{row['new_nick'] or 'None'}`",
                value=f"<t:{ts}:R>", inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Mod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mod_group = ModGroup(name="mod", description="Moderation commands")
        bot.tree.add_command(self.mod_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("mod")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mod(bot))
