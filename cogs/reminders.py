import re
import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands

TIME_UNITS = {
    "s": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}


def parse_duration(text: str) -> int | None:
    pattern = r"(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours|d|day|days)"
    matches = re.findall(pattern, text.lower())
    if not matches:
        return None
    total = sum(int(num) * TIME_UNITS[unit] for num, unit in matches)
    return total if total > 0 else None


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, user_id, channel_id, message FROM reminders WHERE remind_at <= NOW()"
            )
            if not rows:
                return
            for row in rows:
                channel = self.bot.get_channel(row["channel_id"])
                if channel:
                    try:
                        embed = discord.Embed(
                            title="⏰ Reminder!",
                            description=row["message"],
                            color=0xE67E22,
                        )
                        await channel.send(f"<@{row['user_id']}>", embed=embed)
                    except discord.HTTPException:
                        pass
            ids = [row["id"] for row in rows]
            await conn.execute("DELETE FROM reminders WHERE id = ANY($1)", ids)

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="remind", description="Set a reminder (e.g. 2h 30m, 1d)")
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        seconds = parse_duration(time)
        if not seconds:
            return await interaction.response.send_message(
                "❌ Invalid time format. Examples: `30m`, `2h`, `1d`, `1h 30m`", ephemeral=True
            )
        if seconds > 86400 * 30:
            return await interaction.response.send_message("❌ Max reminder time is 30 days.", ephemeral=True)

        remind_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO reminders (user_id, channel_id, message, remind_at) VALUES ($1, $2, $3, $4)",
                interaction.user.id, interaction.channel_id, message, remind_at
            )

        ts = int(remind_at.timestamp())
        embed = discord.Embed(
            title="⏰ Reminder Set",
            description=f"I'll remind you: **{message}**",
            color=0xE67E22,
        )
        embed.add_field(name="When", value=f"<t:{ts}:R> (<t:{ts}:f>)")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reminders", description="List your active reminders")
    async def list_reminders(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, message, remind_at FROM reminders WHERE user_id = $1 ORDER BY remind_at ASC LIMIT 10",
                interaction.user.id
            )
        if not rows:
            return await interaction.response.send_message("❌ You have no active reminders.", ephemeral=True)

        embed = discord.Embed(title="⏰ Your Reminders", color=0xE67E22)
        for row in rows:
            ts = int(row["remind_at"].timestamp())
            embed.add_field(
                name=f"ID #{row['id']}",
                value=f"{row['message']}\n<t:{ts}:R>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remindcancel", description="Cancel a reminder by ID")
    async def cancel_reminder(self, interaction: discord.Interaction, reminder_id: int):
        async with self.bot.db.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM reminders WHERE id = $1 AND user_id = $2",
                reminder_id, interaction.user.id
            )
        if result == "DELETE 0":
            return await interaction.response.send_message("❌ Reminder not found or not yours.", ephemeral=True)
        await interaction.response.send_message(f"✅ Reminder `#{reminder_id}` cancelled.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
