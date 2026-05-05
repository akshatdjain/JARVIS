import re
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

CONFIG_PATH = "/app/lavalink_config.yml"


class YTRefresh(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="refreshyt", description="Update YouTube visitorData token and restart Lavalink (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def refreshyt(self, interaction: discord.Interaction, visitor_data: str):
        await interaction.response.defer(ephemeral=True)

        # Read current config
        try:
            with open(CONFIG_PATH, "r") as f:
                config = f.read()
        except FileNotFoundError:
            return await interaction.edit_original_response(
                content="❌ Lavalink config file not found at expected path."
            )

        # Replace or insert visitorData
        visitor_data = visitor_data.strip().strip('"')
        if 'visitorData:' in config:
            config = re.sub(
                r'visitorData:\s*"[^"]*"',
                f'visitorData: "{visitor_data}"',
                config
            )
        else:
            # Insert under pot: section or create it
            if 'pot:' in config:
                config = re.sub(
                    r'(pot:\s*\n)',
                    f'pot:\n      visitorData: "{visitor_data}"\n',
                    config
                )
            else:
                config = config.replace(
                    '    clients:',
                    f'    pot:\n      visitorData: "{visitor_data}"\n    clients:'
                )

        # Write updated config
        try:
            with open(CONFIG_PATH, "w") as f:
                f.write(config)
        except Exception as e:
            return await interaction.edit_original_response(content=f"❌ Failed to write config: {e}")

        # Restart Lavalink via Docker CLI
        await interaction.edit_original_response(content="⏳ Config updated. Restarting Lavalink...")
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "restart", "lavalink",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return await interaction.edit_original_response(
                    content=f"❌ Docker restart failed: {stderr.decode()}"
                )
        except FileNotFoundError:
            return await interaction.edit_original_response(
                content="❌ Docker CLI not found in container. Check docker.sock mount."
            )
        except asyncio.TimeoutError:
            return await interaction.edit_original_response(content="❌ Restart timed out.")

        # Wait for Lavalink to come back up
        await interaction.edit_original_response(content="⏳ Lavalink restarting, waiting for it to come online...")
        await asyncio.sleep(20)

        await interaction.edit_original_response(
            content="✅ visitorData updated and Lavalink restarted! YouTube should be unblocked again.\n"
                    f"Token preview: `{visitor_data[:30]}...`"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(YTRefresh(bot))
