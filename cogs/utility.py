import datetime
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands

SCHEMA = """
CREATE TABLE IF NOT EXISTS afk_users (
    user_id BIGINT,
    guild_id BIGINT,
    reason TEXT,
    since TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, guild_id)
);
CREATE TABLE IF NOT EXISTS nickname_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    old_nick TEXT,
    new_nick TEXT,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS utility_config (
    guild_id BIGINT PRIMARY KEY,
    mod_log_channel_id BIGINT,
    auto_role_id BIGINT,
    bump_channel_id BIGINT,
    welcome_channel_id BIGINT
);
"""

BUMP_BOT_ID = 302050872383242240  # Disboard bot ID


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._init_db())
        self.bump_reminder.start()

    def cog_unload(self):
        self.bump_reminder.cancel()

    async def _init_db(self):
        await self.bot.wait_until_ready()
        async with self.bot.db.acquire() as conn:
            await conn.execute(SCHEMA)

    async def _get_config(self, guild_id: int):
        async with self.bot.db.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM utility_config WHERE guild_id = $1", guild_id)

    # ── AFK ───────────────────────────────────────────────────────────────────
    @app_commands.command(name="afk", description="Set your AFK status")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK"):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO afk_users (user_id, guild_id, reason) VALUES ($1, $2, $3) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET reason = $3, since = NOW()",
                interaction.user.id, interaction.guild_id, reason
            )
        await interaction.response.send_message(f"😴 You're now AFK: **{reason}**")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Remove AFK if the user sends a message
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT reason, since FROM afk_users WHERE user_id = $1 AND guild_id = $2",
                message.author.id, message.guild.id
            )
            if row:
                await conn.execute(
                    "DELETE FROM afk_users WHERE user_id = $1 AND guild_id = $2",
                    message.author.id, message.guild.id
                )
                await message.channel.send(
                    f"👋 Welcome back, {message.author.mention}! AFK removed.", delete_after=5
                )

            # Notify if someone pings an AFK user
            for mention in message.mentions:
                if mention.bot or mention.id == message.author.id:
                    continue
                afk = await conn.fetchrow(
                    "SELECT reason, since FROM afk_users WHERE user_id = $1 AND guild_id = $2",
                    mention.id, message.guild.id
                )
                if afk:
                    since = afk["since"]
                    diff = datetime.datetime.now(datetime.timezone.utc) - since
                    mins = int(diff.total_seconds() // 60)
                    time_str = f"{mins} min ago" if mins < 60 else f"{mins // 60}h ago"
                    await message.channel.send(
                        f"😴 **{mention.display_name}** is AFK: *{afk['reason']}* ({time_str})",
                        delete_after=10
                    )

        # Bump reminder detection
        if message.author.id == BUMP_BOT_ID and message.embeds:
            embed = message.embeds[0]
            if embed.description and "bump done" in embed.description.lower():
                async with self.bot.db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT bump_channel_id FROM utility_config WHERE guild_id = $1",
                        message.guild.id
                    )
                if row and row["bump_channel_id"]:
                    ch = message.guild.get_channel(row["bump_channel_id"])
                    if ch:
                        await asyncio.sleep(7200)  # 2 hours
                        await ch.send(
                            "@here ⏰ Time to bump the server! Use `/bump` to help us grow!",
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )

        # Message logging (edit/delete handled separately)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        config = await self._get_config(message.guild.id)
        if not config or not config["mod_log_channel_id"]:
            return
        ch = message.guild.get_channel(config["mod_log_channel_id"])
        if not ch:
            return
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            color=0xE74C3C,
            timestamp=datetime.datetime.now(),
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Content", value=message.content[:1000] or "*[no text]*", inline=False)
        if message.attachments:
            embed.add_field(name="Attachments", value="\n".join(a.filename for a in message.attachments), inline=False)
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        config = await self._get_config(before.guild.id)
        if not config or not config["mod_log_channel_id"]:
            return
        ch = before.guild.get_channel(config["mod_log_channel_id"])
        if not ch:
            return
        embed = discord.Embed(
            title="✏️ Message Edited",
            color=0xF39C12,
            timestamp=datetime.datetime.now(),
        )
        embed.add_field(name="Author", value=before.author.mention, inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Before", value=before.content[:500] or "*empty*", inline=False)
        embed.add_field(name="After", value=after.content[:500] or "*empty*", inline=False)
        embed.add_field(name="Jump", value=f"[Go to message]({after.jump_url})", inline=False)
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    # ── AUTO ROLE ON JOIN ─────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self._get_config(member.guild.id)
        if not config or not config["auto_role_id"]:
            return
        role = member.guild.get_role(config["auto_role_id"])
        if role:
            try:
                await member.add_roles(role, reason="Auto-role on join")
            except discord.HTTPException:
                pass

    # ── NICKNAME HISTORY ──────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick == after.nick:
            return
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO nickname_history (user_id, guild_id, old_nick, new_nick) VALUES ($1, $2, $3, $4)",
                after.id, after.guild.id, before.nick, after.nick
            )

    @app_commands.command(name="nickhistory", description="View nickname history for a user")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def nickhistory(self, interaction: discord.Interaction, user: discord.Member):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT old_nick, new_nick, changed_at FROM nickname_history "
                "WHERE user_id = $1 AND guild_id = $2 ORDER BY changed_at DESC LIMIT 10",
                user.id, interaction.guild_id
            )
        if not rows:
            return await interaction.response.send_message(f"No nickname history for {user.mention}.", ephemeral=True)
        embed = discord.Embed(title=f"📝 Nickname History — {user.display_name}", color=0x2B2D31)
        for row in rows:
            ts = int(row["changed_at"].timestamp())
            embed.add_field(
                name=f"`{row['old_nick'] or 'None'}` → `{row['new_nick'] or 'None'}`",
                value=f"<t:{ts}:R>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # ── SPOTIFY PRESENCE ──────────────────────────────────────────────────────
    @app_commands.command(name="spotify", description="See what someone is listening to on Spotify")
    async def spotify(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        spotify_activity = next(
            (a for a in target.activities if isinstance(a, discord.Spotify)), None
        )
        if not spotify_activity:
            return await interaction.response.send_message(
                f"❌ {target.display_name} isn't listening to Spotify right now.", ephemeral=True
            )
        embed = discord.Embed(
            title="🎵 Spotify",
            description=f"**{spotify_activity.title}**",
            color=0x1DB954,
        )
        embed.add_field(name="Artist", value=spotify_activity.artist, inline=True)
        embed.add_field(name="Album", value=spotify_activity.album, inline=True)
        if spotify_activity.album_cover_url:
            embed.set_thumbnail(url=spotify_activity.album_cover_url)
        embed.set_footer(
            text=f"{target.display_name} is listening",
            icon_url=target.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed)

    # ── BUMP REMINDER LOOP ────────────────────────────────────────────────────
    @tasks.loop(hours=2)
    async def bump_reminder(self):
        pass  # Handled reactively via on_message Disboard detection

    @bump_reminder.before_loop
    async def before_bump(self):
        await self.bot.wait_until_ready()

    # ── SETUP COMMANDS ────────────────────────────────────────────────────────
    @app_commands.command(name="setautorole", description="Set role to auto-assign when someone joins")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setautorole(self, interaction: discord.Interaction, role: discord.Role):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO utility_config (guild_id, auto_role_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET auto_role_id = $2",
                interaction.guild_id, role.id
            )
        await interaction.response.send_message(
            f"✅ Auto-role set to {role.mention}. New members will get this automatically.", ephemeral=True
        )

    @app_commands.command(name="setbumpchannel", description="Set channel for bump reminders")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setbumpchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO utility_config (guild_id, bump_channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET bump_channel_id = $2",
                interaction.guild_id, channel.id
            )
        await interaction.response.send_message(f"✅ Bump reminders will go to {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
