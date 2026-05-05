import discord
from discord.ext import commands
from discord import app_commands
import asyncio

COLORS = {
    "Red":     0xE74C3C,
    "Orange":  0xE67E22,
    "Yellow":  0xF1C40F,
    "Green":   0x2ECC71,
    "Cyan":    0x1ABC9C,
    "Blue":    0x3498DB,
    "Purple":  0x9B59B6,
    "Pink":    0xFF69B4,
    "White":   0xFFFFFF,
    "Black":   0x2C2F33,
}

LEVEL_ROLE_THRESHOLDS = [
    (5,  "Level 5"),
    (10, "Level 10"),
    (20, "Level 20"),
    (30, "Level 30"),
    (50, "Level 50"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS role_menus (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    menu_type TEXT DEFAULT 'custom'
);
CREATE TABLE IF NOT EXISTS role_menu_items (
    id SERIAL PRIMARY KEY,
    menu_id INTEGER REFERENCES role_menus(id) ON DELETE CASCADE,
    role_id BIGINT,
    label TEXT,
    emoji TEXT,
    description TEXT
);
"""


class RoleMenuView(discord.ui.View):
    def __init__(self, items: list[dict]):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(
                label=item["label"],
                value=str(item["role_id"]),
                emoji=item.get("emoji"),
                description=item.get("description", ""),
            )
            for item in items
        ]
        select = discord.ui.Select(
            placeholder="Pick a role...",
            min_values=0,
            max_values=min(len(options), 25),
            options=options,
            custom_id="role_menu_select",
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        selected_ids = {int(v) for v in interaction.data["values"]}
        guild = interaction.guild
        member = interaction.user

        # Collect all role IDs in this menu
        all_menu_ids = {int(o.value) for o in self.children[0].options}

        to_add = [guild.get_role(rid) for rid in selected_ids if guild.get_role(rid)]
        to_remove = [guild.get_role(rid) for rid in (all_menu_ids - selected_ids) if guild.get_role(rid) and guild.get_role(rid) in member.roles]

        try:
            if to_add:
                await member.add_roles(*to_add, reason="Role menu")
            if to_remove:
                await member.remove_roles(*to_remove, reason="Role menu")
            added = ", ".join(r.name for r in to_add) or "none"
            removed = ", ".join(r.name for r in to_remove) or "none"
            await interaction.response.send_message(
                f"✅ Added: **{added}** | Removed: **{removed}**", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ Missing permissions to assign roles.", ephemeral=True)


class ColorRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(label=name, value=name, emoji="🎨")
            for name in COLORS
        ]
        select = discord.ui.Select(
            placeholder="Pick your color...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="color_role_select",
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        chosen = interaction.data["values"][0]
        guild = interaction.guild
        member = interaction.user

        # Remove any existing color roles
        color_role_names = set(COLORS.keys())
        to_remove = [r for r in member.roles if r.name in color_role_names]
        if to_remove:
            await member.remove_roles(*to_remove, reason="Color role change")

        # Get or create the color role
        role = discord.utils.get(guild.roles, name=chosen)
        if not role:
            role = await guild.create_role(
                name=chosen,
                color=discord.Color(COLORS[chosen]),
                reason="Color role auto-created",
            )
        await member.add_roles(role, reason="Color role selection")
        await interaction.response.send_message(f"🎨 Color set to **{chosen}**!", ephemeral=True)


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._init_db())

    async def _init_db(self):
        await self.bot.wait_until_ready()
        async with self.bot.db.acquire() as conn:
            await conn.execute(SCHEMA)

    # ── Level role assignment (called from levels cog on level up) ─────────────
    async def assign_level_role(self, member: discord.Member, new_level: int):
        guild = member.guild
        for threshold, role_name in LEVEL_ROLE_THRESHOLDS:
            if new_level >= threshold:
                role = discord.utils.get(guild.roles, name=role_name)
                if not role:
                    role = await guild.create_role(
                        name=role_name,
                        color=discord.Color.gold(),
                        reason="Level role auto-created",
                    )
                if role not in member.roles:
                    await member.add_roles(role, reason=f"Reached level {threshold}")

    # ── /colormenu ─────────────────────────────────────────────────────────────
    @app_commands.command(name="colormenu", description="Post the color picker role menu")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def colormenu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎨 Pick Your Color",
            description="Select a color role from the dropdown below.\nYour previous color will be removed automatically.",
            color=0x2B2D31,
        )
        await interaction.channel.send(embed=embed, view=ColorRoleView())
        await interaction.response.send_message("✅ Color menu posted.", ephemeral=True)

    # ── /rolesmenu ─────────────────────────────────────────────────────────────
    @app_commands.command(name="rolesmenu", description="Post a role picker menu in this channel")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rolesmenu(self, interaction: discord.Interaction, title: str, description: str = "Pick your roles below."):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(title=title, description=description, color=0x5865F2)
        msg = await interaction.channel.send(embed=embed, view=discord.ui.View())  # placeholder

        async with self.bot.db.acquire() as conn:
            menu_id = await conn.fetchval(
                "INSERT INTO role_menus (guild_id, channel_id, message_id) VALUES ($1, $2, $3) RETURNING id",
                interaction.guild_id, interaction.channel_id, msg.id
            )

        await interaction.edit_original_response(
            content=f"✅ Role menu created (ID: `{menu_id}`). Use `/roleadd {menu_id} @role Label` to add roles to it."
        )

    # ── /roleadd ───────────────────────────────────────────────────────────────
    @app_commands.command(name="roleadd", description="Add a role option to a role menu")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def roleadd(self, interaction: discord.Interaction, menu_id: int, role: discord.Role, label: str, emoji: str = None, description: str = None):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.acquire() as conn:
            menu = await conn.fetchrow("SELECT * FROM role_menus WHERE id = $1 AND guild_id = $2", menu_id, interaction.guild_id)
            if not menu:
                return await interaction.edit_original_response(content="❌ Menu not found.")

            await conn.execute(
                "INSERT INTO role_menu_items (menu_id, role_id, label, emoji, description) VALUES ($1, $2, $3, $4, $5)",
                menu_id, role.id, label, emoji, description
            )
            items = await conn.fetch("SELECT * FROM role_menu_items WHERE menu_id = $1", menu_id)

        # Rebuild the menu message
        channel = interaction.guild.get_channel(menu["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(menu["message_id"])
                item_dicts = [dict(i) for i in items]
                await msg.edit(view=RoleMenuView(item_dicts))
            except discord.HTTPException:
                pass

        await interaction.edit_original_response(content=f"✅ Added **{role.name}** to menu `{menu_id}`.")



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roles(bot))
