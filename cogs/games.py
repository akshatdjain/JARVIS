import asyncio
import random
import string
import aiohttp
import datetime
import discord
from discord.ext import commands
from discord import app_commands

# ── WORDLE ────────────────────────────────────────────────────────────────────
WORDLE_WORDS = [
    "apple", "brave", "chair", "dance", "eagle", "flame", "grace", "heart",
    "ivory", "joker", "knife", "lemon", "magic", "night", "ocean", "piano",
    "queen", "raven", "smile", "tiger", "ultra", "voice", "water", "xenon",
    "yacht", "zebra", "about", "above", "abuse", "actor", "acute", "admit",
    "adopt", "adult", "after", "again", "agent", "agree", "ahead", "alarm",
    "album", "alert", "alike", "align", "alive", "alley", "allow", "alone",
    "along", "aloud", "alpha", "altar", "alter", "angel", "anger", "angle",
    "angry", "anime", "annoy", "antic", "anvil", "apart", "aping", "apron",
    "ardor", "arena", "argue", "arise", "armor", "aroma", "array", "arrow",
    "artsy", "asked", "atlas", "attic", "audio", "audit", "augur", "aunty",
    "avail", "avant", "avert", "avid", "avoid", "award", "awful", "awoke",
    "azure", "babel", "badge", "badly", "baker", "banjo", "banks", "basic",
    "basis", "batch", "beach", "beard", "beast", "began", "being", "below",
    "bench", "bible", "birth", "bison", "black", "blade", "blame", "bland",
    "blank", "blast", "blaze", "bleak", "bleed", "blend", "bless", "blind",
    "block", "blood", "blown", "blues", "blunt", "blurb", "blurt", "board",
    "boost", "booth", "bound", "boxer", "brace", "braid", "brain", "brand",
    "break", "breed", "bribe", "brick", "bride", "brief", "bring", "brisk",
    "broad", "broil", "broke", "brood", "brook", "broth", "brush", "build",
    "built", "bulge", "bunch", "burly", "burnt", "burst", "cabin", "cache",
    "camel", "canal", "candy", "cargo", "carry", "catch", "cause", "cease",
]


def wordle_check(guess: str, answer: str) -> str:
    result = []
    answer_chars = list(answer)
    guess_chars = list(guess)
    marks = ["⬛"] * 5
    used = [False] * 5

    for i in range(5):
        if guess_chars[i] == answer_chars[i]:
            marks[i] = "🟩"
            used[i] = True
            guess_chars[i] = None

    for i in range(5):
        if guess_chars[i] is not None:
            for j in range(5):
                if not used[j] and guess_chars[i] == answer_chars[j]:
                    marks[i] = "🟨"
                    used[j] = True
                    break

    return "".join(marks)


class WordleGame:
    def __init__(self, answer: str):
        self.answer = answer
        self.guesses: list[tuple[str, str]] = []
        self.max_guesses = 6
        self.won = False
        self.lost = False

    def guess(self, word: str) -> str:
        result = wordle_check(word, self.answer)
        self.guesses.append((word, result))
        if result == "🟩🟩🟩🟩🟩":
            self.won = True
        elif len(self.guesses) >= self.max_guesses:
            self.lost = True
        return result

    def build_embed(self) -> discord.Embed:
        color = 0x2ECC71 if self.won else (0xE74C3C if self.lost else 0x2B2D31)
        embed = discord.Embed(title="🟩 Wordle", color=color)
        board = ""
        for word, result in self.guesses:
            board += f"{result}  `{word.upper()}`\n"
        for _ in range(self.max_guesses - len(self.guesses)):
            board += "⬛⬛⬛⬛⬛\n"
        embed.description = board
        if self.won:
            embed.set_footer(text=f"Solved in {len(self.guesses)}/{self.max_guesses} guesses!")
        elif self.lost:
            embed.set_footer(text=f"Answer was: {self.answer.upper()}")
        else:
            embed.set_footer(text=f"{self.max_guesses - len(self.guesses)} guesses remaining")
        return embed


# ── HANGMAN ───────────────────────────────────────────────────────────────────
HANGMAN_STAGES = [
    "```\n  +---+\n      |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n  |   |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|   |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|\\  |\n      |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|\\  |\n /    |\n      |\n=========```",
    "```\n  +---+\n  O   |\n /|\\  |\n / \\  |\n      |\n=========```",
]

HANGMAN_WORDS = [
    "python", "discord", "lavalink", "wavelink", "database", "container",
    "raspberry", "keyboard", "algorithm", "framework", "javascript", "typescript",
    "minecraft", "developer", "software", "hardware", "streaming", "microphone",
]


class HangmanGame:
    def __init__(self, word: str, channel_id: int):
        self.word = word
        self.channel_id = channel_id
        self.guessed: set[str] = set()
        self.wrong: list[str] = []
        self.max_wrong = 6

    @property
    def display(self) -> str:
        return " ".join(c if c in self.guessed else "_" for c in self.word)

    @property
    def won(self) -> bool:
        return all(c in self.guessed for c in self.word)

    @property
    def lost(self) -> bool:
        return len(self.wrong) >= self.max_wrong

    def guess(self, letter: str) -> bool:
        letter = letter.lower()
        self.guessed.add(letter)
        if letter not in self.word:
            self.wrong.append(letter)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        color = 0x2ECC71 if self.won else (0xE74C3C if self.lost else 0x2B2D31)
        embed = discord.Embed(title="🎭 Hangman", color=color)
        embed.add_field(name="Board", value=HANGMAN_STAGES[len(self.wrong)], inline=False)
        word_display = self.word if self.lost else self.display
        embed.add_field(name="Word", value=f"`{word_display}`", inline=True)
        embed.add_field(name="Wrong", value=", ".join(self.wrong) or "none", inline=True)
        if self.won:
            embed.set_footer(text="You won!")
        elif self.lost:
            embed.set_footer(text=f"Game over! Word was: {self.word}")
        return embed


# ── TIC TAC TOE ───────────────────────────────────────────────────────────────
class TicTacToeButton(discord.ui.Button):
    def __init__(self, pos: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="​", row=pos // 3)
        self.pos = pos

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user != view.current_player():
            return await interaction.response.send_message("❌ Not your turn!", ephemeral=True)
        if view.board[self.pos] != 0:
            return await interaction.response.send_message("❌ Already taken!", ephemeral=True)

        view.board[self.pos] = view.turn
        self.label = "❌" if view.turn == 1 else "⭕"
        self.style = discord.ButtonStyle.danger if view.turn == 1 else discord.ButtonStyle.primary
        self.disabled = True

        winner = view.check_winner()
        if winner:
            view.stop()
            for child in view.children:
                child.disabled = True
            p = view.player1 if winner == 1 else view.player2
            await interaction.response.edit_message(
                content=f"🏆 {p.mention} wins!", embed=None, view=view
            )
        elif all(v != 0 for v in view.board):
            view.stop()
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(content="🤝 It's a draw!", embed=None, view=view)
        else:
            view.turn = 3 - view.turn
            p = view.current_player()
            await interaction.response.edit_message(
                content=f"{'❌' if view.turn == 1 else '⭕'} {p.mention}'s turn",
                view=view
            )


class TicTacToeView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=120)
        self.player1 = player1
        self.player2 = player2
        self.board = [0] * 9
        self.turn = 1
        for i in range(9):
            self.add_item(TicTacToeButton(i))

    def current_player(self) -> discord.Member:
        return self.player1 if self.turn == 1 else self.player2

    def check_winner(self) -> int:
        wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for a, b, c in wins:
            if self.board[a] == self.board[b] == self.board[c] != 0:
                return self.board[a]
        return 0


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._wordle_games: dict[int, WordleGame] = {}   # user_id -> game
        self._hangman_games: dict[int, HangmanGame] = {} # channel_id -> game

    # ── TRIVIA ────────────────────────────────────────────────────────────────
    @app_commands.command(name="trivia", description="Answer a trivia question and earn XP")
    async def trivia(self, interaction: discord.Interaction):
        await interaction.response.defer()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    "https://opentdb.com/api.php?amount=1&type=multiple",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
            except Exception:
                return await interaction.followup.send("❌ Trivia API unavailable.")

        q = data["results"][0]
        import html
        question = html.unescape(q["question"])
        correct = html.unescape(q["correct_answer"])
        wrong = [html.unescape(a) for a in q["incorrect_answers"]]
        options = wrong + [correct]
        random.shuffle(options)
        correct_idx = options.index(correct)

        labels = ["A", "B", "C", "D"]
        view = discord.ui.View(timeout=20)
        answered = {"done": False}

        async def make_callback(idx: int):
            async def callback(btn_interaction: discord.Interaction):
                if answered["done"]:
                    return
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message("Not your question!", ephemeral=True)
                answered["done"] = True
                view.stop()
                if idx == correct_idx:
                    xp_gain = 50
                    async with self.bot.db.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO levels (user_id, guild_id, xp, level) VALUES ($1, $2, $3, 0) "
                            "ON CONFLICT (user_id, guild_id) DO UPDATE SET xp = levels.xp + $3",
                            interaction.user.id, interaction.guild_id, xp_gain
                        )
                    result = f"✅ Correct! +{xp_gain} XP"
                    color = 0x2ECC71
                else:
                    result = f"❌ Wrong! The answer was **{correct}**"
                    color = 0xE74C3C
                embed = discord.Embed(title="🎯 Trivia Result", description=result, color=color)
                embed.add_field(name="Question", value=question, inline=False)
                await btn_interaction.response.edit_message(embed=embed, view=None)
            return callback

        embed = discord.Embed(
            title="🎯 Trivia",
            description=f"**{question}**\n\nCategory: *{q['category']}* | Difficulty: *{q['difficulty']}*",
            color=0x5865F2,
        )
        for i, opt in enumerate(options):
            btn = discord.ui.Button(label=f"{labels[i]}: {opt}", style=discord.ButtonStyle.secondary, row=i // 2)
            btn.callback = await make_callback(i)
            view.add_item(btn)

        embed.set_footer(text="You have 20 seconds!")
        await interaction.followup.send(embed=embed, view=view)

    # ── WORDLE ────────────────────────────────────────────────────────────────
    @app_commands.command(name="wordle", description="Start a Wordle game")
    async def wordle(self, interaction: discord.Interaction):
        if interaction.user.id in self._wordle_games:
            game = self._wordle_games[interaction.user.id]
            if not game.won and not game.lost:
                return await interaction.response.send_message(
                    "You already have an active game! Use `/wordleguess` to guess.", ephemeral=True
                )
        answer = random.choice(WORDLE_WORDS)
        self._wordle_games[interaction.user.id] = WordleGame(answer)
        embed = WordleGame(answer).build_embed()
        embed.set_footer(text="Use /wordleguess <word> to guess! You have 6 tries.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="wordleguess", description="Guess a word in your Wordle game")
    async def wordleguess(self, interaction: discord.Interaction, word: str):
        game = self._wordle_games.get(interaction.user.id)
        if not game:
            return await interaction.response.send_message("Start a game with `/wordle` first!", ephemeral=True)
        if game.won or game.lost:
            return await interaction.response.send_message("Game over! Start a new one with `/wordle`.", ephemeral=True)
        word = word.lower().strip()
        if len(word) != 5 or not word.isalpha():
            return await interaction.response.send_message("❌ Must be a 5-letter word.", ephemeral=True)

        game.guess(word)
        embed = game.build_embed()
        if game.won or game.lost:
            self._wordle_games.pop(interaction.user.id, None)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── HANGMAN ───────────────────────────────────────────────────────────────
    @app_commands.command(name="hangman", description="Start a hangman game in this channel")
    async def hangman(self, interaction: discord.Interaction):
        if interaction.channel_id in self._hangman_games:
            g = self._hangman_games[interaction.channel_id]
            if not g.won and not g.lost:
                return await interaction.response.send_message(
                    "There's already an active hangman game here!", ephemeral=True
                )
        word = random.choice(HANGMAN_WORDS)
        self._hangman_games[interaction.channel_id] = HangmanGame(word, interaction.channel_id)
        game = self._hangman_games[interaction.channel_id]
        await interaction.response.send_message(embed=game.build_embed())

    @app_commands.command(name="guess", description="Guess a letter in the hangman game")
    async def guess(self, interaction: discord.Interaction, letter: str):
        game = self._hangman_games.get(interaction.channel_id)
        if not game:
            return await interaction.response.send_message("No active hangman game! Use `/hangman`.", ephemeral=True)
        if game.won or game.lost:
            self._hangman_games.pop(interaction.channel_id, None)
            return await interaction.response.send_message("Game over! Start a new one.", ephemeral=True)
        letter = letter[0].lower()
        if letter in game.guessed:
            return await interaction.response.send_message(f"Already guessed `{letter}`!", ephemeral=True)
        game.guess(letter)
        embed = game.build_embed()
        if game.won or game.lost:
            self._hangman_games.pop(interaction.channel_id, None)
        await interaction.response.send_message(embed=embed)

    # ── TIC TAC TOE ───────────────────────────────────────────────────────────
    @app_commands.command(name="ttt", description="Challenge someone to Tic Tac Toe")
    async def ttt(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.bot or opponent == interaction.user:
            return await interaction.response.send_message("❌ Invalid opponent.", ephemeral=True)
        view = TicTacToeView(interaction.user, opponent)
        await interaction.response.send_message(
            f"❌ {interaction.user.mention} vs ⭕ {opponent.mention}\n{interaction.user.mention}'s turn",
            view=view
        )

    # ── WOULD YOU RATHER ─────────────────────────────────────────────────────
    @app_commands.command(name="wyr", description="Would you rather...?")
    async def wyr(self, interaction: discord.Interaction):
        WYR_PROMPTS = [
            ("Have super speed", "Have super strength"),
            ("Live in the past", "Live in the future"),
            ("Always be 10 minutes late", "Always be 20 minutes early"),
            ("Have unlimited money but no friends", "Have great friends but always be broke"),
            ("Only listen to one song forever", "Never listen to music again"),
            ("Be able to fly", "Be invisible"),
            ("Speak every language", "Play every instrument"),
            ("Have a personal chef", "Have a personal driver"),
            ("Never sleep again", "Never need to eat again"),
            ("Know when you'll die", "Know how you'll die"),
        ]
        a, b = random.choice(WYR_PROMPTS)
        votes = {"a": set(), "b": set()}
        view = discord.ui.View(timeout=30)

        async def vote_a(btn_interaction: discord.Interaction):
            votes["b"].discard(btn_interaction.user.id)
            votes["a"].add(btn_interaction.user.id)
            await btn_interaction.response.defer()

        async def vote_b(btn_interaction: discord.Interaction):
            votes["a"].discard(btn_interaction.user.id)
            votes["b"].add(btn_interaction.user.id)
            await btn_interaction.response.defer()

        btn_a = discord.ui.Button(label=f"🅰️ {a}", style=discord.ButtonStyle.primary)
        btn_b = discord.ui.Button(label=f"🅱️ {b}", style=discord.ButtonStyle.secondary)
        btn_a.callback = vote_a
        btn_b.callback = vote_b
        view.add_item(btn_a)
        view.add_item(btn_b)

        embed = discord.Embed(title="🤔 Would You Rather...?", color=0x9B59B6)
        embed.add_field(name="🅰️", value=a, inline=True)
        embed.add_field(name="🅱️", value=b, inline=True)
        embed.set_footer(text="Vote in 30 seconds!")
        msg = await interaction.response.send_message(embed=embed, view=view)

        await asyncio.sleep(30)
        view.stop()
        total = len(votes["a"]) + len(votes["b"])
        pct_a = int(len(votes["a"]) / total * 100) if total else 0
        pct_b = 100 - pct_a if total else 0
        result_embed = discord.Embed(title="🤔 Would You Rather — Results", color=0x9B59B6)
        result_embed.add_field(name=f"🅰️ {a}", value=f"**{pct_a}%** ({len(votes['a'])} votes)", inline=True)
        result_embed.add_field(name=f"🅱️ {b}", value=f"**{pct_b}%** ({len(votes['b'])} votes)", inline=True)
        await interaction.edit_original_response(embed=result_embed, view=None)

    # ── TRUTH OR DARE ─────────────────────────────────────────────────────────
    @app_commands.command(name="tod", description="Truth or Dare!")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Truth", value="truth"),
        app_commands.Choice(name="Dare", value="dare"),
    ])
    async def tod(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        TRUTHS = [
            "What's the most embarrassing thing you've ever done?",
            "What's your biggest fear?",
            "Have you ever lied to get out of trouble? What was it?",
            "What's the most childish thing you still do?",
            "What's a secret you've never told anyone?",
            "Who was your first crush?",
            "What's the worst gift you've ever received?",
            "Have you ever cheated on a test?",
            "What's the most embarrassing thing on your phone?",
            "What's a bad habit you have that you can't stop?",
        ]
        DARES = [
            "Send a voice message singing the chorus of the last song you listened to.",
            "Change your profile picture to a meme for 1 hour.",
            "Type with your elbows for the next 5 minutes.",
            "DM a random contact 'I know what you did'.",
            "Set your status to 'I love fortnite' for 30 minutes.",
            "Send the 10th photo in your camera roll.",
            "Talk in rhymes for the next 3 messages.",
            "Do 20 pushups and report back.",
            "Let someone else send one message as you.",
            "Post an embarrassing childhood photo.",
        ]
        pool = TRUTHS if choice.value == "truth" else DARES
        prompt = random.choice(pool)
        icon = "🤔" if choice.value == "truth" else "🎯"
        embed = discord.Embed(
            title=f"{icon} {choice.name}!",
            description=f"**{interaction.user.mention}**, your {choice.name.lower()}:\n\n*{prompt}*",
            color=0xE74C3C if choice.value == "dare" else 0x3498DB,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Games(bot))
