import discord
from discord.ext import commands, tasks
from discord import app_commands

# Full channel layout
CATEGORIES = [
    {
        "name": "📋 INFO",
        "channels": [
            {"name": "📌・rules",         "type": "text", "topic": "Server rules. Read before anything else."},
            {"name": "📣・announcements",  "type": "text", "topic": "Official server announcements.", "no_send": True},
            {"name": "🔄・changelog",      "type": "text", "topic": "Bot updates and server changes.", "no_send": True},
            {"name": "🎭・roles",          "type": "text", "topic": "Pick your roles here."},
        ],
    },
    {
        "name": "🎮 COMMUNITY",
        "channels": [
            {"name": "💬・general",        "type": "text", "topic": "General chat — anything goes."},
            {"name": "🔥・hot-takes",      "type": "text", "topic": "Drop your spiciest opinions."},
            {"name": "🤫・confessions",    "type": "text", "topic": "Anonymous confessions. Use /confess", "no_send": True},
            {"name": "⭐・starboard",      "type": "text", "topic": "Hall of fame — messages with enough ⭐ land here.", "no_send": True},
            {"name": "🔢・counting",       "type": "text", "topic": "Count as high as possible. One number per message. Don't mess up."},
            {"name": "📸・media",          "type": "text", "topic": "Images and videos only."},
        ],
    },
    {
        "name": "🎵 MUSIC",
        "channels": [
            {"name": "🎧・music-commands", "type": "text", "topic": "Use music commands here. /play /skip /queue etc."},
            {"name": "🔊 mujikk",          "type": "voice"},
        ],
    },
    {
        "name": "🎲 GAMES",
        "channels": [
            {"name": "🎮・game-commands",  "type": "text", "topic": "Play games here. /trivia /wordle /ttt etc."},
            {"name": "🏆・leaderboard",    "type": "text", "topic": "Server leaderboards.", "no_send": True},
        ],
    },
    {
        "name": "🎥 STREAM",
        "channels": [
            {"name": "📺・stream-chat",    "type": "text", "topic": "Chat while watching. Use /stream to find content on Hotstar or YouTube."},
            {"name": "🎥 stream",          "type": "voice"},
        ],
    },
    {
        "name": "💰 ECONOMY",
        "channels": [
            {"name": "🏪・shop-chat",      "type": "text", "topic": "Use /shop /buy /slots /blackjack /balance here."},
            {"name": "💵・economy-log",    "type": "text", "topic": "Big wins and economy events.", "no_send": True},
        ],
    },
    {
        "name": "🔒 PRIVATE",
        "channels": [
            {"name": "💬・vip-lounge",     "type": "text", "topic": "VIP lounge — boosters and OGs only.", "vip_only": True},
            {"name": "🔊 vip-vc",          "type": "voice", "vip_only": True},
        ],
    },
    {
        "name": "📢 SOCIAL",
        "channels": [
            {"name": "🤖・bot-commands",   "type": "text", "topic": "Use bot commands here. Keep general clean."},
        ],
    },
    {
        "name": "🎫 SUPPORT",
        "channels": [
            {"name": "📬・open-a-ticket",  "type": "text", "topic": "Need help? Use /ticket to open a private support channel."},
        ],
    },
]

STAT_CATEGORY = "📊 SERVER STATS"
STAT_CHANNELS = [
    {"key": "members", "label": "👥 Members: {count}"},
    {"key": "bots",    "label": "🤖 Bots: {count}"},
    {"key": "boosts",  "label": "🚀 Boosts: {count}"},
]


async def _get_or_create_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    cat = discord.utils.get(guild.categories, name=name)
    if not cat:
        cat = await guild.create_category(name)
    return cat


class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_stats.start()

    def cog_unload(self):
        self.update_stats.cancel()

    # ── /setup ────────────────────────────────────────────────────────────────
    @app_commands.command(name="setup", description="Build the full server channel structure (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        created, skipped = 0, 0

        everyone = guild.default_role
        bot_member = guild.me

        for cat_data in CATEGORIES:
            cat = await _get_or_create_category(guild, cat_data["name"])

            for ch_data in cat_data["channels"]:
                existing = discord.utils.get(guild.channels, name=ch_data["name"])
                if existing:
                    skipped += 1
                    continue

                if ch_data.get("vip_only"):
                    # Hidden from @everyone, visible to OG/Booster roles and admins
                    vip_role = discord.utils.get(guild.roles, name="OG")
                    booster_role = guild.premium_subscriber_role
                    overwrites = {
                        everyone: discord.PermissionOverwrite(view_channel=False),
                        bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True),
                    }
                    if vip_role:
                        overwrites[vip_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)
                    if booster_role:
                        overwrites[booster_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)
                else:
                    overwrites = {
                        everyone: discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=not ch_data.get("no_send", False),
                            add_reactions=True,
                        ),
                        bot_member: discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            manage_messages=True,
                            manage_channels=True,
                        ),
                    }

                if ch_data["type"] == "text":
                    await guild.create_text_channel(
                        ch_data["name"],
                        category=cat,
                        topic=ch_data.get("topic", ""),
                        overwrites=overwrites,
                    )
                else:
                    vc_overwrites = overwrites if ch_data.get("vip_only") else {
                        everyone: discord.PermissionOverwrite(view_channel=True, connect=True),
                        bot_member: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
                    }
                    await guild.create_voice_channel(
                        ch_data["name"],
                        category=cat,
                        overwrites=vc_overwrites,
                    )
                created += 1

        # Stats category — read-only VCs
        stats_cat = await _get_or_create_category(guild, STAT_CATEGORY)
        stat_overwrites = {
            everyone: discord.PermissionOverwrite(view_channel=True, connect=False),
            bot_member: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
        }

        for stat in STAT_CHANNELS:
            label = self._stat_label(guild, stat)
            existing = discord.utils.get(stats_cat.voice_channels, name__startswith=stat["label"].split(":")[0].strip())
            if not existing:
                await guild.create_voice_channel(label, category=stats_cat, overwrites=stat_overwrites)
                created += 1
            else:
                skipped += 1

        await interaction.edit_original_response(
            content=f"✅ Server setup complete! Created **{created}** channels, skipped **{skipped}** existing."
        )

    # ── /cleanup — delete old uncategorised channels before running /setup ──────
    @app_commands.command(name="cleanup", description="Delete old channels not in the new layout (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Names of legacy channels/VCs to delete
        LEGACY_NAMES = {
            # text
            "general", "games", "music", "watch",
            # voice
            "lounge", "stream room", "watch",
        }

        # Build the set of channel names that belong to the new layout
        NEW_NAMES = set()
        for cat in CATEGORIES:
            for ch in cat["channels"]:
                NEW_NAMES.add(ch["name"].lower())
        for stat in STAT_CHANNELS:
            NEW_NAMES.add(stat["label"].split(":")[0].strip().lower())

        deleted = []
        skipped = []

        for ch in list(guild.channels):
            name_lower = ch.name.lower().strip()
            # Only touch channels that are in the legacy list AND not in the new layout
            if name_lower in LEGACY_NAMES and name_lower not in NEW_NAMES:
                # Skip if it's already inside one of our new categories
                if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                    if ch.category and ch.category.name in [c["name"] for c in CATEGORIES] + [STAT_CATEGORY]:
                        skipped.append(ch.name)
                        continue
                try:
                    await ch.delete(reason="Cleanup before /setup")
                    deleted.append(ch.name)
                except discord.HTTPException:
                    skipped.append(ch.name)

        # Also delete empty legacy categories (Text Channels, Voice Channels)
        LEGACY_CATS = {"text channels", "voice channels"}
        for cat in list(guild.categories):
            if cat.name.lower() in LEGACY_CATS and len(cat.channels) == 0:
                try:
                    await cat.delete(reason="Cleanup legacy category")
                    deleted.append(f"[category] {cat.name}")
                except discord.HTTPException:
                    pass

        msg = f"Deleted **{len(deleted)}** channels: {', '.join(f'`{n}`' for n in deleted) or 'none'}"
        if skipped:
            msg += f"\nSkipped: {', '.join(f'`{n}`' for n in skipped)}"
        msg += "\n\nNow run `/setup` to build the new layout."
        await interaction.edit_original_response(content=msg)

    def _stat_label(self, guild: discord.Guild, stat: dict) -> str:
        if stat["key"] == "members":
            count = sum(1 for m in guild.members if not m.bot)
        elif stat["key"] == "bots":
            count = sum(1 for m in guild.members if m.bot)
        else:
            count = guild.premium_subscription_count
        return stat["label"].format(count=count)

    # ── Stat VC updater ───────────────────────────────────────────────────────
    @tasks.loop(minutes=10)
    async def update_stats(self):
        for guild in self.bot.guilds:
            stats_cat = discord.utils.get(guild.categories, name=STAT_CATEGORY)
            if not stats_cat:
                continue
            for stat in STAT_CHANNELS:
                prefix = stat["label"].split(":")[0].strip()
                vc = discord.utils.find(lambda c, p=prefix: c.name.startswith(p), stats_cat.voice_channels)
                if vc:
                    new_name = self._stat_label(guild, stat)
                    if vc.name != new_name:
                        try:
                            await vc.edit(name=new_name)
                        except discord.HTTPException:
                            pass

    @update_stats.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Setup(bot))
