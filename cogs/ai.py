import os
import discord
from discord.ext import commands
from discord import app_commands
import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "You are JARVIS, a witty and helpful Discord bot assistant. "
    "Keep responses concise and Discord-friendly (no markdown headers, short paragraphs). "
    "Be casual, smart, and a little snarky when appropriate."
)


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else None
        self._ai_channels: dict[int, int] = {}  # guild_id -> channel_id, loaded lazily

    async def _get_ai_channel(self, guild_id: int) -> int | None:
        if guild_id not in self._ai_channels:
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow("SELECT ai_channel_id FROM guild_config WHERE guild_id = $1", guild_id)
            self._ai_channels[guild_id] = row["ai_channel_id"] if row else None
        return self._ai_channels.get(guild_id)

    async def _ask_claude(self, prompt: str, system: str = SYSTEM_PROMPT) -> str:
        if not self.client:
            return "❌ ANTHROPIC_API_KEY not configured."
        try:
            msg = await self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as e:
            return f"❌ AI error: {e}"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        ai_channel = await self._get_ai_channel(message.guild.id)
        if not ai_channel or message.channel.id != ai_channel:
            return
        if not self.client:
            return

        async with message.channel.typing():
            reply = await self._ask_claude(message.content)

        await message.reply(reply, mention_author=False)

    @app_commands.command(name="ask", description="Ask JARVIS anything")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        reply = await self._ask_claude(question)
        embed = discord.Embed(description=reply, color=0x2B2D31)
        embed.set_author(name="JARVIS AI", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_footer(text=f"Asked by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="vibe", description="Tell JARVIS your mood and get a song recommendation")
    async def vibe(self, interaction: discord.Interaction, mood: str):
        await interaction.response.defer()
        prompt = (
            f"A Discord user described their mood as: '{mood}'. "
            "Recommend exactly ONE song that fits this mood. "
            "Reply in this format only: **Song Title** by Artist Name — [one sentence why it fits]"
        )
        reply = await self._ask_claude(prompt)
        embed = discord.Embed(title="🎵 Vibe Check", description=reply, color=0x1DB954)
        embed.set_footer(text=f"Mood: {mood}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="tldr", description="Summarize a long piece of text")
    async def tldr(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer()
        prompt = f"Summarize this in 2-3 bullet points, Discord-friendly, no fluff:\n\n{text}"
        reply = await self._ask_claude(prompt)
        embed = discord.Embed(title="📝 TL;DR", description=reply, color=0x2B2D31)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="aichannel", description="Set the channel where JARVIS auto-replies to messages")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aichannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id, ai_channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET ai_channel_id = $2",
                interaction.guild_id, channel.id
            )
        self._ai_channels[interaction.guild_id] = channel.id
        await interaction.response.send_message(
            f"✅ JARVIS will now auto-reply in {channel.mention}.", ephemeral=True
        )



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI(bot))
