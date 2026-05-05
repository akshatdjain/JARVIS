import discord
from discord.ext import commands
from discord import app_commands


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: commands.Bot, ticket_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT user_id FROM tickets WHERE id = $1", self.ticket_id
                )
            if not row or row["user_id"] != interaction.user.id:
                return await interaction.response.send_message("❌ Only the ticket owner or mods can close this.", ephemeral=True)

        await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")
        import asyncio
        await asyncio.sleep(5)

        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE tickets SET closed = TRUE WHERE id = $1", self.ticket_id)

        try:
            await interaction.channel.delete(reason="Ticket closed")
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ticket", description="Open a support ticket")
    async def ticket(self, interaction: discord.Interaction, topic: str = "Support"):
        await interaction.response.defer(ephemeral=True)

        # Check if user already has an open ticket
        async with self.bot.db.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT channel_id FROM tickets WHERE user_id = $1 AND guild_id = $2 AND closed = FALSE",
                interaction.user.id, interaction.guild_id
            )

        if existing:
            ch = interaction.guild.get_channel(existing["channel_id"])
            if ch:
                return await interaction.edit_original_response(
                    content=f"❌ You already have an open ticket: {ch.mention}"
                )

        # Create private channel
        category = discord.utils.get(interaction.guild.categories, name="Tickets")
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        # Give mods access
        for role in interaction.guild.roles:
            if role.permissions.manage_messages:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=category,
            topic=f"Ticket for {interaction.user} | {topic}",
        )

        async with self.bot.db.acquire() as conn:
            ticket_id = await conn.fetchval(
                "INSERT INTO tickets (guild_id, channel_id, user_id) VALUES ($1, $2, $3) RETURNING id",
                interaction.guild_id, channel.id, interaction.user.id
            )

        embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_id}",
            description=f"**Topic:** {topic}\n\nHello {interaction.user.mention}! Support will be with you shortly.\nDescribe your issue below.",
            color=0x2ECC71,
        )
        embed.set_footer(text="Click 'Close Ticket' when resolved.")
        await channel.send(interaction.user.mention, embed=embed, view=TicketCloseView(self.bot, ticket_id))
        await interaction.edit_original_response(content=f"✅ Ticket created: {channel.mention}")



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
