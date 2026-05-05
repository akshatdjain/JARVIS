import datetime
import discord
from discord.ext import commands
from discord import app_commands


async def log_action(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow("SELECT mod_log_channel_id FROM guild_config WHERE guild_id = $1", guild.id)
    if not row or not row["mod_log_channel_id"]:
        return
    channel = guild.get_channel(row["mod_log_channel_id"])
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


def mod_embed(action: str, target: discord.Member, moderator: discord.Member, reason: str, color: int) -> discord.Embed:
    embed = discord.Embed(title=f"🔨 {action}", color=color, timestamp=datetime.datetime.now())
    embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=True)
    embed.add_field(name="Moderator", value=moderator.mention, inline=True)
    embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    return embed


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Warn a user")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO warnings (user_id, guild_id, moderator_id, reason) VALUES ($1, $2, $3, $4)",
                user.id, interaction.guild_id, interaction.user.id, reason
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM warnings WHERE user_id = $1 AND guild_id = $2",
                user.id, interaction.guild_id
            )
        embed = mod_embed("Warning Issued", user, interaction.user, reason, 0xF39C12)
        embed.add_field(name="Total Warnings", value=f"`{count}`", inline=True)
        await interaction.response.send_message(embed=embed)
        try:
            await user.send(f"⚠️ You were warned in **{interaction.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await log_action(self.bot, interaction.guild, embed)

    @app_commands.command(name="warnings", description="View warnings for a user")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, user: discord.Member):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT reason, created_at, moderator_id FROM warnings WHERE user_id = $1 AND guild_id = $2 ORDER BY created_at DESC LIMIT 10",
                user.id, interaction.guild_id
            )
        if not rows:
            return await interaction.response.send_message(f"✅ {user.mention} has no warnings.", ephemeral=True)
        embed = discord.Embed(title=f"⚠️ Warnings for {user.display_name}", color=0xF39C12)
        for i, row in enumerate(rows, 1):
            ts = int(row["created_at"].timestamp())
            embed.add_field(name=f"#{i}", value=f"{row['reason']}\n<t:{ts}:R> by <@{row['moderator_id']}>", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a user")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def clearwarnings(self, interaction: discord.Interaction, user: discord.Member):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM warnings WHERE user_id = $1 AND guild_id = $2",
                user.id, interaction.guild_id
            )
        await interaction.response.send_message(f"✅ Cleared all warnings for {user.mention}.")

    @app_commands.command(name="kick", description="Kick a user from the server")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        embed = mod_embed("Member Kicked", user, interaction.user, reason, 0xE67E22)
        try:
            await user.send(f"👢 You were kicked from **{interaction.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await user.kick(reason=reason)
        await interaction.followup.send(embed=embed)
        await log_action(self.bot, interaction.guild, embed)

    @app_commands.command(name="ban", description="Ban a user from the server")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided", delete_days: app_commands.Range[int, 0, 7] = 0):
        await interaction.response.defer()
        embed = mod_embed("Member Banned", user, interaction.user, reason, 0xE74C3C)
        try:
            await user.send(f"🔨 You were banned from **{interaction.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await user.ban(reason=reason, delete_message_days=delete_days)
        await interaction.followup.send(embed=embed)
        await log_action(self.bot, interaction.guild, embed)

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        await interaction.response.defer()
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
            await interaction.followup.send(f"✅ Unbanned **{user}**.")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to unban: {e}")

    @app_commands.command(name="timeout", description="Timeout a user")
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
        embed = mod_embed(f"Member Timed Out ({duration.name})", user, interaction.user, reason, 0x9B59B6)
        await interaction.response.send_message(embed=embed)
        await log_action(self.bot, interaction.guild, embed)

    @app_commands.command(name="untimeout", description="Remove a timeout from a user")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, user: discord.Member):
        await user.timeout(None)
        await interaction.response.send_message(f"✅ Removed timeout from {user.mention}.")

    @app_commands.command(name="purge", description="Bulk delete messages in this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Deleted **{len(deleted)}** messages.", ephemeral=True)

    @app_commands.command(name="lock", description="Lock a channel so only mods can send messages")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔒 {ch.mention} locked.")

    @app_commands.command(name="unlock", description="Unlock a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔓 {ch.mention} unlocked.")

    @app_commands.command(name="slowmode", description="Set slowmode in a channel (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        msg = f"✅ Slowmode set to `{seconds}s`." if seconds else "✅ Slowmode disabled."
        await interaction.response.send_message(msg)

    @app_commands.command(name="setmodlog", description="Set the mod log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setmodlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id, mod_log_channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET mod_log_channel_id = $2",
                interaction.guild_id, channel.id
            )
        await interaction.response.send_message(f"✅ Mod log set to {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
