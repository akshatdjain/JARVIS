import asyncio
import hashlib
import discord
from discord.ext import commands
from discord import app_commands

SCHEMA = """
CREATE TABLE IF NOT EXISTS starboard_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    threshold INTEGER DEFAULT 3
);
CREATE TABLE IF NOT EXISTS starboard_entries (
    original_message_id BIGINT PRIMARY KEY,
    starboard_message_id BIGINT,
    guild_id BIGINT
);
CREATE TABLE IF NOT EXISTS counting_state (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    current_count INTEGER DEFAULT 0,
    last_user_id BIGINT
);
CREATE TABLE IF NOT EXISTS confessions (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    user_id BIGINT,
    receipt_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS community_config (
    guild_id BIGINT PRIMARY KEY,
    media_channel_id BIGINT,
    counting_channel_id BIGINT,
    confessions_channel_id BIGINT,
    starboard_channel_id BIGINT,
    starboard_threshold INTEGER DEFAULT 3
);
"""

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm"}


def make_receipt(user_id: int, confession_id: int) -> str:
    return hashlib.sha256(f"{user_id}{confession_id}".encode()).hexdigest()[:10].upper()


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._init_db())

    async def _init_db(self):
        await self.bot.wait_until_ready()
        async with self.bot.db.acquire() as conn:
            await conn.execute(SCHEMA)

    async def _get_config(self, guild_id: int):
        async with self.bot.db.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM community_config WHERE guild_id = $1", guild_id)

    # ── STARBOARD ──────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != "⭐":
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        config = await self._get_config(payload.guild_id)
        if not config or not config["starboard_channel_id"]:
            return

        starboard_ch = guild.get_channel(config["starboard_channel_id"])
        if not starboard_ch:
            return

        try:
            channel = guild.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        # Count ⭐ reactions
        star_reaction = discord.utils.get(message.reactions, emoji="⭐")
        count = star_reaction.count if star_reaction else 0
        threshold = config["starboard_threshold"] or 3

        if count < threshold:
            return

        async with self.bot.db.acquire() as conn:
            entry = await conn.fetchrow(
                "SELECT starboard_message_id FROM starboard_entries WHERE original_message_id = $1",
                payload.message_id
            )

        embed = discord.Embed(
            description=message.content or "*[no text]*",
            color=0xF1C40F,
            timestamp=message.created_at,
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Source", value=f"[Jump to message]({message.jump_url})", inline=False)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        embed.set_footer(text=f"⭐ {count} | #{channel.name}")

        if entry:
            try:
                sb_msg = await starboard_ch.fetch_message(entry["starboard_message_id"])
                await sb_msg.edit(embed=embed)
            except discord.HTTPException:
                pass
        else:
            sb_msg = await starboard_ch.send(embed=embed)
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO starboard_entries (original_message_id, starboard_message_id, guild_id) VALUES ($1, $2, $3)",
                    payload.message_id, sb_msg.id, payload.guild_id
                )

    # ── COUNTING ───────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = await self._get_config(message.guild.id)
        if not config:
            return

        # Media-only enforcement
        if config["media_channel_id"] and message.channel.id == config["media_channel_id"]:
            has_media = any(
                any(message.content.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
                or att.content_type and att.content_type.startswith(("image/", "video/"))
                for att in message.attachments
            ) if message.attachments else False

            if not has_media and not message.attachments:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention} only images and videos here!",
                        delete_after=5
                    )
                except discord.HTTPException:
                    pass
                return

        # Counting game
        if config["counting_channel_id"] and message.channel.id == config["counting_channel_id"]:
            await self._handle_counting(message)

    async def _handle_counting(self, message: discord.Message):
        async with self.bot.db.acquire() as conn:
            state = await conn.fetchrow(
                "SELECT * FROM counting_state WHERE guild_id = $1", message.guild.id
            )
            current = state["current_count"] if state else 0
            last_user = state["last_user_id"] if state else None

        # Parse the number
        try:
            number = int(message.content.strip())
        except ValueError:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        expected = current + 1

        if number == expected and message.author.id != last_user:
            await message.add_reaction("✅")
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO counting_state (guild_id, channel_id, current_count, last_user_id) VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT (guild_id) DO UPDATE SET current_count = $3, last_user_id = $4",
                    message.guild.id, message.channel.id, expected, message.author.id
                )
        else:
            await message.add_reaction("❌")
            reason = "Same person can't count twice in a row!" if message.author.id == last_user else f"Wrong number! Expected `{expected}`."
            await message.channel.send(
                f"💥 {message.author.mention} ruined it at **{current}**! {reason} Starting over from 0.",
                delete_after=10
            )
            # Reset
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO counting_state (guild_id, channel_id, current_count, last_user_id) VALUES ($1, $2, 0, NULL) "
                    "ON CONFLICT (guild_id) DO UPDATE SET current_count = 0, last_user_id = NULL",
                    message.guild.id, message.channel.id
                )
            # Timeout the offender briefly
            try:
                import datetime
                await message.author.timeout(
                    discord.utils.utcnow() + datetime.timedelta(seconds=30),
                    reason="Ruined counting game"
                )
            except discord.HTTPException:
                pass

    # ── CONFESSIONS ────────────────────────────────────────────────────────────
    @app_commands.command(name="confess", description="Post an anonymous confession")
    async def confess(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)

        config = await self._get_config(interaction.guild_id)
        if not config or not config["confessions_channel_id"]:
            return await interaction.edit_original_response(
                content="❌ Confessions channel not set. Ask an admin to run `/communitysetup`."
            )

        channel = interaction.guild.get_channel(config["confessions_channel_id"])
        if not channel:
            return await interaction.edit_original_response(content="❌ Confessions channel not found.")

        async with self.bot.db.acquire() as conn:
            conf_id = await conn.fetchval(
                "INSERT INTO confessions (guild_id, channel_id, user_id, receipt_id) VALUES ($1, $2, $3, $4) RETURNING id",
                interaction.guild_id, channel.id, interaction.user.id, "TEMP"
            )
            receipt = make_receipt(interaction.user.id, conf_id)
            await conn.execute("UPDATE confessions SET receipt_id = $1 WHERE id = $2", receipt, conf_id)

        embed = discord.Embed(
            title=f"🤫 Anonymous Confession #{conf_id}",
            description=message,
            color=0x2B2D31,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Posted anonymously")
        conf_msg = await channel.send(embed=embed)

        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE confessions SET message_id = $1 WHERE id = $2", conf_msg.id, conf_id)

        await interaction.edit_original_response(
            content=f"✅ Confession posted anonymously!\nYour receipt ID: `{receipt}` (save this — mods can use it to trace if needed)"
        )

    @app_commands.command(name="reveal", description="Reveal who posted a confession (mod only)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reveal(self, interaction: discord.Interaction, receipt_id: str):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, id FROM confessions WHERE receipt_id = $1 AND guild_id = $2",
                receipt_id.upper(), interaction.guild_id
            )
        if not row:
            return await interaction.response.send_message("❌ Receipt not found.", ephemeral=True)
        user = interaction.guild.get_member(row["user_id"])
        name = str(user) if user else f"Unknown (ID: {row['user_id']})"
        await interaction.response.send_message(
            f"🔍 Confession #{row['id']} was posted by **{name}**", ephemeral=True
        )

    # ── SETUP COMMANDS ─────────────────────────────────────────────────────────
    @app_commands.command(name="communitysetup", description="Configure community features")
    @app_commands.checks.has_permissions(administrator=True)
    async def communitysetup(
        self,
        interaction: discord.Interaction,
        starboard: discord.TextChannel = None,
        starboard_threshold: app_commands.Range[int, 1, 20] = 3,
        counting: discord.TextChannel = None,
        confessions: discord.TextChannel = None,
        media_only: discord.TextChannel = None,
    ):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """INSERT INTO community_config
                   (guild_id, starboard_channel_id, starboard_threshold, counting_channel_id, confessions_channel_id, media_channel_id)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (guild_id) DO UPDATE SET
                     starboard_channel_id = COALESCE($2, community_config.starboard_channel_id),
                     starboard_threshold = $3,
                     counting_channel_id = COALESCE($4, community_config.counting_channel_id),
                     confessions_channel_id = COALESCE($5, community_config.confessions_channel_id),
                     media_channel_id = COALESCE($6, community_config.media_channel_id)
                """,
                interaction.guild_id,
                starboard.id if starboard else None,
                starboard_threshold,
                counting.id if counting else None,
                confessions.id if confessions else None,
                media_only.id if media_only else None,
            )

        lines = []
        if starboard:   lines.append(f"⭐ Starboard: {starboard.mention} (threshold: {starboard_threshold})")
        if counting:    lines.append(f"🔢 Counting: {counting.mention}")
        if confessions: lines.append(f"🤫 Confessions: {confessions.mention}")
        if media_only:  lines.append(f"📸 Media-only: {media_only.mention}")

        await interaction.response.send_message(
            "✅ Community features configured:\n" + "\n".join(lines) if lines else "✅ Nothing changed.",
            ephemeral=True
        )



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Community(bot))
