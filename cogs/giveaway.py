import re
import random
import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands

GIVEAWAY_EMOJI = "🎉"

TIME_UNITS = {
    "s": 1, "m": 60, "h": 3600, "d": 86400,
    "sec": 1, "min": 60, "hr": 3600, "day": 86400,
    "second": 1, "minute": 60, "hour": 3600,
    "seconds": 1, "minutes": 60, "hours": 3600, "days": 86400,
}


def parse_duration(text: str) -> int | None:
    pattern = r"(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours|d|day|days)"
    matches = re.findall(pattern, text.lower())
    if not matches:
        return None
    return sum(int(n) * TIME_UNITS[u] for n, u in matches)


def giveaway_embed(prize: str, ends_at: datetime.datetime, winners: int, ended: bool = False) -> discord.Embed:
    ts = int(ends_at.timestamp())
    color = 0xF1C40F if not ended else 0x95A5A6
    embed = discord.Embed(title=f"{GIVEAWAY_EMOJI} Giveaway", description=f"**{prize}**", color=color)
    embed.add_field(name="Winners", value=f"`{winners}`", inline=True)
    if not ended:
        embed.add_field(name="Ends", value=f"<t:{ts}:R>", inline=True)
        embed.set_footer(text=f"React with {GIVEAWAY_EMOJI} to enter!")
    else:
        embed.add_field(name="Ended", value=f"<t:{ts}:R>", inline=True)
        embed.set_footer(text="Giveaway ended.")
    return embed


class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, guild_id, channel_id, message_id, prize, ends_at, winner_count "
                "FROM giveaways WHERE ended = FALSE AND ends_at <= NOW()"
            )
            for row in rows:
                await self._end_giveaway(
                    row["id"], row["guild_id"], row["channel_id"],
                    row["message_id"], row["prize"], row["ends_at"], row["winner_count"]
                )
                await conn.execute("UPDATE giveaways SET ended = TRUE WHERE id = $1", row["id"])

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _end_giveaway(self, gid, guild_id, channel_id, message_id, prize, ends_at, winner_count):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return

        reaction = discord.utils.get(message.reactions, emoji=GIVEAWAY_EMOJI)
        entrants = []
        if reaction:
            async for user in reaction.users():
                if not user.bot:
                    entrants.append(user)

        embed = giveaway_embed(prize, ends_at, winner_count, ended=True)

        if not entrants:
            embed.add_field(name="Result", value="No valid entries.", inline=False)
            await message.edit(embed=embed)
            await channel.send(f"🎉 Giveaway for **{prize}** ended with no entries.")
            return

        winners = random.sample(entrants, min(winner_count, len(entrants)))
        winner_mentions = ", ".join(w.mention for w in winners)
        embed.add_field(name="🏆 Winner(s)", value=winner_mentions, inline=False)
        await message.edit(embed=embed)
        await channel.send(f"🎉 Congratulations {winner_mentions}! You won **{prize}**!")

    @app_commands.command(name="giveaway", description="Start a giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: app_commands.Range[int, 1, 10] = 1,
        channel: discord.TextChannel = None,
    ):
        seconds = parse_duration(duration)
        if not seconds:
            return await interaction.response.send_message("❌ Invalid duration. Example: `1h`, `30m`, `2d`", ephemeral=True)

        target = channel or interaction.channel
        ends_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
        embed = giveaway_embed(prize, ends_at, winners)
        msg = await target.send(embed=embed)
        await msg.add_reaction(GIVEAWAY_EMOJI)

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, ends_at, winner_count) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                interaction.guild_id, target.id, msg.id, prize, ends_at, winners
            )

        await interaction.response.send_message(f"✅ Giveaway started in {target.mention}!", ephemeral=True)

    @app_commands.command(name="reroll", description="Reroll a giveaway winner")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reroll(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer()
        try:
            msg = await interaction.channel.fetch_message(int(message_id))
        except Exception:
            return await interaction.followup.send("❌ Message not found in this channel.")

        reaction = discord.utils.get(msg.reactions, emoji=GIVEAWAY_EMOJI)
        if not reaction:
            return await interaction.followup.send("❌ No giveaway reaction found.")

        entrants = [u async for u in reaction.users() if not u.bot]
        if not entrants:
            return await interaction.followup.send("❌ No valid entries to reroll.")

        winner = random.choice(entrants)
        await interaction.followup.send(f"🎉 Rerolled! New winner: {winner.mention}!")

    @app_commands.command(name="giveawayend", description="End a giveaway early by message ID")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveawayend(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, channel_id, prize, ends_at, winner_count FROM giveaways "
                "WHERE message_id = $1 AND guild_id = $2 AND ended = FALSE",
                int(message_id), interaction.guild_id
            )
        if not row:
            return await interaction.followup.send("❌ Active giveaway not found.")
        await self._end_giveaway(
            row["id"], interaction.guild_id, row["channel_id"],
            int(message_id), row["prize"], row["ends_at"], row["winner_count"]
        )
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE giveaways SET ended = TRUE WHERE id = $1", row["id"])
        await interaction.followup.send("✅ Giveaway ended.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaway(bot))
