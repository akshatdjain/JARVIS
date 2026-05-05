import random
import asyncio
import discord
from discord.ext import commands
from discord import app_commands


XP_PER_MESSAGE = (15, 25)
XP_COOLDOWN_SECONDS = 60


def xp_for_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level


class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns: dict[tuple, asyncio.Task] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        key = (message.author.id, message.guild.id)
        if key in self._cooldowns:
            return

        xp_gain = random.randint(*XP_PER_MESSAGE)

        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO levels (user_id, guild_id, xp, level) VALUES ($1, $2, $3, 0) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET xp = levels.xp + $3 "
                "RETURNING xp, level",
                message.author.id, message.guild.id, xp_gain
            )
            new_xp = row["xp"]
            old_level = row["level"]
            new_level = level_from_xp(new_xp)

            if new_level > old_level:
                await conn.execute(
                    "UPDATE levels SET level = $1 WHERE user_id = $2 AND guild_id = $3",
                    new_level, message.author.id, message.guild.id
                )
                embed = discord.Embed(
                    title="⬆️ Level Up!",
                    description=f"{message.author.mention} reached **Level {new_level}**!",
                    color=0xF1C40F,
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=embed)
                # Assign level roles if roles cog is loaded
                roles_cog = self.bot.cogs.get("Roles")
                if roles_cog:
                    await roles_cog.assign_level_role(message.author, new_level)

        async def _reset_cooldown():
            await asyncio.sleep(XP_COOLDOWN_SECONDS)
            self._cooldowns.pop(key, None)

        self._cooldowns[key] = asyncio.create_task(_reset_cooldown())

    @app_commands.command(name="rank", description="Show your XP rank or another user's")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT xp, level FROM levels WHERE user_id = $1 AND guild_id = $2",
                target.id, interaction.guild_id
            )
            rank_row = await conn.fetchrow(
                "SELECT COUNT(*) + 1 AS rank FROM levels WHERE guild_id = $1 AND xp > $2",
                interaction.guild_id, row["xp"] if row else 0
            )

        if not row:
            return await interaction.response.send_message(f"❌ {target.display_name} has no XP yet.", ephemeral=True)

        xp = row["xp"]
        level = row["level"]
        next_level_xp = xp_for_level(level)
        current_xp = xp - sum(xp_for_level(i) for i in range(level))
        bar_filled = int((current_xp / next_level_xp) * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        embed = discord.Embed(title=f"📊 {target.display_name}'s Rank", color=0x2B2D31)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Rank", value=f"`#{rank_row['rank']}`", inline=True)
        embed.add_field(name="Level", value=f"`{level}`", inline=True)
        embed.add_field(name="Total XP", value=f"`{xp:,}`", inline=True)
        embed.add_field(name="Progress", value=f"`[{bar}]` `{current_xp}/{next_level_xp}`", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show the server XP leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, xp, level FROM levels WHERE guild_id = $1 ORDER BY xp DESC LIMIT 10",
                interaction.guild_id
            )

        if not rows:
            return await interaction.response.send_message("❌ No XP data yet for this server.", ephemeral=True)

        embed = discord.Embed(title="🏆 XP Leaderboard", color=0xF1C40F)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            member = interaction.guild.get_member(row["user_id"])
            name = member.display_name if member else f"User {row['user_id']}"
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{medal} **{name}** — Level {row['level']} • `{row['xp']:,} XP`")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Levels(bot))
