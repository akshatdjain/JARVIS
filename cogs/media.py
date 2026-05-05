import urllib.parse
import discord
from discord.ext import commands
from discord import app_commands


class WatchView(discord.ui.View):
    def __init__(self, movie_name: str):
        super().__init__(timeout=None)
        query = urllib.parse.quote(movie_name)
        slug = query.replace("%20", "-")

        self.add_item(discord.ui.Button(
            label="Hotstar", url=f"https://www.hotstar.com/in/explore?search_query={query}", style=discord.ButtonStyle.link,
        ))
        self.add_item(discord.ui.Button(
            label="Movies2Watch", url=f"https://movies2watch.tv/search/{slug}", style=discord.ButtonStyle.link,
        ))
        self.add_item(discord.ui.Button(
            label="JustWatch", url=f"https://www.justwatch.com/in/search?q={query}", style=discord.ButtonStyle.link,
        ))


class Media(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="watch", description="Search for a movie or series to watch")
    async def watch(self, interaction: discord.Interaction, query: str):
        embed = discord.Embed(
            title="🎥 Movie / Series Search",
            description=f"Searching for: **{query}**",
            color=0xE50914,
        )
        embed.set_author(name="JARVIS Media", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.add_field(name="Platforms", value="Click the buttons below to search streaming platforms.", inline=False)
        embed.set_footer(text="Active subscription required for official platforms.")
        await interaction.response.send_message(embed=embed, view=WatchView(query))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Media(bot))
