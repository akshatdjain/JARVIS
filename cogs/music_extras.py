import discord
from discord.ext import commands
from discord import app_commands
import wavelink

SCHEMA = """
CREATE TABLE IF NOT EXISTS music_config (
    guild_id BIGINT PRIMARY KEY,
    dj_role_id BIGINT,
    music_channel_id BIGINT,
    mode_247 BOOLEAN DEFAULT FALSE
);
"""


def dj_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        async with interaction.client.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT dj_role_id FROM music_config WHERE guild_id = $1", interaction.guild_id
            )
        if not row or not row["dj_role_id"]:
            return True
        if interaction.user.guild_permissions.manage_guild:
            return True
        role = interaction.guild.get_role(row["dj_role_id"])
        if role and role in interaction.user.roles:
            return True
        await interaction.response.send_message(
            f"❌ You need the DJ role to use this command.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


class MusicExtras(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._init_db())

    async def _init_db(self):
        await self.bot.wait_until_ready()
        async with self.bot.db.acquire() as conn:
            await conn.execute(SCHEMA)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT mode_247 FROM music_config WHERE guild_id = $1",
                player.guild.id
            )
        if row and row["mode_247"]:
            return  # 24/7 mode: don't disconnect
        await player.disconnect()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT music_channel_id FROM music_config WHERE guild_id = $1", message.guild.id
            )
        if not row or not row["music_channel_id"]:
            return
        if message.channel.id != row["music_channel_id"]:
            return
        # Only allow slash commands (interactions) in music channel — delete regular messages
        if not message.interaction:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    @app_commands.command(name="setdj", description="Set the DJ role (only DJs can skip/stop/filter)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setdj(self, interaction: discord.Interaction, role: discord.Role):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO music_config (guild_id, dj_role_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET dj_role_id = $2",
                interaction.guild_id, role.id
            )
        await interaction.response.send_message(
            f"✅ DJ role set to {role.mention}. Only DJs can now control music.", ephemeral=True
        )

    @app_commands.command(name="setmusicchannel", description="Lock music commands to a specific channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setmusicchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO music_config (guild_id, music_channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET music_channel_id = $2",
                interaction.guild_id, channel.id
            )
        await interaction.response.send_message(
            f"✅ Music commands locked to {channel.mention}. Other messages there will be auto-deleted.", ephemeral=True
        )

    @app_commands.command(name="247", description="Toggle 24/7 mode — bot stays in VC forever")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mode_247(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT mode_247 FROM music_config WHERE guild_id = $1", interaction.guild_id
            )
            current = row["mode_247"] if row else False
            new_mode = not current
            await conn.execute(
                "INSERT INTO music_config (guild_id, mode_247) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET mode_247 = $2",
                interaction.guild_id, new_mode
            )
        icon = "🔁" if new_mode else "⏹️"
        status = "**enabled** — bot will stay in VC indefinitely" if new_mode else "**disabled** — bot will leave when queue ends"
        await interaction.response.send_message(f"{icon} 24/7 mode {status}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicExtras(bot))
