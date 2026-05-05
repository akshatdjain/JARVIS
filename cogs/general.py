import discord
from discord.ext import commands
from discord import app_commands
import os


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        color = 0x2ECC71 if latency < 100 else (0xF39C12 if latency < 200 else 0xE74C3C)
        embed = discord.Embed(title="🏓 Pong!", description=f"Latency: **{latency}ms**", color=color)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Show server information")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        embed = discord.Embed(title=g.name, color=0x2B2D31)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Owner", value=g.owner.mention if g.owner else "Unknown", inline=True)
        embed.add_field(name="Members", value=f"`{g.member_count}`", inline=True)
        embed.add_field(name="Channels", value=f"`{len(g.channels)}`", inline=True)
        embed.add_field(name="Roles", value=f"`{len(g.roles)}`", inline=True)
        embed.add_field(name="Boosts", value=f"`{g.premium_subscription_count}` (Tier {g.premium_tier})", inline=True)
        ts = int(g.created_at.timestamp())
        embed.add_field(name="Created", value=f"<t:{ts}:D>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Show info about a user")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=str(target), color=target.color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="Nickname", value=target.nick or "None", inline=True)
        ts_joined = int(target.joined_at.timestamp()) if target.joined_at else 0
        ts_created = int(target.created_at.timestamp())
        embed.add_field(name="Joined Server", value=f"<t:{ts_joined}:D>", inline=True)
        embed.add_field(name="Account Created", value=f"<t:{ts_created}:D>", inline=True)
        roles = [r.mention for r in reversed(target.roles[1:])][:10]
        embed.add_field(name=f"Roles ({len(target.roles)-1})", value=" ".join(roles) or "None", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Get a user's avatar")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=f"{target.display_name}'s Avatar", color=0x2B2D31)
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="invite", description="Get the bot's invite link")
    async def invite(self, interaction: discord.Interaction):
        import os
        client_id = os.getenv("CLIENT_ID", str(self.bot.user.id))
        url = f"https://discord.com/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot%20applications.commands"
        embed = discord.Embed(title="➕ Invite JARVIS", description=f"[Click here to add JARVIS to your server]({url})", color=0x5865F2)
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("SELECT welcome_channel_id FROM guild_config WHERE guild_id = $1", member.guild.id)

        channel_id = row["welcome_channel_id"] if row else None
        channel = (
            member.guild.get_channel(channel_id) if channel_id
            else member.guild.system_channel
            or next((c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages), None)
        )
        if not channel:
            return

        embed = discord.Embed(
            title=f"Welcome, {member.name}!",
            description=f"Glad to have you in **{member.guild.name}**! Use `/help` to see what I can do.",
            color=0x1DB954,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        embed.timestamp = discord.utils.utcnow()
        await channel.send(member.mention, embed=embed)

    @app_commands.command(name="setwelcome", description="Set the welcome message channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcome(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id, welcome_channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET welcome_channel_id = $2",
                interaction.guild_id, channel.id
            )
        await interaction.response.send_message(f"✅ Welcome messages will go to {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
