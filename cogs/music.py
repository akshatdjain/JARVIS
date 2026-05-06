import os
import re
import datetime
import asyncio
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
import wavelink


# ── Now-Playing card with controls ────────────────────────────────────────────
class MusicView(discord.ui.View):
    def __init__(self, bot, track_title: str = ""):
        super().__init__(timeout=None)
        self.bot = bot
        self.track_title = track_title

    # Row 0 — playback controls
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="prev_btn", row=0)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("No previous track in queue.", ephemeral=True)

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, custom_id="pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not active.", ephemeral=True)
        await vc.pause(not vc.paused)
        button.emoji = "▶️" if vc.paused else "⏸️"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="skip_btn", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not active.", ephemeral=True)
        await vc.skip(force=True)
        await interaction.response.send_message("Skipped.", ephemeral=True)

    # Row 1 — extras
    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="shuffle_btn", row=1)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not active.", ephemeral=True)
        vc.queue.shuffle()
        await interaction.response.send_message("Queue shuffled.", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="loop_btn", row=1)
    async def loop_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not active.", ephemeral=True)
        modes = [wavelink.QueueMode.normal, wavelink.QueueMode.loop, wavelink.QueueMode.loop_all]
        labels = {wavelink.QueueMode.normal: "Loop off", wavelink.QueueMode.loop: "Loop track", wavelink.QueueMode.loop_all: "Loop queue"}
        icons = {wavelink.QueueMode.normal: "🔁", wavelink.QueueMode.loop: "🔂", wavelink.QueueMode.loop_all: "🔁"}
        current = vc.queue.mode
        next_mode = modes[(modes.index(current) + 1) % 3]
        vc.queue.mode = next_mode
        button.emoji = icons[next_mode]
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(labels[next_mode], ephemeral=True)

    @discord.ui.button(label="Lyrics", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="lyrics_btn", row=1)
    async def lyrics_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        vc: wavelink.Player = interaction.guild.voice_client
        track = vc.current if vc else None
        title = track.title if track else self.track_title
        author = re.sub(r'\s*-\s*Topic$', '', track.author or '').strip() if track else ""
        if not title:
            return await interaction.followup.send("Nothing playing.", ephemeral=True)
        async with aiohttp.ClientSession() as session:
            try:
                params = {"track_name": title, "artist_name": author} if author else {"track_name": title}
                async with session.get("https://lrclib.net/api/get", params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        async with session.get("https://lrclib.net/api/search", params={"q": title}, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                            if resp2.status != 200:
                                return await interaction.followup.send(f"No lyrics found for **{title}**.", ephemeral=True)
                            results = await resp2.json()
                            lyrics = results[0].get("plainLyrics", "") if results else ""
                    else:
                        data = await resp.json()
                        lyrics = data.get("plainLyrics", "")
            except Exception:
                return await interaction.followup.send("Lyrics service unavailable.", ephemeral=True)
        if not lyrics:
            return await interaction.followup.send(f"No lyrics found for **{title}**.", ephemeral=True)
        embed = discord.Embed(title=f"Lyrics — {title}", description=lyrics[:3900], color=0x1C1C1E)
        if author:
            embed.set_footer(text=author)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="🛑", style=discord.ButtonStyle.danger, custom_id="stop_btn", row=1)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not active.", ephemeral=True)
        await vc.disconnect()
        await interaction.response.send_message("Stopped.", ephemeral=True)


def format_duration(ms: int) -> str:
    s = str(datetime.timedelta(milliseconds=ms)).split(".")[0]
    return s[2:] if s.startswith("0:") else s


async def get_vc(interaction: discord.Interaction) -> wavelink.Player:
    vc: wavelink.Player = interaction.guild.voice_client
    if vc and vc.channel != interaction.user.voice.channel:
        await vc.move_to(interaction.user.voice.channel)
        return vc
    if not vc:
        vc = await interaction.user.voice.channel.connect(cls=wavelink.Player, self_deaf=True, timeout=None)
    return vc


def _now_playing_embed(track: wavelink.Playable, player: wavelink.Player) -> discord.Embed:
    embed = discord.Embed(color=0x1C1C1E)
    artist = track.author or "Unknown Artist"
    # Strip " - Topic" suffix from YouTube auto-generated channels
    artist = re.sub(r'\s*-\s*Topic$', '', artist).strip()
    embed.description = f"### [{track.title}]({track.uri})\n{artist}"
    if track.artwork:
        embed.set_image(url=track.artwork)
    duration = format_duration(track.length)
    queue_len = len(player.queue)
    loop_icons = {
        wavelink.QueueMode.normal: "",
        wavelink.QueueMode.loop: " 🔂",
        wavelink.QueueMode.loop_all: " 🔁",
    }
    loop_str = loop_icons.get(player.queue.mode, "")
    meta = f"`{duration}`"
    if queue_len:
        meta += f"  `{queue_len} in queue`"
    if loop_str:
        meta += loop_str
    embed.add_field(name="", value=meta, inline=False)
    return embed


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.loop.create_task(self._connect_node())

    async def _connect_node(self):
        await self.bot.wait_until_ready()
        node = wavelink.Node(uri="http://localhost:2333", password=os.getenv("LAVALINK_PASSWORD", "youshallnotpass"))
        await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        import logging
        log = logging.getLogger("jarvis")
        log.info("Lavalink node ready: %s (resumed=%s)", payload.node.identifier, payload.resumed)
        if not payload.resumed:
            for guild in self.bot.guilds:
                vc = guild.voice_client
                if vc and isinstance(vc, wavelink.Player):
                    try:
                        await vc.disconnect()
                        log.info("Disconnected stale player in guild %s", guild.id)
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        track = payload.track
        if not hasattr(player, "text_channel") or not player.text_channel:
            return
        embed = _now_playing_embed(track, player)
        requester = getattr(player, "requested_by", None)
        if requester:
            embed.set_footer(text=f"Queued by {requester.display_name}", icon_url=requester.display_avatar.url)
        embed.timestamp = datetime.datetime.now()
        view = MusicView(self.bot, track_title=track.title)

        # Show next up if queue has items
        if player.queue:
            next_track = player.queue.peek(0)
            if next_track:
                next_artist = re.sub(r'\s*-\s*Topic$', '', next_track.author or '').strip()
                embed.add_field(
                    name="⏭️ Next up",
                    value=f"**{next_track.title}**{f' — {next_artist}' if next_artist else ''}",
                    inline=False,
                )

        await player.text_channel.send(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        player = payload.player
        track = payload.track
        clean_title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", track.title).strip()
        author = re.sub(r'\s*-\s*Topic$', '', track.author or '').strip()

        if hasattr(player, "text_channel") and player.text_channel:
            await player.text_channel.send(f"⚠️ Blocked: **{track.title}**. Trying fallbacks...")

        for source, query in [
            ("scsearch:", f"{clean_title} {author}".strip()),
            ("scsearch:", clean_title),
            ("ytsearch:", f"{clean_title} {author}".strip()),
        ]:
            try:
                results = await wavelink.Playable.search(query, source=source)
                if results:
                    await player.play(results[0], add_history=False)
                    return
            except Exception:
                pass

        if hasattr(player, "text_channel") and player.text_channel:
            await player.text_channel.send(f"❌ **{track.title}** unavailable everywhere. Skipping.")

        # Advance queue manually if autoplay didn't trigger
        if not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        # Handled by music_extras cog (247 mode check)
        pass

    # ── /play ─────────────────────────────────────────────────────────────────
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

        # Set autoplay to partial — auto-advances queue, no recommendations
        vc.autoplay = wavelink.AutoPlayMode.partial

        tracks = None
        for source in (None, "ytsearch:", "scsearch:"):
            try:
                tracks = await wavelink.Playable.search(query, source=source)
                if tracks:
                    break
            except Exception:
                pass

        if not tracks:
            return await interaction.followup.send(f"❌ No results found for `{query}`.")

        if isinstance(tracks, wavelink.Playlist):
            added = await vc.queue.put_wait(tracks)
            msg = f"✅ Added playlist **{tracks.name}** — {added} tracks."
        else:
            track = tracks[0]
            await vc.queue.put_wait(track)
            msg = f"✅ Added **{track.title}** to queue."

        await interaction.followup.send(msg)

        # Start playing if not already — use the queue so order is preserved
        if not vc.playing:
            next_track = vc.queue.get()
            await vc.play(next_track)

    # ── Controls ──────────────────────────────────────────────────────────────
    @app_commands.command(name="skip", description="Skip the current track")
    async def skip(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)
        await vc.skip(force=True)
        await interaction.response.send_message("⏭️ Skipped!")

    @app_commands.command(name="stop", description="Stop playback and disconnect")
    async def stop(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not in a voice channel!", ephemeral=True)
        vc.queue.clear()
        await vc.stop()
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

    @app_commands.command(name="loop", description="Set loop mode")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Track", value="track"),
        app_commands.Choice(name="Queue", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not active!", ephemeral=True)
        mode_map = {
            "off": wavelink.QueueMode.normal,
            "track": wavelink.QueueMode.loop,
            "queue": wavelink.QueueMode.loop_all,
        }
        vc.queue.mode = mode_map[mode.value]
        icons = {"off": "➡️", "track": "🔂", "queue": "🔁"}
        await interaction.response.send_message(f"{icons[mode.value]} Loop set to **{mode.name}**.")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc or vc.queue.is_empty:
            return await interaction.response.send_message("❌ Queue is empty!", ephemeral=True)
        vc.queue.shuffle()
        await interaction.response.send_message("🔀 Queue shuffled!")

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction):
        vc: wavelink.Player = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Not active!", ephemeral=True)
        embed = discord.Embed(title="🎶 Queue", color=0x2B2D31)
        if vc.current:
            embed.add_field(
                name="Now Playing",
                value=f"**{vc.current.title}** `{format_duration(vc.current.length)}`",
                inline=False,
            )
        if not vc.queue.is_empty:
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
        embed = _now_playing_embed(vc.current, vc)
        pos = format_duration(vc.position)
        dur = format_duration(vc.current.length)
        embed.add_field(name="Progress", value=f"`{pos} / {dur}`", inline=True)
        embed.add_field(name="🔊 Volume", value=f"`{vc.volume}%`", inline=True)
        await interaction.response.send_message(embed=embed, view=MusicView(self.bot, track_title=vc.current.title))

    @app_commands.command(name="lyrics", description="Get lyrics for the current or a specific song")
    async def lyrics(self, interaction: discord.Interaction, song: str = None):
        await interaction.response.defer()
        vc: wavelink.Player = interaction.guild.voice_client
        query = song or (vc.current.title if vc and vc.current else None)
        if not query:
            return await interaction.followup.send("❌ Nothing is playing and no song specified!")
        author = re.sub(r'\s*-\s*Topic$', '', (vc.current.author or '') if (vc and vc.current and not song) else '').strip()
        async with aiohttp.ClientSession() as session:
            try:
                params = {"track_name": query, "artist_name": author} if author else {"track_name": query}
                async with session.get("https://lrclib.net/api/get", params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        async with session.get("https://lrclib.net/api/search", params={"q": query}, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                            if resp2.status != 200:
                                return await interaction.followup.send(f"❌ No lyrics found for **{query}**.")
                            results = await resp2.json()
                            lyrics = results[0].get("plainLyrics", "") if results else ""
                    else:
                        data = await resp.json()
                        lyrics = data.get("plainLyrics", "")
            except Exception:
                return await interaction.followup.send("❌ Lyrics service unavailable.")
        if not lyrics:
            return await interaction.followup.send(f"❌ No lyrics found for **{query}**.")
        chunks = [lyrics[i:i+3900] for i in range(0, min(len(lyrics), 7800), 3900)]
        embed = discord.Embed(title=f"🎵 Lyrics — {query}", description=chunks[0], color=0x1C1C1E)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.channel.send(embed=discord.Embed(description=chunk, color=0x1C1C1E))

    @app_commands.command(name="summon", description="Summon the bot to your voice channel")
    async def summon(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.voice:
            return await interaction.edit_original_response(content="❌ Join a voice channel first!")
        try:
            vc = await get_vc(interaction)
            vc.text_channel = interaction.channel
            vc.autoplay = wavelink.AutoPlayMode.partial
        except Exception as e:
            return await interaction.edit_original_response(content=f"❌ Could not connect: {e}")
        await interaction.edit_original_response(content=f"✅ Joined **{interaction.user.voice.channel.name}**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
