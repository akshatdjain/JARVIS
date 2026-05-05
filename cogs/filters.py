import discord
from discord.ext import commands
from discord import app_commands
import wavelink


def _eq(gains: list[float]) -> wavelink.Equalizer:
    return wavelink.Equalizer(payload=[{"band": i, "gain": g} for i, g in enumerate(gains)])


def _ts(speed: float, pitch: float, rate: float = 1.0) -> wavelink.Timescale:
    return wavelink.Timescale(payload={"speed": speed, "pitch": pitch, "rate": rate})


def _rot(hz: float) -> wavelink.Rotation:
    return wavelink.Rotation(payload={"rotationHz": hz})


FILTER_PRESETS = {
    "bassboost": {"equalizer": _eq([0.3, 0.25, 0.2, 0.15, 0.1, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])},
    "nightcore": {"timescale": _ts(1.25, 1.3)},
    "vaporwave": {"timescale": _ts(0.8, 0.8)},
    "8d": {"rotation": _rot(0.2)},
    "soft": {"equalizer": _eq([-0.05, 0.0, 0.05, 0.1, 0.1, 0.05, 0.0, -0.05, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1])},
    "pop": {"equalizer": _eq([-0.02, -0.01, 0.08, 0.1, 0.1, 0.05, 0.0, -0.03, -0.05, -0.05, 0.0, 0.05, 0.1, 0.1, 0.05])},
}


class Filters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _require_vc(self, interaction: discord.Interaction) -> wavelink.Player | None:
        return interaction.guild.voice_client

    @app_commands.command(name="filter", description="Apply an audio filter to the player")
    @app_commands.choices(preset=[
        app_commands.Choice(name="Bassboost", value="bassboost"),
        app_commands.Choice(name="Nightcore", value="nightcore"),
        app_commands.Choice(name="Vaporwave", value="vaporwave"),
        app_commands.Choice(name="8D Audio", value="8d"),
        app_commands.Choice(name="Soft", value="soft"),
        app_commands.Choice(name="Pop", value="pop"),
        app_commands.Choice(name="Reset (off)", value="reset"),
    ])
    async def filter(self, interaction: discord.Interaction, preset: app_commands.Choice[str]):
        vc: wavelink.Player = self._require_vc(interaction)
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)

        filters = wavelink.Filters()

        if preset.value == "reset":
            await vc.set_filters(filters)
            return await interaction.response.send_message("✅ Filters reset.")

        config = FILTER_PRESETS.get(preset.value, {})
        for key, val in config.items():
            setattr(filters, key, val)

        await vc.set_filters(filters)
        await interaction.response.send_message(f"✅ Applied **{preset.name}** filter.")

    @app_commands.command(name="bassboost", description="Toggle bassboost on/off")
    async def bassboost(self, interaction: discord.Interaction):
        vc: wavelink.Player = self._require_vc(interaction)
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)

        current = vc.filters
        filters = wavelink.Filters()
        if current.equalizer is not None:
            await vc.set_filters(filters)
            await interaction.response.send_message("🔇 Bassboost **off**.")
        else:
            config = FILTER_PRESETS["bassboost"]
            for key, val in config.items():
                setattr(filters, key, val)
            await vc.set_filters(filters)
            await interaction.response.send_message("🔊 Bassboost **on**.")

    @app_commands.command(name="nightcore", description="Toggle nightcore (speed + pitch up)")
    async def nightcore(self, interaction: discord.Interaction):
        vc: wavelink.Player = self._require_vc(interaction)
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)

        current = vc.filters
        filters = wavelink.Filters()
        if current.timescale is not None:
            await vc.set_filters(filters)
            await interaction.response.send_message("✅ Nightcore **off**.")
        else:
            config = FILTER_PRESETS["nightcore"]
            for key, val in config.items():
                setattr(filters, key, val)
            await vc.set_filters(filters)
            await interaction.response.send_message("✅ Nightcore **on**.")

    @app_commands.command(name="8d", description="Toggle 8D rotating audio effect")
    async def audio_8d(self, interaction: discord.Interaction):
        vc: wavelink.Player = self._require_vc(interaction)
        if not vc or not vc.playing:
            return await interaction.response.send_message("❌ Nothing is playing!", ephemeral=True)

        current = vc.filters
        filters = wavelink.Filters()
        if current.rotation is not None:
            await vc.set_filters(filters)
            await interaction.response.send_message("🎧 8D Audio **off**.")
        else:
            config = FILTER_PRESETS["8d"]
            for key, val in config.items():
                setattr(filters, key, val)
            await vc.set_filters(filters)
            await interaction.response.send_message("🎧 8D Audio **on**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Filters(bot))
