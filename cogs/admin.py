"""
/admin — guild-only subcommand group for server administration.
Replaces: setup, cleanup, refreshyt, addcoins, reveal
"""
import re
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

CONFIG_PATH = "/app/lavalink_config.yml"


class AdminGroup(app_commands.Group):
    """Server administration commands — server owner only."""

    # Lock the entire group to administrator permission — no exceptions
    default_permissions = discord.Permissions(administrator=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != interaction.guild.owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("This command is restricted to server administrators.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="setup", description="Build the full server channel structure")
    async def setup(self, interaction: discord.Interaction):
        # Delegate to the setup cog's logic
        setup_cog = interaction.client.cogs.get("Setup")
        if setup_cog:
            await setup_cog.setup.callback(setup_cog, interaction)
        else:
            await interaction.response.send_message("Setup cog not loaded.", ephemeral=True)

    @app_commands.command(name="cleanup", description="Delete old channels before running setup")
    async def cleanup(self, interaction: discord.Interaction):
        setup_cog = interaction.client.cogs.get("Setup")
        if setup_cog:
            await setup_cog.cleanup.callback(setup_cog, interaction)
        else:
            await interaction.response.send_message("Setup cog not loaded.", ephemeral=True)

    @app_commands.command(name="refreshyt", description="Update YouTube visitorData and restart Lavalink")
    @app_commands.describe(visitor_data="Paste the x-goog-visitor-id header value from YouTube DevTools")
    async def refreshyt(self, interaction: discord.Interaction, visitor_data: str):
        await interaction.response.defer(ephemeral=True)
        visitor_data = visitor_data.strip().strip('"')
        try:
            with open(CONFIG_PATH, "r") as f:
                config = f.read()
        except FileNotFoundError:
            return await interaction.edit_original_response(content="Config file not found.")

        if 'visitorData:' in config:
            config = re.sub(r'visitorData:\s*"[^"]*"', f'visitorData: "{visitor_data}"', config)
        else:
            config = config.replace('    clients:', f'    pot:\n      visitorData: "{visitor_data}"\n    clients:')

        with open(CONFIG_PATH, "w") as f:
            f.write(config)

        await interaction.edit_original_response(content="Config updated. Restarting Lavalink...")
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "restart", "lavalink",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as e:
            return await interaction.edit_original_response(content=f"Restart failed: {e}")

        await asyncio.sleep(20)
        await interaction.edit_original_response(
            content=f"Done. visitorData updated. Token: `{visitor_data[:30]}...`"
        )

    @app_commands.command(name="addcoins", description="Give coins to a user")
    @app_commands.describe(user="Member to give coins to", amount="Amount of coins")
    async def addcoins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO economy (user_id, guild_id, coins) VALUES ($1, $2, $3) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET coins = economy.coins + $3",
                user.id, interaction.guild_id, amount
            )
            new_bal = await conn.fetchval(
                "SELECT coins FROM economy WHERE user_id = $1 AND guild_id = $2",
                user.id, interaction.guild_id
            )
        await interaction.response.send_message(
            f"Gave **{amount:,} coins** to {user.mention}. New balance: **{new_bal:,}**.", ephemeral=True
        )

    @app_commands.command(name="reveal", description="Reveal who posted an anonymous confession")
    @app_commands.describe(receipt_id="The receipt ID the user received after posting")
    async def reveal(self, interaction: discord.Interaction, receipt_id: str):
        async with interaction.client.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, id FROM confessions WHERE receipt_id = $1 AND guild_id = $2",
                receipt_id.upper(), interaction.guild_id
            )
        if not row:
            return await interaction.response.send_message("Receipt not found.", ephemeral=True)
        user = interaction.guild.get_member(row["user_id"])
        name = str(user) if user else f"Unknown (ID: {row['user_id']})"
        await interaction.response.send_message(
            f"Confession #{row['id']} was posted by **{name}**", ephemeral=True
        )


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.admin_group = AdminGroup(name="admin", description="Server administration")
        bot.tree.add_command(self.admin_group)

    async def cog_unload(self):
        self.bot.tree.remove_command("admin")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
