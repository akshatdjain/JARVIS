import urllib.parse
import discord
from discord.ext import commands
from discord import app_commands

SCHEMA = """
CREATE TABLE IF NOT EXISTS stream_config (
    guild_id BIGINT PRIMARY KEY,
    stream_vc_id BIGINT,
    announce_channel_id BIGINT,
    stream_text_channel_id BIGINT
);
"""


class Stream(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._init_db())
        self._active_streams: dict[int, int] = {}  # user_id -> guild_id

    async def _init_db(self):
        await self.bot.wait_until_ready()
        async with self.bot.db.acquire() as conn:
            await conn.execute(SCHEMA)

    async def _get_config(self, guild_id: int):
        async with self.bot.db.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM stream_config WHERE guild_id = $1", guild_id)

    # ── Detect when someone starts/stops streaming in the stream VC ───────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        config = await self._get_config(member.guild.id)
        if not config or not config["stream_vc_id"]:
            return

        stream_vc_id = config["stream_vc_id"]
        announce_ch_id = config["announce_channel_id"]

        # Someone started streaming in the stream VC
        started_stream = (
            after.channel and after.channel.id == stream_vc_id and
            after.self_stream and not (before.self_stream and before.channel and before.channel.id == stream_vc_id)
        )

        # Someone stopped streaming
        stopped_stream = (
            before.self_stream and before.channel and before.channel.id == stream_vc_id and
            not (after.self_stream and after.channel and after.channel.id == stream_vc_id)
        )

        if started_stream:
            self._active_streams[member.id] = member.guild.id
            if announce_ch_id:
                ch = member.guild.get_channel(announce_ch_id)
                if ch:
                    embed = discord.Embed(
                        title="🎥 Stream Started!",
                        description=f"{member.mention} is now live in <#{stream_vc_id}>!",
                        color=0x9B59B6,
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text="Join the voice channel to watch!")
                    await ch.send(embed=embed)

        elif stopped_stream:
            self._active_streams.pop(member.id, None)

    # ── /streamsetup — create or configure the stream channel ─────────────────
    @app_commands.command(name="streamsetup", description="Create a stream voice channel and configure announcements")
    @app_commands.checks.has_permissions(administrator=True)
    async def streamsetup(
        self,
        interaction: discord.Interaction,
        stream_chat: discord.TextChannel = None,
        announce_channel: discord.TextChannel = None,
        existing_vc: discord.VoiceChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if existing_vc:
            stream_vc = existing_vc
        else:
            # Create a dedicated stream VC if it doesn't exist
            stream_vc = discord.utils.get(guild.voice_channels, name="🎥 stream")
            if not stream_vc:
                # Find or create a Voice Channels category
                cat = discord.utils.get(guild.categories, name="Voice Channels") or \
                      discord.utils.get(guild.categories, name="🎵 MUSIC")
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True,
                        connect=True,
                        stream=True,
                        use_voice_activation=True,
                    ),
                    guild.me: discord.PermissionOverwrite(
                        view_channel=True,
                        connect=True,
                        manage_channels=True,
                        mute_members=True,
                    ),
                }
                stream_vc = await guild.create_voice_channel(
                    "🎥 stream",
                    category=cat,
                    overwrites=overwrites,
                    bitrate=96000,
                )

        # Auto-detect stream chat channel if not provided
        if not stream_chat:
            stream_chat = discord.utils.get(guild.text_channels, name="📺・stream-chat")

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO stream_config (guild_id, stream_vc_id, announce_channel_id, stream_text_channel_id) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (guild_id) DO UPDATE SET stream_vc_id = $2, announce_channel_id = $3, stream_text_channel_id = $4",
                guild.id, stream_vc.id,
                announce_channel.id if announce_channel else None,
                stream_chat.id if stream_chat else None,
            )

        msg = f"Stream VC: **{stream_vc.name}**"
        if stream_chat:
            msg += f"\nStream chat: {stream_chat.mention} (only channel where /stream works)"
        if announce_channel:
            msg += f"\nAnnouncements: {announce_channel.mention}"

        await interaction.edit_original_response(content=msg)



    @app_commands.command(name="stream", description="Search Hotstar or YouTube")
    @app_commands.choices(platform=[
        app_commands.Choice(name="Hotstar", value="hotstar"),
        app_commands.Choice(name="YouTube", value="yt"),
    ])
    async def stream(self, interaction: discord.Interaction, platform: app_commands.Choice[str], query: str):
        # Enforce stream chat channel
        config = await self._get_config(interaction.guild_id)
        if config and config.get("stream_text_channel_id"):
            if interaction.channel_id != config["stream_text_channel_id"]:
                ch = interaction.guild.get_channel(config["stream_text_channel_id"])
                return await interaction.response.send_message(
                    f"Use this command in {ch.mention}.", ephemeral=True
                )

        q = urllib.parse.quote_plus(query)
        if platform.value == "hotstar":
            url = f"https://www.hotstar.com/in/explore?search_query={q}"
            label = "Open Hotstar"
            color = 0x1F80E0
        else:
            url = f"https://www.youtube.com/results?search_query={q}"
            label = "Open YouTube"
            color = 0xFF0000

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
        # Respond with just the button — minimal, click to open
        await interaction.response.send_message(
            f"**{query}** on {platform.name} — click to open:",
            view=view
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stream(bot))
