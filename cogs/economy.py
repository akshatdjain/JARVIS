import random
import asyncio
import datetime
import discord
from discord.ext import commands
from discord import app_commands

SCHEMA = """
CREATE TABLE IF NOT EXISTS economy (
    user_id BIGINT,
    guild_id BIGINT,
    coins BIGINT DEFAULT 0,
    last_daily TIMESTAMPTZ,
    PRIMARY KEY (user_id, guild_id)
);
CREATE TABLE IF NOT EXISTS shop_items (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    name TEXT,
    description TEXT,
    role_id BIGINT,
    price INTEGER,
    stock INTEGER DEFAULT -1
);
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    amount BIGINT,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

DAILY_AMOUNT = 200
CHAT_COINS_RANGE = (1, 5)
CHAT_COOLDOWN = 60


async def get_balance(conn, user_id: int, guild_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT coins FROM economy WHERE user_id = $1 AND guild_id = $2",
        user_id, guild_id
    )
    return row["coins"] if row else 0


async def add_coins(conn, user_id: int, guild_id: int, amount: int, reason: str = ""):
    await conn.execute(
        "INSERT INTO economy (user_id, guild_id, coins) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id, guild_id) DO UPDATE SET coins = economy.coins + $3",
        user_id, guild_id, amount
    )
    if reason:
        await conn.execute(
            "INSERT INTO transactions (guild_id, user_id, amount, reason) VALUES ($1, $2, $3, $4)",
            guild_id, user_id, amount, reason
        )


class BlackjackView(discord.ui.View):
    SUITS = ["♠", "♥", "♦", "♣"]
    VALS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

    def __init__(self, bot, user_id: int, guild_id: int, bet: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.bet = bet
        deck = [v for v in self.VALS for _ in self.SUITS]
        random.shuffle(deck)
        self.deck = deck
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.done = False

    def card_value(self, card: str) -> int:
        if card in ("J", "Q", "K"):
            return 10
        if card == "A":
            return 11
        return int(card)

    def hand_value(self, hand: list) -> int:
        total = sum(self.card_value(c) for c in hand)
        aces = hand.count("A")
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def build_embed(self, result: str = "") -> discord.Embed:
        pv = self.hand_value(self.player)
        dv = self.hand_value(self.dealer) if self.done else "?"
        dealer_show = " ".join(self.dealer) if self.done else f"{self.dealer[0]} ??"
        color = 0x2ECC71 if "win" in result.lower() else (0xE74C3C if "lose" in result.lower() or "bust" in result.lower() else 0x2B2D31)
        embed = discord.Embed(title=f"🃏 Blackjack — Bet: {self.bet:,} coins", color=color)
        embed.add_field(name=f"Your Hand ({pv})", value=" ".join(self.player), inline=True)
        embed.add_field(name=f"Dealer ({dv})", value=dealer_show, inline=True)
        if result:
            embed.set_footer(text=result)
        return embed

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🎯")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your game!", ephemeral=True)
        self.player.append(self.deck.pop())
        pv = self.hand_value(self.player)
        if pv > 21:
            self.done = True
            self.stop()
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "UPDATE economy SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3",
                    self.bet, self.user_id, self.guild_id
                )
            await interaction.response.edit_message(embed=self.build_embed(f"Bust! You lost {self.bet:,} coins."), view=None)
        else:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your game!", ephemeral=True)
        self.done = True
        self.stop()
        while self.hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        pv = self.hand_value(self.player)
        dv = self.hand_value(self.dealer)
        async with self.bot.db.acquire() as conn:
            if dv > 21 or pv > dv:
                winnings = self.bet
                await add_coins(conn, self.user_id, self.guild_id, winnings, "blackjack win")
                result = f"You win! +{winnings:,} coins"
            elif pv == dv:
                result = "Push! Bet returned."
            else:
                await conn.execute(
                    "UPDATE economy SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3",
                    self.bet, self.user_id, self.guild_id
                )
                result = f"Dealer wins. -{self.bet:,} coins"
        await interaction.response.edit_message(embed=self.build_embed(result), view=None)


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._chat_cooldowns: dict[tuple, float] = {}
        self.bot.loop.create_task(self._init_db())

    async def _init_db(self):
        await self.bot.wait_until_ready()
        async with self.bot.db.acquire() as conn:
            await conn.execute(SCHEMA)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.author.id, message.guild.id)
        import time
        now = time.time()
        if now - self._chat_cooldowns.get(key, 0) < CHAT_COOLDOWN:
            return
        self._chat_cooldowns[key] = now
        coins = random.randint(*CHAT_COINS_RANGE)
        async with self.bot.db.acquire() as conn:
            await add_coins(conn, message.author.id, message.guild.id, coins)

    @app_commands.command(name="balance", description="Check your coin balance")
    async def balance(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        async with self.bot.db.acquire() as conn:
            coins = await get_balance(conn, target.id, interaction.guild_id)
            rank = await conn.fetchval(
                "SELECT COUNT(*) + 1 FROM economy WHERE guild_id = $1 AND coins > $2",
                interaction.guild_id, coins
            )
        embed = discord.Embed(title=f"💰 {target.display_name}'s Balance", color=0xF1C40F)
        embed.add_field(name="Coins", value=f"**{coins:,}** 🪙", inline=True)
        embed.add_field(name="Rank", value=f"**#{rank}**", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily coin reward")
    async def daily(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_daily FROM economy WHERE user_id = $1 AND guild_id = $2",
                interaction.user.id, interaction.guild_id
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            if row and row["last_daily"]:
                diff = now - row["last_daily"]
                if diff.total_seconds() < 86400:
                    remaining = 86400 - diff.total_seconds()
                    h, m = divmod(int(remaining) // 60, 60)
                    return await interaction.response.send_message(
                        f"⏰ Daily already claimed! Come back in **{h}h {m}m**.", ephemeral=True
                    )
            await conn.execute(
                "INSERT INTO economy (user_id, guild_id, coins, last_daily) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET coins = economy.coins + $3, last_daily = $4",
                interaction.user.id, interaction.guild_id, DAILY_AMOUNT, now
            )
        embed = discord.Embed(
            title="💰 Daily Reward!",
            description=f"You claimed **{DAILY_AMOUNT:,} coins**! Come back tomorrow for more.",
            color=0xF1C40F,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Send coins to another user")
    async def pay(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ You can't pay yourself.", ephemeral=True)
        async with self.bot.db.acquire() as conn:
            sender_bal = await get_balance(conn, interaction.user.id, interaction.guild_id)
            if sender_bal < amount:
                return await interaction.response.send_message(f"❌ You only have **{sender_bal:,}** coins.", ephemeral=True)
            await conn.execute(
                "UPDATE economy SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3",
                amount, interaction.user.id, interaction.guild_id
            )
            await add_coins(conn, user.id, interaction.guild_id, amount, f"transfer from {interaction.user.id}")
        await interaction.response.send_message(
            f"✅ Sent **{amount:,} coins** to {user.mention}!"
        )

    @app_commands.command(name="ecoleaderboard", description="Top coin holders in the server")
    async def ecoleaderboard(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, coins FROM economy WHERE guild_id = $1 ORDER BY coins DESC LIMIT 10",
                interaction.guild_id
            )
        if not rows:
            return await interaction.response.send_message("No economy data yet.", ephemeral=True)
        embed = discord.Embed(title="💰 Coin Leaderboard", color=0xF1C40F)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            member = interaction.guild.get_member(row["user_id"])
            name = member.display_name if member else f"User {row['user_id']}"
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{medal} **{name}** — {row['coins']:,} 🪙")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slots", description="Spin the slot machine")
    async def slots(self, interaction: discord.Interaction, bet: app_commands.Range[int, 10, 10000]):
        async with self.bot.db.acquire() as conn:
            bal = await get_balance(conn, interaction.user.id, interaction.guild_id)
            if bal < bet:
                return await interaction.response.send_message(f"❌ Not enough coins. You have **{bal:,}**.", ephemeral=True)

        SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎"]
        WEIGHTS = [30, 25, 20, 15, 7, 3]
        reels = random.choices(SYMBOLS, weights=WEIGHTS, k=3)

        if reels[0] == reels[1] == reels[2]:
            mult = 10 if reels[0] == "💎" else (5 if reels[0] == "⭐" else 3)
            winnings = bet * mult
            result = f"JACKPOT! +{winnings:,} coins (x{mult})"
            color = 0xF1C40F
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            winnings = bet
            result = f"Two of a kind! +{winnings:,} coins"
            color = 0x2ECC71
        else:
            winnings = -bet
            result = f"No match. -{bet:,} coins"
            color = 0xE74C3C

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "UPDATE economy SET coins = coins + $1 WHERE user_id = $2 AND guild_id = $3",
                winnings, interaction.user.id, interaction.guild_id
            )
            new_bal = await get_balance(conn, interaction.user.id, interaction.guild_id)

        embed = discord.Embed(title="🎰 Slot Machine", color=color)
        embed.add_field(name="Reels", value=f"[ {' | '.join(reels)} ]", inline=False)
        embed.add_field(name="Result", value=result, inline=True)
        embed.add_field(name="Balance", value=f"{new_bal:,} 🪙", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="blackjack", description="Play blackjack against the dealer")
    async def blackjack(self, interaction: discord.Interaction, bet: app_commands.Range[int, 10, 50000]):
        async with self.bot.db.acquire() as conn:
            bal = await get_balance(conn, interaction.user.id, interaction.guild_id)
            if bal < bet:
                return await interaction.response.send_message(f"❌ Not enough coins. You have **{bal:,}**.", ephemeral=True)

        view = BlackjackView(self.bot, interaction.user.id, interaction.guild_id, bet)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="shop", description="Browse the server shop")
    async def shop(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            items = await conn.fetch(
                "SELECT * FROM shop_items WHERE guild_id = $1 ORDER BY price ASC",
                interaction.guild_id
            )
        if not items:
            return await interaction.response.send_message(
                "❌ No items in the shop yet. Admins can use `/shopadd` to add items.", ephemeral=True
            )
        embed = discord.Embed(title="🏪 Server Shop", color=0x5865F2)
        for item in items:
            role = interaction.guild.get_role(item["role_id"])
            stock = f"Stock: {item['stock']}" if item["stock"] >= 0 else "Unlimited"
            embed.add_field(
                name=f"`{item['id']}` {item['name']} — {item['price']:,} 🪙",
                value=f"{item['description']}\nRole: {role.mention if role else 'N/A'} • {stock}",
                inline=False,
            )
        embed.set_footer(text="Use /buy <id> to purchase an item")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the shop")
    async def buy(self, interaction: discord.Interaction, item_id: int):
        async with self.bot.db.acquire() as conn:
            item = await conn.fetchrow(
                "SELECT * FROM shop_items WHERE id = $1 AND guild_id = $2",
                item_id, interaction.guild_id
            )
            if not item:
                return await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            if item["stock"] == 0:
                return await interaction.response.send_message("❌ Out of stock.", ephemeral=True)

            bal = await get_balance(conn, interaction.user.id, interaction.guild_id)
            if bal < item["price"]:
                return await interaction.response.send_message(
                    f"❌ Not enough coins. Need **{item['price']:,}**, you have **{bal:,}**.", ephemeral=True
                )

            await conn.execute(
                "UPDATE economy SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3",
                item["price"], interaction.user.id, interaction.guild_id
            )
            if item["stock"] > 0:
                await conn.execute("UPDATE shop_items SET stock = stock - 1 WHERE id = $1", item_id)

        role = interaction.guild.get_role(item["role_id"])
        if role:
            try:
                await interaction.user.add_roles(role, reason=f"Shop purchase: {item['name']}")
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"✅ Purchased **{item['name']}** for **{item['price']:,} coins**!"
            + (f" You received the {role.mention} role!" if role else "")
        )

    @app_commands.command(name="shopadd", description="Add an item to the shop")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shopadd(self, interaction: discord.Interaction, name: str, price: int, role: discord.Role, description: str = "", stock: int = -1):
        async with self.bot.db.acquire() as conn:
            item_id = await conn.fetchval(
                "INSERT INTO shop_items (guild_id, name, description, role_id, price, stock) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                interaction.guild_id, name, description, role.id, price, stock
            )
        await interaction.response.send_message(
            f"✅ Added **{name}** to the shop (ID: `{item_id}`, Price: {price:,} 🪙).", ephemeral=True
        )

    @app_commands.command(name="shopremove", description="Remove an item from the shop")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shopremove(self, interaction: discord.Interaction, item_id: int):
        async with self.bot.db.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM shop_items WHERE id = $1 AND guild_id = $2", item_id, interaction.guild_id
            )
        if result == "DELETE 0":
            return await interaction.response.send_message("❌ Item not found.", ephemeral=True)
        await interaction.response.send_message(f"✅ Removed item `{item_id}` from the shop.", ephemeral=True)

    @app_commands.command(name="addcoins", description="Give coins to a user (admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addcoins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        async with self.bot.db.acquire() as conn:
            await add_coins(conn, user.id, interaction.guild_id, amount, "admin grant")
            new_bal = await get_balance(conn, user.id, interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Added **{amount:,} coins** to {user.mention}. New balance: **{new_bal:,}**.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
