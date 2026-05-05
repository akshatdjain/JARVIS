"""
/config — guild-only subcommand group for all server configuration.
Replaces: setdj, setmusicchannel, 247, setautorole, setmodlog,
          setbumpchannel, setwelcome, aichannel, communitysetup, streamsetup
"""
import discord
from discord.ext import commands
from discord import app_commands


class ConfigGroup(app_commands.Group):
    """Configure JARVIS settings for this server."""

    # ── /config music ──────────────────────────────────────────────────────────
    @app_commands.command(name="music", description="Configure music settings")
    @app_commands.describe(
        dj_role="Role that can control music (skip/stop/filters)",
        channel="Channel where music commands are allowed",
        mode_247="Keep bot in VC permanently",
    )
    async def music(
        self,
        interaction: discord.Interaction,
        dj_role: discord.Role = None,
        channel: discord.TextChannel = None,
        mode_247: bool = None,
    ):
        async with interaction.client.db.acquire() as conn:
            updates = {}
            if dj_role is not None:
                updates["dj_role_id"] = dj_role.id
            if channel is not None:
                updates["music_channel_id"] = channel.id
            if mode_247 is not None:
                updates["mode_247"] = mode_247

            if not updates:
                # Show current config
                row = await conn.fetchrow(
                    "SELECT dj_role_id, music_channel_id, mode_247 FROM music_config WHERE guild_id = $1",
                    interaction.guild_id
                )
                if not row:
                    return await interaction.response.send_message("No music config set yet.", ephemeral=True)
                dj = interaction.guild.get_role(row["dj_role_id"]) if row["dj_role_id"] else None
                ch = interaction.guild.get_channel(row["music_channel_id"]) if row["music_channel_id"] else None
                embed = discord.Embed(title="Music Config", color=0x2B2D31)
                embed.add_field(name="DJ Role", value=dj.mention if dj else "None", inline=True)
                embed.add_field(name="Music Channel", value=ch.mention if ch else "None", inline=True)
                embed.add_field(name="24/7 Mode", value="On" if row["mode_247"] else "Off", inline=True)
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            # Build upsert
            set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
            vals = [interaction.guild_id] + list(updates.values())
            keys = ", ".join(updates.keys())
            placeholders = ", ".join(f"${i+2}" for i in range(len(updates)))
            await conn.execute(
                f"INSERT INTO music_config (guild_id, {keys}) VALUES ($1, {placeholders}) "
                f"ON CONFLICT (guild_id) DO UPDATE SET {set_clause}",
                *vals
            )

        lines = []
        if dj_role:    lines.append(f"DJ role: {dj_role.mention}")
        if channel:    lines.append(f"Music channel: {channel.mention}")
        if mode_247 is not None: lines.append(f"24/7 mode: {'on' if mode_247 else 'off'}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── /config server ─────────────────────────────────────────────────────────
    @app_commands.command(name="server", description="Configure server-wide settings")
    @app_commands.describe(
        auto_role="Role to auto-assign when someone joins",
        mod_log="Channel for mod action logs (edits, deletes, bans)",
        bump_channel="Channel for Disboard bump reminders",
        welcome_channel="Channel for welcome messages",
        ai_channel="Channel where JARVIS auto-replies to every message",
    )
    async def server(
        self,
        interaction: discord.Interaction,
        auto_role: discord.Role = None,
        mod_log: discord.TextChannel = None,
        bump_channel: discord.TextChannel = None,
        welcome_channel: discord.TextChannel = None,
        ai_channel: discord.TextChannel = None,
    ):
        if not any([auto_role, mod_log, bump_channel, welcome_channel, ai_channel]):
            return await interaction.response.send_message(
                "Provide at least one setting to update.", ephemeral=True
            )

        async with interaction.client.db.acquire() as conn:
            updates = {}
            if auto_role:       updates["auto_role_id"] = auto_role.id
            if mod_log:         updates["mod_log_channel_id"] = mod_log.id
            if welcome_channel: updates["welcome_channel_id"] = welcome_channel.id
            if ai_channel:      updates["ai_channel_id"] = ai_channel.id

            if updates:
                set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
                keys = ", ".join(updates.keys())
                placeholders = ", ".join(f"${i+2}" for i in range(len(updates)))
                vals = [interaction.guild_id] + list(updates.values())
                await conn.execute(
                    f"INSERT INTO guild_config (guild_id, {keys}) VALUES ($1, {placeholders}) "
                    f"ON CONFLICT (guild_id) DO UPDATE SET {set_clause}",
                    *vals
                )

            if bump_channel:
                await conn.execute(
                    "INSERT INTO utility_config (guild_id, bump_channel_id) VALUES ($1, $2) "
                    "ON CONFLICT (guild_id) DO UPDATE SET bump_channel_id = $2",
                    interaction.guild_id, bump_channel.id
                )

        lines = []
        if auto_role:       lines.append(f"Auto-role: {auto_role.mention}")
        if mod_log:         lines.append(f"Mod log: {mod_log.mention}")
        if bump_channel:    lines.append(f"Bump channel: {bump_channel.mention}")
        if welcome_channel: lines.append(f"Welcome: {welcome_channel.mention}")
        if ai_channel:      lines.append(f"AI channel: {ai_channel.mention}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── /config community ──────────────────────────────────────────────────────
    @app_commands.command(name="community", description="Configure community features")
    @app_commands.describe(
        starboard="Channel to post starred messages",
        star_threshold="Number of stars needed to appear on starboard",
        counting="Channel for the counting game",
        confessions="Channel for anonymous confessions",
        media_only="Channel that only allows images and videos",
    )
    async def community(
        self,
        interaction: discord.Interaction,
        starboard: discord.TextChannel = None,
        star_threshold: app_commands.Range[int, 1, 20] = None,
        counting: discord.TextChannel = None,
        confessions: discord.TextChannel = None,
        media_only: discord.TextChannel = None,
    ):
        if not any([starboard, counting, confessions, media_only]):
            return await interaction.response.send_message("Provide at least one channel.", ephemeral=True)

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """INSERT INTO community_config
                   (guild_id, starboard_channel_id, starboard_threshold, counting_channel_id,
                    confessions_channel_id, media_channel_id)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (guild_id) DO UPDATE SET
                     starboard_channel_id  = COALESCE($2, community_config.starboard_channel_id),
                     starboard_threshold   = COALESCE($3, community_config.starboard_threshold),
                     counting_channel_id   = COALESCE($4, community_config.counting_channel_id),
                     confessions_channel_id= COALESCE($5, community_config.confessions_channel_id),
                     media_channel_id      = COALESCE($6, community_config.media_channel_id)
                """,
                interaction.guild_id,
                starboard.id if starboard else None,
                star_threshold,
                counting.id if counting else None,
                confessions.id if confessions else None,
                media_only.id if media_only else None,
            )

        lines = []
        if starboard:   lines.append(f"Starboard: {starboard.mention} (threshold: {star_threshold or 3} stars)")
        if counting:    lines.append(f"Counting: {counting.mention}")
        if confessions: lines.append(f"Confessions: {confessions.mention}")
        if media_only:  lines.append(f"Media-only: {media_only.mention}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── /config stream ─────────────────────────────────────────────────────────
    @app_commands.command(name="stream", description="Configure the stream channel")
    @app_commands.describe(
        stream_chat="Text channel where /stream commands work",
        stream_vc="Voice channel for Go Live / screen share",
        announce="Channel to announce when someone starts streaming",
    )
    async def stream(
        self,
        interaction: discord.Interaction,
        stream_chat: discord.TextChannel = None,
        stream_vc: discord.VoiceChannel = None,
        announce: discord.TextChannel = None,
    ):
        if not any([stream_chat, stream_vc, announce]):
            return await interaction.response.send_message("Provide at least one option.", ephemeral=True)

        # Auto-detect if not provided
        if not stream_chat:
            stream_chat = discord.utils.get(interaction.guild.text_channels, name="📺・stream-chat")
        if not stream_vc:
            stream_vc = discord.utils.get(interaction.guild.voice_channels, name="🎥 stream")

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO stream_config (guild_id, stream_vc_id, announce_channel_id, stream_text_channel_id) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id) DO UPDATE SET "
                "stream_vc_id = COALESCE($2, stream_config.stream_vc_id), "
                "announce_channel_id = COALESCE($3, stream_config.announce_channel_id), "
                "stream_text_channel_id = COALESCE($4, stream_config.stream_text_channel_id)",
                interaction.guild_id,
                stream_vc.id if stream_vc else None,
                announce.id if announce else None,
                stream_chat.id if stream_chat else None,
            )

        lines = []
        if stream_chat: lines.append(f"Stream chat: {stream_chat.mention}")
        if stream_vc:   lines.append(f"Stream VC: {stream_vc.name}")
        if announce:    lines.append(f"Announcements: {announce.mention}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── /config shop ───────────────────────────────────────────────────────────
    @app_commands.command(name="shop", description="Add or remove items from the role shop")
    @app_commands.describe(
        action="Add or remove an item",
        name="Item name",
        role="Role to grant on purchase",
        price="Cost in coins",
        description="Short description shown in /shop",
        item_id="Item ID to remove (use /shop to find IDs)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
    ])
    async def shop(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        name: str = None,
        role: discord.Role = None,
        price: int = None,
        description: str = "",
        item_id: int = None,
    ):
        async with interaction.client.db.acquire() as conn:
            if action.value == "add":
                if not name or not role or not price:
                    return await interaction.response.send_message(
                        "Provide name, role, and price to add an item.", ephemeral=True
                    )
                iid = await conn.fetchval(
                    "INSERT INTO shop_items (guild_id, name, description, role_id, price) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                    interaction.guild_id, name, description, role.id, price
                )
                await interaction.response.send_message(
                    f"Added **{name}** to shop (ID: `{iid}`, price: {price:,} coins).", ephemeral=True
                )
            else:
                if not item_id:
                    return await interaction.response.send_message("Provide an item_id to remove.", ephemeral=True)
                result = await conn.execute(
                    "DELETE FROM shop_items WHERE id = $1 AND guild_id = $2", item_id, interaction.guild_id
                )
                if result == "DELETE 0":
                    return await interaction.response.send_message("Item not found.", ephemeral=True)
                await interaction.response.send_message(f"Removed item `{item_id}` from shop.", ephemeral=True)


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_group = ConfigGroup(name="config", description="Configure JARVIS for this server")
        bot.tree.add_command(self.config_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("config")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Config(bot))
