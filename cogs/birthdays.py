import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


class Birthdays(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    @tasks.loop(hours=1)
    async def check_birthdays(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        if now.hour != 9:  # Run announcements at 9 AM UTC
            return

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT b.user_id, b.guild_id, g.birthday_channel_id "
                "FROM birthdays b "
                "LEFT JOIN guild_config g ON b.guild_id = g.guild_id "
                "WHERE b.birth_month = $1 AND b.birth_day = $2",
                now.month, now.day
            )

        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            member = guild.get_member(row["user_id"])
            if not member:
                continue
            channel_id = row["birthday_channel_id"]
            channel = guild.get_channel(channel_id) if channel_id else (
                guild.system_channel or next(
                    (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None
                )
            )
            if not channel:
                continue
            embed = discord.Embed(
                title="🎂 Happy Birthday!",
                description=f"It's {member.mention}'s birthday today! 🎉\nWish them a great day!",
                color=0xFF69B4,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    @check_birthdays.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="birthday", description="Set your birthday")
    @app_commands.choices(month=[app_commands.Choice(name=m, value=v) for m, v in MONTHS.items()])
    async def birthday(self, interaction: discord.Interaction, month: app_commands.Choice[int], day: app_commands.Range[int, 1, 31]):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO birthdays (user_id, guild_id, birth_month, birth_day) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET birth_month = $3, birth_day = $4",
                interaction.user.id, interaction.guild_id, month.value, day
            )
        await interaction.response.send_message(
            f"🎂 Birthday set to **{month.name} {day}**!", ephemeral=True
        )

    @app_commands.command(name="birthdaycheck", description="Check when someone's birthday is")
    async def birthdaycheck(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT birth_month, birth_day FROM birthdays WHERE user_id = $1 AND guild_id = $2",
                target.id, interaction.guild_id
            )
        if not row:
            return await interaction.response.send_message(
                f"❌ {target.display_name} hasn't set their birthday.", ephemeral=True
            )
        month_name = next(m for m, v in MONTHS.items() if v == row["birth_month"])
        await interaction.response.send_message(
            f"🎂 **{target.display_name}**'s birthday is **{month_name} {row['birth_day']}**."
        )

    @app_commands.command(name="birthdaychannel", description="Set the birthday announcement channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def birthdaychannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id, birthday_channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET birthday_channel_id = $2",
                interaction.guild_id, channel.id
            )
        await interaction.response.send_message(
            f"✅ Birthday announcements will go to {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="upcomingbirthdays", description="See upcoming birthdays in the server")
    async def upcomingbirthdays(self, interaction: discord.Interaction):
        now = datetime.datetime.now(datetime.timezone.utc)
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, birth_month, birth_day FROM birthdays WHERE guild_id = $1",
                interaction.guild_id
            )
        if not rows:
            return await interaction.response.send_message("❌ No birthdays set in this server.", ephemeral=True)

        def days_until(month: int, day: int) -> int:
            today = now.date()
            try:
                bday = datetime.date(today.year, month, day)
            except ValueError:
                return 999
            if bday < today:
                bday = datetime.date(today.year + 1, month, day)
            return (bday - today).days

        upcoming = []
        for row in rows:
            member = interaction.guild.get_member(row["user_id"])
            if not member:
                continue
            d = days_until(row["birth_month"], row["birth_day"])
            month_name = next(m for m, v in MONTHS.items() if v == row["birth_month"])
            upcoming.append((d, member.display_name, month_name, row["birth_day"]))

        upcoming.sort(key=lambda x: x[0])
        embed = discord.Embed(title="🎂 Upcoming Birthdays", color=0xFF69B4)
        for days, name, month, day in upcoming[:10]:
            label = "Today! 🎉" if days == 0 else f"In {days} day(s)"
            embed.add_field(name=f"{name}", value=f"{month} {day} — {label}", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Birthdays(bot))
