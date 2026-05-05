import datetime
import asyncio
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
import wavelink


class MusicView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.secondary, custom_id="pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Player not active!", ephemeral=True)
        await vc.pause(not vc.paused)
        await interaction.response.send_message(f"✅ {'Paused' if vc.paused else 'Resumed'}!", ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary, custom_id="skip_btn")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Player not active!", ephemeral=True)
        await vc.skip()
        await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)

    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary, custom_id="shuffle_btn")
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Player not active!", ephemeral=True)
        vc.queue.shuffle()
        await interaction.response.send_message("🔀 Queue shuffled!", ephemeral=True)

    @discord.ui.button(label="🛑", style=discord.ButtonStyle.danger, custom_id="stop_btn")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Player not active!", ephemeral=True)
        await vc.disconnect()
        await interaction.response.send_message("🛑 Disconnected!", ephemeral=True)


def format_duration(ms: int) -> str:
    s = str(datetime.timedelta(milliseconds=ms)).split(".")[0]
    return s[2:] if s.startswith("0:") else s


async def get_vc(interaction: discord.Interaction) -> wavelink.Player | None:
    vc: wavelink.Player = interaction.guild.voice_client
    if vc and vc.channel != interaction.user.voice.channel:
        await vc.disconnect()
        vc = None
    if not vc:
        vc = await interaction.user.voice.channel.connect(
            cls=wavelink.Player, self_deaf=True, timeout=None
        )
    return vc


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.loop.create_task(self._connect_node())

    async def _connect_node(self):
        await self.bot.wait_until_ready()
        node = wavelink.Node(uri="http://localhost:2333", password="youshallnotpass")
        await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        import logging
        logging.getLogger("jarvis").info("Lavalink node ready: %s", payload.node.identifier)

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        track = payload.track

        loop_status = ""
        if hasattr(player, "loop_mode"):
            if player.loop_mode == "track":
                loop_status = " • 🔂 Looping Track"
            elif player.loop_mode == "queue":
                loop_status = " • 🔁 Looping Queue"

        embed = discord.Embed(
            title="📻 Now Playing",
            description=f"**[{track.title}]({track.uri})**",
            color=0x2B2D31,
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        embed.add_field(name="⏱️ Duration", value=f"`{format_duration(track.length)}`", inline=True)
        requester = player.requested_by.mention if hasattr(player, "requested_by") else "Unknown"
        embed.add_field(name="🎧 Requester", value=requester, inline=True)
        embed.add_field(name="⏭️ Queue", value=f"`{len(player.queue)} tracks`{loop_status}", inline=False)
        embed.set_footer(
            text="JARVIS Music",
            icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None,
        )
        embed.timestamp = datetime.datetime.now()

        if hasattr(player, "text_channel") and player.text_channel:
            await player.text_channel.send(embed=embed, view=MusicView(self.bot))

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if not hasattr(player, "loop_mode"):
            return

        if player.loop_mode == "track" and payload.track:
            await player.play(payload.track)
        elif player.loop_mode == "queue" and payload.track:
            await player.queue.put_wait(payload.track)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        player = payload.player
        track = payload.track

        import re
        # Strip noise like (Lyrical), (Official), (Audio), [HD] etc for cleaner fallback search
        clean_title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", track.title).strip()

        if hasattr(player, "text_channel") and player.text_channel:
            await player.text_channel.send(f"⚠️ Blocked: **{track.title}**. Trying fallbacks...")

        # Try SoundCloud with clean title, then full title, then YouTube with clean title
        for source, query in [
            ("scsearch:", clean_title),
            ("scsearch:", track.title),
            ("ytsearch:", clean_title),
        ]:
            try:
                results = await wavelink.Playable.search(query, source=source)
                if results:
                    await player.play(results[0])
                    return
            except Exception:
                pass

        if hasattr(player, "text_channel") and player.text_channel:
            await player.text_channel.send(f"❌ **{track.title}** is unavailable on all sources. Skipping.")

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        await player.disconnect()

    @app_commands.command(name="play", description="Play a song from YouTube, Spotify, SoundCloud, or a URL")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        if not interaction.user.voice:
            return await interaction.followup.send("❌ Join a voice channel first!")
        try:
            vc = await get_vc(interaction)
        except Exception as e:
            return await interaction.followup.send(f"❌ Connection error: {e}")

        vc.text_channel = interaction.channel
        vc.requested_by = interaction.user
        if not hasattr(vc, "loop_mode"):
            vc.loop_mode = "off"

        tracks = None
        # Try direct URL/Spotify first, then YouTube, then SoundCloud as fallback
        for source in (None, "ytsearch:", "scsearch:"):
            try:
                if source:
                    tracks = await wavelink.Playable.search(query, source=source)
                else:
                    tracks = await wavelink.Playable.search(query)
                if tracks:
                    break
            except Exception:
                pass

        if not tracks:
            return await interaction.followup.send(f"❌ No results found for `{query}`.")

        if isinstance(tracks, wavelink.Playlist):
            added = await vc.queue.put_wait(tracks)
            await interaction.followup.send(f"✅ Added playlist **{tracks.name}** ({added} tracks).")
        else:
            track = tracks[0]
            await vc.queue.put_wait(track)
            await interaction.followup.send(f"✅ Added **{track.title}** to queue.")

        if not vc.playing:
            await vc.play(vc.queue.get())

    @app_commands.command(name="skip", description="Skip the current track")
    async def skip(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)
        await vc.skip()
        await interaction.response.send_message("⏭️ Skipped!")

    @app_commands.command(name="stop", description="Stop playback and disconnect")
    async def stop(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not in a voice channel!", ephemeral=True)
        await vc.disconnect()
        await interaction.response.send_message("🛑 Stopped and disconnected.")

    @app_commands.command(name="pause", description="Pause or resume playback")
    async def pause(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not active!", ephemeral=True)
        await vc.pause(not vc.paused)
        await interaction.response.send_message(f"{'⏸️ Paused' if vc.paused else '▶️ Resumed'}!")

    @app_commands.command(name="volume", description="Set playback volume (0–100)")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not active!", ephemeral=True)
        await vc.set_volume(level)
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.")

    @app_commands.command(name="seek", description="Seek to a position in the current track (seconds)")
    async def seek(self, interaction: discord.Interaction, seconds: int):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or not vc.current:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)
        ms = seconds * 1000
        if ms > vc.current.length:
            return await interaction.response.send_message("❌ Position exceeds track length!", ephemeral=True)
        await vc.seek(ms)
        await interaction.response.send_message(f"⏩ Seeked to `{format_duration(ms)}`.")

    @app_commands.command(name="loop", description="Toggle loop mode (off/track/queue)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Track", value="track"),
        app_commands.Choice(name="Queue", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not active!", ephemeral=True)
        vc.loop_mode = mode.value
        icons = {"off": "➡️", "track": "🔂", "queue": "🔁"}
        await interaction.response.send_message(f"{icons[mode.value]} Loop set to **{mode.name}**.")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or not vc.queue:
            return await interaction.response.send_message("❌ Queue is empty!", ephemeral=True)
        vc.queue.shuffle()
        await interaction.response.send_message("🔀 Queue shuffled!")

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)
        embed = discord.Embed(title="🎶 Queue", color=0x2B2D31)
        if vc.current:
            embed.add_field(name="Now Playing", value=f"**{vc.current.title}** `{format_duration(vc.current.length)}`", inline=False)
        if vc.queue:
            lines = [f"`{i+1}.` {t.title} `{format_duration(t.length)}`" for i, t in enumerate(list(vc.queue)[:10])]
            if len(vc.queue) > 10:
                lines.append(f"*...and {len(vc.queue) - 10} more*")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="Queue is empty.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Show the currently playing track")
    async def nowplaying(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or not vc.current:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)
        track = vc.current
        embed = discord.Embed(title="📻 Now Playing", description=f"**[{track.title}]({track.uri})**", color=0x2B2D31)
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        pos = format_duration(vc.position)
        dur = format_duration(track.length)
        embed.add_field(name="Progress", value=f"`{pos} / {dur}`", inline=True)
        embed.add_field(name="🔊 Volume", value=f"`{vc.volume}%`", inline=True)
        loop_mode = getattr(vc, "loop_mode", "off")
        embed.add_field(name="🔁 Loop", value=f"`{loop_mode}`", inline=True)
        await interaction.response.send_message(embed=embed, view=MusicView(self.bot))

    @app_commands.command(name="lyrics", description="Get lyrics for the current or a specific song")
    async def lyrics(self, interaction: discord.Interaction, song: str = None):
        await interaction.response.defer()
        vc: wavelink.Player = interaction.guild.voice_client
        query = song or (vc.current.title if vc and vc.current else None)
        if not query:
            return await interaction.followup.send("❌ Nothing is playing and no song specified!")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://api.lyrics.ovh/v1/{query.replace(' ', '/')}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(f"❌ No lyrics found for **{query}**.")
                    data = await resp.json()
                    lyrics = data.get("lyrics", "")
            except Exception:
                return await interaction.followup.send("❌ Lyrics service unavailable.")

        if not lyrics:
            return await interaction.followup.send(f"❌ No lyrics found for **{query}**.")

        chunks = [lyrics[i:i+4000] for i in range(0, min(len(lyrics), 8000), 4000)]
        embed = discord.Embed(title=f"🎵 Lyrics — {query}", description=chunks[0], color=0x2B2D31)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.channel.send(embed=discord.Embed(description=chunk, color=0x2B2D31))

    @app_commands.command(name="summon", description="Summon the bot to your voice channel")
    async def summon(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.voice:
            return await interaction.edit_original_response(content="❌ Join a voice channel first!")

        vc: wavelink.Player = interaction.guild.voice_client
        if vc:
            await vc.move_to(interaction.user.voice.channel)
        else:
            try:
                vc = await interaction.user.voice.channel.connect(
                    cls=wavelink.Player, self_deaf=True, timeout=None
                )
            except Exception as e:
                return await interaction.edit_original_response(content=f"❌ Could not connect: {e}")

        vc.text_channel = interaction.channel
        if not hasattr(vc, "loop_mode"):
            vc.loop_mode = "off"
        await interaction.edit_original_response(content=f"✅ Joined **{interaction.user.voice.channel.name}**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
