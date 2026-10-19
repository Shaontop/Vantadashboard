
import asyncio
import re
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import imageio_ffmpeg


# VantaHQ channel settings
CREATE_CHANNEL_ID = 1561548581939183696
PANEL_CHANNEL_ID = 1561548409838641263

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()


YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "default_search": "ytsearch1",
    "extract_flat": False,
    "extractor_args": {
        "youtube": {
            "player_client": ["tv", "web_safari"],
        },
    },
}


FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


def owner_id(channel):
    """Read the owner ID saved in a temporary voice channel's topic."""
    if not channel.topic:
        return None
    match = re.search(r"VantaHQ owner:(\d+)", channel.topic)
    return int(match.group(1)) if match else None


async def search_song(query):
    """Search YouTube and return the playable audio information."""
    def extract():
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = result.get("entries") or []
            if not entries:
                raise ValueError("No songs found.")

            song = entries[0]
            webpage = song.get("webpage_url") or song.get("url")
            if not webpage:
                raise ValueError("Could not get the song link.")

            if song.get("formats") and song.get("url"):
                info = song
            else:
                info = ydl.extract_info(webpage, download=False)

            return {
                "title": info.get("title", song.get("title", "Unknown song")),
                "webpage_url": info.get("webpage_url", webpage),
                "audio_url": info.get("url"),
                "duration": info.get("duration"),
            }

    return await asyncio.to_thread(extract)


class SongModal(discord.ui.Modal, title="Change Song"):
    song = discord.ui.TextInput(
        label="Song name or YouTube link",
        placeholder="Search for a song...",
        max_length=200,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.request_song(interaction, str(self.song))


class AddPersonModal(discord.ui.Modal, title="Add Someone to Your Room"):
    person = discord.ui.TextInput(
        label="User ID or @mention",
        placeholder="Enter their Discord user ID",
        max_length=40,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.user.voice.channel if interaction.user.voice else None

        if not channel or owner_id(channel) != interaction.user.id:
            await interaction.response.send_message(
                "Join your own temporary room first.", ephemeral=True
            )
            return

        raw = str(self.person).strip()
        match = re.search(r"\d{15,22}", raw)
        if not match:
            await interaction.response.send_message(
                "Enter a valid user ID or mention.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(int(match.group()))
        if not member:
            await interaction.response.send_message(
                "I couldn't find that member in this server.", ephemeral=True
            )
            return

        await channel.set_permissions(
            member, connect=True, view_channel=True
        )
        await interaction.response.send_message(
            f"Added {member.mention} to **{channel.name}**.", ephemeral=True
        )


class MusicPanel(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def get_owned_room(self, interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Join your temporary voice room first.", ephemeral=True
            )
            return None

        channel = interaction.user.voice.channel
        if owner_id(channel) != interaction.user.id:
            await interaction.response.send_message(
                "You must be in a temporary room you own.", ephemeral=True
            )
            return None

        return channel

    @discord.ui.button(
        label="Lock", style=discord.ButtonStyle.secondary,
        emoji="🔒", custom_id="vantahq:lock"
    )
    async def lock(self, interaction, button):
        channel = await self.get_owned_room(interaction)
        if channel is None:
            return
        await channel.set_permissions(
            interaction.guild.default_role, connect=False
        )
        await interaction.response.send_message(
            "🔒 Your room is locked.", ephemeral=True
        )

    @discord.ui.button(
        label="Unlock", style=discord.ButtonStyle.secondary,
        emoji="🔓", custom_id="vantahq:unlock"
    )
    async def unlock(self, interaction, button):
        channel = await self.get_owned_room(interaction)
        if channel is None:
            return
        await channel.set_permissions(
            interaction.guild.default_role, overwrite=None
        )
        await interaction.response.send_message(
            "🔓 Your room is unlocked.", ephemeral=True
        )

    @discord.ui.button(
        label="Add People", style=discord.ButtonStyle.primary,
        emoji="👥", custom_id="vantahq:add_people"
    )
    async def add_people(self, interaction, button):
        channel = await self.get_owned_room(interaction)
        if channel is None:
            return
        await interaction.response.send_modal(AddPersonModal(self.cog))

    @discord.ui.button(
        label="Change Song", style=discord.ButtonStyle.primary,
        emoji="🎵", custom_id="vantahq:change_song"
    )
    async def change_song(self, interaction, button):
        if not interaction.user.voice:
            await interaction.response.send_message(
                "Join a voice channel first.", ephemeral=True
            )
            return
        await interaction.response.send_modal(SongModal(self.cog))

    @discord.ui.button(
        label="Skip", style=discord.ButtonStyle.secondary,
        emoji="⏭️", custom_id="vantahq:skip"
    )
    async def skip(self, interaction, button):
        voice = interaction.guild.voice_client
        if not voice or not voice.is_playing():
            await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
            return
        voice.stop()
        await interaction.response.send_message("⏭️ Skipped.", ephemeral=True)

    @discord.ui.button(
        label="Queue", style=discord.ButtonStyle.secondary,
        emoji="📃", custom_id="vantahq:queue"
    )
    async def queue_button(self, interaction, button):
        songs = self.cog.queues[interaction.guild.id]
        if not songs:
            message = "The queue is empty."
        else:
            message = "\n".join(
                f"**{i}.** {song['title']}"
                for i, song in enumerate(list(songs)[:10], start=1)
            )
        await interaction.response.send_message(message, ephemeral=True)


class VoiceMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = defaultdict(deque)
        self.panel = MusicPanel(self)

    async def cog_load(self):
        self.bot.add_view(self.panel)

    @commands.Cog.listener()
    async def on_ready(self):
        channel = self.bot.get_channel(PANEL_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        # Reuse an existing VantaHQ panel instead of posting duplicates.
        async for message in channel.history(limit=50):
            if (
                message.author == self.bot.user
                and message.embeds
                and message.embeds[0].footer.text == "VantaHQ Music Panel"
            ):
                await message.edit(view=self.panel)
                return

        embed = discord.Embed(
            title="🎵 VantaHQ Music",
            description=(
                "Join a voice channel and use the buttons below.\n\n"
                "🔒 **Lock** — Keep others out\n"
                "🔓 **Unlock** — Open your room\n"
                "👥 **Add People** — Allow a member into your room\n"
                "🎵 **Change Song** — Search YouTube by song name\n"
                "⏭️ **Skip** — Skip the current song\n"
                "📃 **Queue** — View upcoming songs\n\n"
                "You can also use **/play**."
            ),
            color=discord.Color.from_rgb(255, 125, 35),
        )
        embed.set_footer(text="VantaHQ Music Panel")
        await channel.send(embed=embed, view=self.panel)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # Create a temporary room when a member joins the designated channel.
        if after.channel and after.channel.id == CREATE_CHANNEL_ID:
            category = after.channel.category
            new_channel = await member.guild.create_voice_channel(
                name=f"{member.display_name}'s Room",
                category=category,
                topic=f"VantaHQ owner:{member.id}",
                user_limit=0,
            )
            await member.move_to(new_channel)

        # Delete temporary rooms when they become empty.
        if before.channel and before.channel.id != CREATE_CHANNEL_ID:
            if owner_id(before.channel) and len(before.channel.members) == 0:
                await before.channel.delete(reason="Empty VantaHQ temporary room")

    async def request_song(self, interaction, query):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send(
                "Join a voice channel first.", ephemeral=True
            )
            return

        try:
            song = await search_song(query)
            if not song["audio_url"]:
                raise ValueError("Couldn't get a playable audio stream.")

            song["requested_by"] = interaction.user.display_name
            guild_id = interaction.guild.id
            self.queues[guild_id].append(song)

            voice = interaction.guild.voice_client
            target = interaction.user.voice.channel

            if voice is None:
                voice = await target.connect()
            elif voice.channel != target:
                await voice.move_to(target)

            await interaction.followup.send(
                f"🎵 Added **{song['title']}** to the queue.",
                ephemeral=True,
            )
            await self.play_next(interaction.guild)

        except Exception as error:
            await interaction.followup.send(
                f"Couldn't play that song: {error}", ephemeral=True
            )

    async def play_next(self, guild):
        voice = guild.voice_client
        if not voice or voice.is_playing() or voice.is_paused():
            return

        if not self.queues[guild.id]:
            return

        song = self.queues[guild.id].popleft()

        # Refresh the stream URL before playback because YouTube URLs expire.
        try:
            fresh_song = await search_song(song["webpage_url"])
            audio_url = fresh_song["audio_url"]
            if not audio_url:
                raise ValueError("No audio stream available.")

            source = discord.FFmpegPCMAudio(
                audio_url,
                executable=FFMPEG_PATH,
                before_options=FFMPEG_OPTIONS["before_options"],
                options=FFMPEG_OPTIONS["options"],
            )

            def after_playback(error):
                if error:
                    print(f"VantaHQ audio playback error: {error}")
                asyncio.run_coroutine_threadsafe(
                    self.play_next(guild), self.bot.loop
                )

            voice.play(source, after=after_playback)
        except Exception as error:
            print(f"VantaHQ couldn't play a queued song: {error}")
            await self.play_next(guild)

    @app_commands.command(name="play", description="Search YouTube and play a song")
    @app_commands.describe(song="Song name or YouTube link")
    async def play(self, interaction: discord.Interaction, song: str):
        await self.request_song(interaction, song)


async def setup(bot):
    await bot.add_cog(VoiceMusic(bot))
