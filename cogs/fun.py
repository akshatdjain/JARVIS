import random
import asyncio
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

EIGHT_BALL_RESPONSES = [
    "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes, definitely.",
    "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
    "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
    "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]


class PollView(discord.ui.View):
    def __init__(self, options: list[str], duration: int):
        super().__init__(timeout=duration)
        self.votes: dict[str, set[int]] = {opt: set() for opt in options}
        self.options = options

    def build_embed(self, title: str) -> discord.Embed:
        total = sum(len(v) for v in self.votes.values())
        embed = discord.Embed(title=f"📊 {title}", color=0x5865F2)
        for opt in self.options:
            count = len(self.votes[opt])
            pct = int((count / total * 100) if total else 0)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            embed.add_field(name=opt, value=f"`[{bar}]` {count} vote(s) ({pct}%)", inline=False)
        embed.set_footer(text=f"Total votes: {total}")
        return embed

    @discord.ui.button(label="Vote A", style=discord.ButtonStyle.primary, custom_id="vote_0")
    async def vote_0(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, 0)

    @discord.ui.button(label="Vote B", style=discord.ButtonStyle.primary, custom_id="vote_1")
    async def vote_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, 1)

    @discord.ui.button(label="Vote C", style=discord.ButtonStyle.secondary, custom_id="vote_2")
    async def vote_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, 2)

    @discord.ui.button(label="Vote D", style=discord.ButtonStyle.secondary, custom_id="vote_3")
    async def vote_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, 3)

    async def _vote(self, interaction: discord.Interaction, index: int):
        if index >= len(self.options):
            return await interaction.response.send_message("❌ Invalid option.", ephemeral=True)
        uid = interaction.user.id
        for opt_set in self.votes.values():
            opt_set.discard(uid)
        self.votes[self.options[index]].add(uid)
        await interaction.response.send_message(f"✅ Voted for **{self.options[index]}**!", ephemeral=True)
        await interaction.message.edit(embed=self.build_embed(interaction.message.embeds[0].title.replace("📊 ", "")))


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a question")
    async def eightball(self, interaction: discord.Interaction, question: str):
        response = random.choice(EIGHT_BALL_RESPONSES)
        positive = ["It is certain", "It is decidedly so", "Without a doubt", "Yes", "Most likely", "Outlook good", "Signs point to yes"]
        color = 0x2ECC71 if any(r in response for r in positive) else (0xE74C3C if "no" in response.lower() or "doubtful" in response.lower() else 0xF39C12)
        embed = discord.Embed(color=color)
        embed.add_field(name="❓ Question", value=question, inline=False)
        embed.add_field(name="🎱 Answer", value=f"*{response}*", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="coinflip", description="Flip a coin")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(["Heads 🪙", "Tails 🪙"])
        await interaction.response.send_message(f"**{result}!**")

    @app_commands.command(name="dice", description="Roll dice (e.g. 2d6)")
    async def dice(self, interaction: discord.Interaction, notation: str = "1d6"):
        try:
            parts = notation.lower().split("d")
            count = min(int(parts[0]) if parts[0] else 1, 20)
            sides = min(int(parts[1]), 1000)
        except Exception:
            return await interaction.response.send_message("❌ Use format like `2d6` or `1d20`.", ephemeral=True)
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        embed = discord.Embed(title=f"🎲 Rolled {notation}", color=0x9B59B6)
        embed.add_field(name="Rolls", value=" + ".join(f"`{r}`" for r in rolls), inline=False)
        if count > 1:
            embed.add_field(name="Total", value=f"**{total}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="meme", description="Get a random meme from Reddit")
    async def meme(self, interaction: discord.Interaction):
        await interaction.response.defer()
        subreddits = ["memes", "dankmemes", "me_irl", "shitposting"]
        sub = random.choice(subreddits)
        async with aiohttp.ClientSession(headers={"User-Agent": "JarvisBot/1.0"}) as session:
            try:
                async with session.get(f"https://www.reddit.com/r/{sub}/hot.json?limit=50", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send("❌ Reddit is down or rate-limited.")
                    data = await resp.json()
                posts = [
                    p["data"] for p in data["data"]["children"]
                    if not p["data"]["over_18"] and p["data"].get("url", "").endswith((".jpg", ".png", ".gif", ".jpeg"))
                ]
                if not posts:
                    return await interaction.followup.send("❌ No memes found right now.")
                post = random.choice(posts)
                embed = discord.Embed(title=post["title"], url=f"https://reddit.com{post['permalink']}", color=0xFF4500)
                embed.set_image(url=post["url"])
                embed.set_footer(text=f"👍 {post['ups']:,} • r/{sub}")
                await interaction.followup.send(embed=embed)
            except Exception:
                await interaction.followup.send("❌ Failed to fetch meme.")

    @app_commands.command(name="weather", description="Get the weather for a city")
    async def weather(self, interaction: discord.Interaction, city: str):
        await interaction.response.defer()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://wttr.in/{city.replace(' ', '+')}?format=j1", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(f"❌ City `{city}` not found.")
                    data = await resp.json()
            except Exception:
                return await interaction.followup.send("❌ Weather service unavailable.")

        current = data["current_condition"][0]
        area = data["nearest_area"][0]
        city_name = area["areaName"][0]["value"]
        country = area["country"][0]["value"]

        temp_c = current["temp_C"]
        temp_f = current["temp_F"]
        feels_c = current["FeelsLikeC"]
        desc = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind_kmph = current["windspeedKmph"]

        WEATHER_ICONS = {
            "Sunny": "☀️", "Clear": "🌙", "Partly cloudy": "⛅",
            "Cloudy": "☁️", "Overcast": "☁️", "Rain": "🌧️",
            "Drizzle": "🌦️", "Snow": "❄️", "Thunder": "⛈️", "Fog": "🌫️",
        }
        icon = next((v for k, v in WEATHER_ICONS.items() if k.lower() in desc.lower()), "🌡️")

        embed = discord.Embed(title=f"{icon} Weather in {city_name}, {country}", color=0x3498DB)
        embed.add_field(name="🌡️ Temperature", value=f"`{temp_c}°C / {temp_f}°F`", inline=True)
        embed.add_field(name="🤔 Feels Like", value=f"`{feels_c}°C`", inline=True)
        embed.add_field(name="💧 Humidity", value=f"`{humidity}%`", inline=True)
        embed.add_field(name="💨 Wind", value=f"`{wind_kmph} km/h`", inline=True)
        embed.add_field(name="🌤️ Condition", value=f"`{desc}`", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="poll", description="Create a quick poll (up to 4 options, comma-separated)")
    async def poll(self, interaction: discord.Interaction, question: str, options: str, duration: app_commands.Range[int, 1, 60] = 5):
        opts = [o.strip() for o in options.split(",")][:4]
        if len(opts) < 2:
            return await interaction.response.send_message("❌ Provide at least 2 comma-separated options.", ephemeral=True)

        view = PollView(opts, duration * 60)
        embed = view.build_embed(question)
        embed.set_footer(text=f"Poll ends in {duration} minute(s)")

        msg = await interaction.response.send_message(embed=embed, view=view)

        await asyncio.sleep(duration * 60)
        view.stop()
        final_embed = view.build_embed(question)
        winner = max(view.votes, key=lambda k: len(view.votes[k]))
        final_embed.add_field(name="🏆 Winner", value=f"**{winner}** with {len(view.votes[winner])} vote(s)", inline=False)
        final_embed.set_footer(text="Poll ended")
        await interaction.edit_original_response(embed=final_embed, view=None)

    @app_commands.command(name="roast", description="Get a harmless roast for someone")
    async def roast(self, interaction: discord.Interaction, user: discord.Member):
        roasts = [
            f"{user.mention} is the reason shampoo has instructions.",
            f"If {user.mention} were any more average, they'd be a median.",
            f"{user.mention} has the energy of a slow WiFi connection at 3am.",
            f"I'd roast {user.mention} but my mom said I can't burn trash.",
            f"{user.mention} is proof that even Discord lets anyone in.",
            f"{user.mention}'s voice channel quality matches their life choices.",
            f"{user.mention} tried to delete system32 to free up space for more bad takes.",
        ]
        await interaction.response.send_message(random.choice(roasts))

    @app_commands.command(name="choose", description="Let JARVIS choose between options (comma-separated)")
    async def choose(self, interaction: discord.Interaction, options: str):
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if not choices:
            return await interaction.response.send_message("❌ Provide some options!", ephemeral=True)
        await interaction.response.send_message(f"🎯 I choose: **{random.choice(choices)}**")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Fun(bot))
