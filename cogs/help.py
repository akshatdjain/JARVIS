import discord
from discord.ext import commands
from discord import app_commands

EVERYONE_COMMANDS = {
    "Music": [
        ("/play <query>", "Play from YouTube, SoundCloud, or Spotify"),
        ("/skip", "Skip current track"),
        ("/pause", "Pause or resume"),
        ("/queue", "Show the queue"),
        ("/nowplaying", "Current track info"),
        ("/volume <0-100>", "Set volume"),
        ("/seek <seconds>", "Jump to position"),
        ("/loop <off/track/queue>", "Loop mode"),
        ("/shuffle", "Shuffle the queue"),
        ("/lyrics", "Get lyrics"),
        ("/filter <preset>", "Audio filters (bassboost, 8d, nightcore...)"),
    ],
    "Games": [
        ("/trivia", "Answer a trivia question, earn XP"),
        ("/wordle", "Start a Wordle game (private)"),
        ("/wordleguess <word>", "Guess in your Wordle game"),
        ("/hangman", "Start hangman in this channel"),
        ("/guess <letter>", "Guess a letter in hangman"),
        ("/ttt @user", "Challenge someone to Tic Tac Toe"),
        ("/wyr", "Would You Rather"),
        ("/tod <truth/dare>", "Truth or Dare"),
    ],
    "Economy": [
        ("/balance", "Check your coin balance"),
        ("/daily", "Claim 200 coins every 24h"),
        ("/pay @user <amount>", "Transfer coins"),
        ("/slots <bet>", "Spin the slots"),
        ("/blackjack <bet>", "Play blackjack"),
        ("/shop", "Browse the role shop"),
        ("/buy <id>", "Buy a shop item"),
        ("/ecoleaderboard", "Top coin holders"),
    ],
    "Levels": [
        ("/rank", "Your XP rank card"),
        ("/leaderboard", "Server XP leaderboard"),
    ],
    "Fun": [
        ("/8ball <question>", "Ask the magic 8-ball"),
        ("/coinflip", "Flip a coin"),
        ("/dice <2d6>", "Roll dice"),
        ("/meme", "Random meme from Reddit"),
        ("/weather <city>", "Current weather"),
        ("/poll <q> <A,B,C>", "Create a timed poll"),
        ("/roast @user", "Harmless roast"),
        ("/choose <a,b,c>", "Let the bot decide"),
    ],
    "Utility": [
        ("/afk <reason>", "Set AFK status"),
        ("/remind <time> <msg>", "Set a reminder"),
        ("/reminders", "List your reminders"),
        ("/spotify @user", "See what someone is listening to"),
        ("/ticket <topic>", "Open a support ticket"),
        ("/confess <msg>", "Post an anonymous confession"),
    ],
    "General": [
        ("/ping", "Bot latency"),
        ("/serverinfo", "Server stats"),
        ("/userinfo", "User profile"),
        ("/avatar", "Get someone's avatar"),
        ("/invite", "Bot invite link"),
        ("/birthday <month> <day>", "Set your birthday"),
        ("/birthdaycheck", "Check a user's birthday"),
        ("/upcomingbirthdays", "Upcoming birthdays"),
    ],
    "Stream": [
        ("/stream hotstar <title>", "Search Hotstar"),
        ("/stream yt <query>", "Search YouTube"),
        ("/streaming", "See who is currently streaming"),
    ],
    "AI": [
        ("/ask <question>", "Ask JARVIS anything (Claude)"),
        ("/vibe <mood>", "Get a song recommendation"),
        ("/tldr <text>", "Summarize text"),
    ],
}

MOD_COMMANDS = {
    "Moderation": [
        ("/warn @user", "Issue a warning"),
        ("/warnings @user", "View warnings"),
        ("/clearwarnings @user", "Clear warnings"),
        ("/kick @user", "Kick a member"),
        ("/ban @user", "Ban a member"),
        ("/unban <id>", "Unban by user ID"),
        ("/timeout @user <duration>", "Timeout a member"),
        ("/untimeout @user", "Remove timeout"),
        ("/purge <1-100>", "Bulk delete messages"),
        ("/lock", "Lock this channel"),
        ("/unlock", "Unlock this channel"),
        ("/slowmode <seconds>", "Set slowmode"),
        ("/nickhistory @user", "View nickname history"),
    ],
    "AutoMod": [
        ("/automod <enable/disable>", "Toggle AutoMod"),
        ("/bannedwords <add/remove/list>", "Manage banned words"),
    ],
}

ADMIN_COMMANDS = {
    "Server Setup": [
        ("/setup", "Build full channel structure"),
        ("/communitysetup", "Configure starboard, counting, confessions, media"),
        ("/streamsetup", "Set up the stream channel"),
        ("/setdj @role", "Set DJ role for music control"),
        ("/setmusicchannel #ch", "Lock music commands to a channel"),
        ("/247", "Toggle 24/7 mode (bot stays in VC)"),
        ("/setautorole @role", "Auto-assign role on join"),
        ("/setmodlog #ch", "Set mod action log channel"),
        ("/setbumpchannel #ch", "Set bump reminder channel"),
        ("/setwelcome #ch", "Set welcome message channel"),
    ],
    "Roles & Economy": [
        ("/colormenu", "Post color picker menu"),
        ("/rolesmenu <title>", "Create a role picker menu"),
        ("/roleadd <menu_id> @role", "Add role to a menu"),
        ("/shopadd <name> <price> @role", "Add item to shop"),
        ("/shopremove <id>", "Remove shop item"),
        ("/addcoins @user <amount>", "Give coins to a user"),
    ],
    "Giveaways & Events": [
        ("/giveaway <prize> <duration>", "Start a giveaway"),
        ("/reroll <msg_id>", "Reroll a giveaway winner"),
        ("/giveawayend <msg_id>", "End a giveaway early"),
    ],
    "AI & YouTube": [
        ("/aichannel #ch", "Set AI auto-reply channel"),
        ("/refreshyt <token>", "Update YouTube visitorData token"),
    ],
}


def build_page(title: str, sections: dict) -> discord.Embed:
    embed = discord.Embed(title=title, color=0x5865F2)
    for section, cmds in sections.items():
        lines = "\n".join(f"`{cmd}` — {desc}" for cmd, desc in cmds)
        embed.add_field(name=section, value=lines, inline=False)
    embed.set_footer(text="Use the buttons to navigate between pages")
    return embed


class HelpView(discord.ui.View):
    def __init__(self, is_mod: bool, is_admin: bool):
        super().__init__(timeout=120)
        self.is_mod = is_mod
        self.is_admin = is_admin
        self.page = 0
        self.pages = self._build_pages()

    def _build_pages(self) -> list[discord.Embed]:
        pages = [build_page("JARVIS — Commands", EVERYONE_COMMANDS)]
        if self.is_mod:
            pages.append(build_page("JARVIS — Moderation", MOD_COMMANDS))
        if self.is_admin:
            pages.append(build_page("JARVIS — Admin", ADMIN_COMMANDS))
        return pages

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, disabled=True)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available commands based on your role")
    async def help(self, interaction: discord.Interaction):
        member = interaction.user
        is_mod = member.guild_permissions.moderate_members or member.guild_permissions.manage_guild
        is_admin = member.guild_permissions.administrator

        view = HelpView(is_mod, is_admin)
        view._update_buttons()
        if len(view.pages) == 1:
            view.stop()
            await interaction.response.send_message(embed=view.pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(embed=view.pages[0], view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
