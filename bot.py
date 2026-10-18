import os
import logging
import asyncio
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from database import Database
import threading
import uvicorn
from api import app as api_app, set_bot

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PREFIX = os.getenv("COMMAND_PREFIX", ",")
GUILD_ID = os.getenv("GUILD_ID", "").strip()
DEFAULT_COLOR = int(os.getenv("EMBED_COLOR", "8B5CF6").replace("#", ""), 16)
db = Database(os.getenv("DATABASE_PATH", "vantahq.sqlite3"))

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN. Copy .env.example to .env and add your bot token.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vantahq")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

def moderator_check():
    async def predicate(ctx):
        return bool(ctx.guild and (ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.administrator))
    return commands.check(predicate)

class Moderation(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def do_warn(self, guild, member, moderator, reason):
        await db.add_case(guild.id, "warn", member.id, moderator.id, reason)
        try:
            await member.send(embed=discord.Embed(title="⚠️ You were warned in VantaHQ", description=f"**Reason:** {reason}\n**Moderator:** {moderator}", color=discord.Colour.orange()))
        except discord.HTTPException: pass
        await log_to_server(guild, "⚠️ Member warned", f"**Member:** {member.mention}\n**Moderator:** {moderator.mention}\n**Reason:** {reason}", discord.Colour.orange())

    @app_commands.command(name="warn", description="Warn a member and DM them.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await self.do_warn(interaction.guild, member, interaction.user, reason)
        await interaction.response.send_message(f"⚠️ Warned {member.mention}.", ephemeral=True)

    @commands.command(name="warn")
    @moderator_check()
    async def warn_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.reply("You need the **Moderate Members** permission.")
        await self.do_warn(ctx.guild, member, ctx.author, reason)
        await ctx.reply(f"⚠️ Warned {member.mention}.")

    async def do_ban(self, guild, member, moderator, reason):
        try: await member.send(embed=discord.Embed(title="You were banned from VantaHQ", description=f"Reason: {reason}", color=discord.Colour.red()))
        except discord.HTTPException: pass
        await member.ban(reason=f"{moderator} | {reason}")
        await db.add_case(guild.id, "ban", member.id, moderator.id, reason)
        await log_to_server(guild, "🔨 Member banned", f"**Member:** {member} (`{member.id}`)\n**Moderator:** {moderator.mention}\n**Reason:** {reason}", discord.Colour.red())

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await self.do_ban(interaction.guild, member, interaction.user, reason)
        await interaction.response.send_message(f"🔨 Banned {member.mention}.", ephemeral=True)

    @commands.command(name="ban")
    @moderator_check()
    async def ban_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not ctx.author.guild_permissions.ban_members:
            return await ctx.reply("You need the **Ban Members** permission.")
        await self.do_ban(ctx.guild, member, ctx.author, reason)
        await ctx.reply(f"🔨 Banned {member.mention}.")

    async def do_kick(self, guild, member, moderator, reason):
        try: await member.send(embed=discord.Embed(title="You were kicked from VantaHQ", description=f"Reason: {reason}", color=discord.Colour.orange()))
        except discord.HTTPException: pass
        await member.kick(reason=f"{moderator} | {reason}")
        await db.add_case(guild.id, "kick", member.id, moderator.id, reason)
        await log_to_server(guild, "👢 Member kicked", f"**Member:** {member} (`{member.id}`)\n**Moderator:** {moderator.mention}\n**Reason:** {reason}", discord.Colour.orange())

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await self.do_kick(interaction.guild, member, interaction.user, reason)
        await interaction.response.send_message(f"👢 Kicked {member.mention}.", ephemeral=True)

    @commands.command(name="kick")
    @moderator_check()
    async def kick_prefix(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not ctx.author.guild_permissions.kick_members:
            return await ctx.reply("You need the **Kick Members** permission.")
        await self.do_kick(ctx.guild, member, ctx.author, reason)
        await ctx.reply(f"👢 Kicked {member.mention}.")

    async def do_timeout(self, guild, member, moderator, minutes, reason):
        await member.timeout(timedelta(minutes=minutes), reason=f"{moderator} | {reason}")
        await db.add_case(guild.id, "timeout", member.id, moderator.id, reason)
        await log_to_server(guild, "⏳ Member timed out", f"**Member:** {member.mention}\n**Duration:** {minutes} minutes\n**Moderator:** {moderator.mention}\n**Reason:** {reason}")

    @app_commands.command(name="timeout", description="Timeout a member for a number of minutes.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_slash(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
        await self.do_timeout(interaction.guild, member, interaction.user, minutes, reason)
        await interaction.response.send_message(f"⏳ Timed out {member.mention} for {minutes} minutes.", ephemeral=True)

    @commands.command(name="timeout", aliases=["mute"])
    @moderator_check()
    async def timeout_prefix(self, ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.reply("You need the **Moderate Members** permission.")
        if not 1 <= minutes <= 40320:
            return await ctx.reply("Minutes must be between 1 and 40320.")
        await self.do_timeout(ctx.guild, member, ctx.author, minutes, reason)
        await ctx.reply(f"⏳ Timed out {member.mention} for {minutes} minutes.")

    @app_commands.command(name="purge", description="Delete 1–100 recent messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_slash(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)
        await log_to_server(interaction.guild, "🧹 Messages purged", f"**Moderator:** {interaction.user.mention}\n**Channel:** {interaction.channel.mention}\n**Count:** {len(deleted)}")

    @commands.command(name="purge", aliases=["clear"])
    @moderator_check()
    async def purge_prefix(self, ctx, amount: int):
        if not ctx.author.guild_permissions.manage_messages:
            return await ctx.reply("You need the **Manage Messages** permission.")
        if not 1 <= amount <= 100:
            return await ctx.reply("Choose an amount from 1 to 100.")
        deleted = await ctx.channel.purge(limit=amount + 1)
        count = max(0, len(deleted) - 1)
        note = await ctx.send(f"🧹 Deleted {count} messages.")
        await asyncio.sleep(3)
        try: await note.delete()
        except discord.HTTPException: pass
        await log_to_server(ctx.guild, "🧹 Messages purged", f"**Moderator:** {ctx.author.mention}\n**Channel:** {ctx.channel.mention}\n**Count:** {count}")

class TicketControls(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="🛡️", custom_id="vantahq:ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Only staff with Manage Channels can claim tickets.", ephemeral=True)
        await interaction.response.send_message(f"🛡️ Ticket claimed by {interaction.user.mention}.")
        await log_to_server(interaction.guild, "🎟️ Ticket claimed", f"**Staff:** {interaction.user.mention}\n**Channel:** {interaction.channel.mention}")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="vantahq:ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Only staff with Manage Channels can close tickets.", ephemeral=True)
        await interaction.response.send_message("🔒 Closing this ticket in 5 seconds.")
        await db.delete_ticket_by_channel(interaction.channel.id)
        await log_to_server(interaction.guild, "🎟️ Ticket closed", f"**Closed by:** {interaction.user.mention}\n**Channel:** {interaction.channel.name}")
        await asyncio.sleep(5)
        try: await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException: pass

class TicketPanel(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎟️", custom_id="vantahq:ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        existing = await db.get_ticket(guild.id, interaction.user.id)
        if existing:
            channel = guild.get_channel(existing)
            if channel:
                return await interaction.response.send_message(f"You already have a ticket: {channel.mention}", ephemeral=True)
        category_id = await db.get_setting(guild.id, "ticket_category")
        category = guild.get_channel(int(category_id)) if category_id and category_id.isdigit() else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        role_id = await db.get_setting(guild.id, "ticket_staff_role")
        role = guild.get_role(int(role_id)) if role_id and role_id.isdigit() else None
        if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        name = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c == "-")[:18] or "member"
        channel = await guild.create_text_channel(f"ticket-{name}", category=category, overwrites=overwrites, reason=f"Ticket opened by {interaction.user}")
        await db.create_ticket(guild.id, interaction.user.id, channel.id)
        embed = discord.Embed(title="VantaHQ Support Ticket", description=f"Welcome {interaction.user.mention}!\nExplain what you need help with. Staff will be with you shortly.", color=DEFAULT_COLOR)
        await channel.send(content=role.mention if role else None, embed=embed, view=TicketControls(self.bot))
        await interaction.response.send_message(f"Your ticket has been created: {channel.mention}", ephemeral=True)
        await log_to_server(guild, "🎟️ Ticket opened", f"**User:** {interaction.user.mention}\n**Channel:** {channel.mention}")

class Tickets(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ticketsetup", description="Configure ticket category and optional staff role.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticketsetup(self, interaction: discord.Interaction, category: discord.CategoryChannel, staff_role: Optional[discord.Role] = None):
        await db.set_setting(interaction.guild_id, "ticket_category", str(category.id))
        if staff_role: await db.set_setting(interaction.guild_id, "ticket_staff_role", str(staff_role.id))
        await interaction.response.send_message("Ticket settings saved.", ephemeral=True)

    @app_commands.command(name="ticketpanel", description="Post the VantaHQ ticket panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticketpanel_slash(self, interaction: discord.Interaction):
        await interaction.channel.send(embed=discord.Embed(title="VantaHQ Support", description="Press **Open Ticket** for partnerships, editing questions, reports, or other support.", color=DEFAULT_COLOR), view=TicketPanel(self.bot))
        await interaction.response.send_message("Ticket panel posted.", ephemeral=True)

    @commands.command(name="ticketpanel")
    @moderator_check()
    async def ticketpanel_prefix(self, ctx):
        await ctx.send(embed=discord.Embed(title="VantaHQ Support", description="Press **Open Ticket** for partnerships, editing questions, reports, or other support.", color=DEFAULT_COLOR), view=TicketPanel(self.bot))

class CoreCommands(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ping", description="Show bot latency.")
    async def ping_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! `{round(self.bot.latency * 1000)} ms`", ephemeral=True)

    @commands.command(name="ping")
    async def ping_prefix(self, ctx):
        await ctx.reply(f"🏓 Pong! `{round(self.bot.latency * 1000)} ms`")

    @app_commands.command(name="avatar", description="Show a member's avatar.")
    async def avatar_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        embed = discord.Embed(title=f"{target.display_name}'s avatar", color=DEFAULT_COLOR)
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="avatar", aliases=["av", "pfp"])
    async def avatar_prefix(self, ctx, member: Optional[discord.Member] = None):
        target = member or ctx.author
        embed = discord.Embed(title=f"{target.display_name}'s avatar", color=DEFAULT_COLOR)
        embed.set_image(url=target.display_avatar.url)
        await ctx.reply(embed=embed)

    @app_commands.command(name="userinfo", description="Show information about a server member.")
    async def userinfo_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        m = member or interaction.user
        embed = discord.Embed(title=f"User Info — {m}", color=DEFAULT_COLOR, timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=m.display_avatar.url)
        embed.add_field(name="User ID", value=str(m.id), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(m.created_at, style="R"), inline=True)
        if m.joined_at: embed.add_field(name="Joined server", value=discord.utils.format_dt(m.joined_at, style="R"), inline=True)
        embed.add_field(name="Top role", value=m.top_role.mention if m.top_role else "None", inline=True)
        embed.add_field(name="Bot", value="Yes" if m.bot else "No", inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="userinfo", aliases=["whois", "user"])
    async def userinfo_prefix(self, ctx, member: Optional[discord.Member] = None):
        m = member or ctx.author
        embed = discord.Embed(title=f"User Info — {m}", color=DEFAULT_COLOR, timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=m.display_avatar.url)
        embed.add_field(name="User ID", value=str(m.id), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(m.created_at, style="R"), inline=True)
        if m.joined_at: embed.add_field(name="Joined server", value=discord.utils.format_dt(m.joined_at, style="R"), inline=True)
        embed.add_field(name="Top role", value=m.top_role.mention if m.top_role else "None", inline=True)
        embed.add_field(name="Bot", value="Yes" if m.bot else "No", inline=True)
        await ctx.reply(embed=embed)

    @app_commands.command(name="serverinfo", description="Show information about this server.")
    async def serverinfo_slash(self, interaction: discord.Interaction):
        g = interaction.guild
        embed = discord.Embed(title=f"{g.name} — Server Info", color=DEFAULT_COLOR, timestamp=discord.utils.utcnow())
        if g.icon: embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Server ID", value=str(g.id), inline=True)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>" if g.owner_id else "Unknown", inline=True)
        embed.add_field(name="Members", value=str(g.member_count or 0), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, style="D"), inline=True)
        embed.add_field(name="Text channels", value=str(len(g.text_channels)), inline=True)
        embed.add_field(name="Roles", value=str(max(0, len(g.roles)-1)), inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="serverinfo", aliases=["server", "si"])
    async def serverinfo_prefix(self, ctx):
        g = ctx.guild
        embed = discord.Embed(title=f"{g.name} — Server Info", color=DEFAULT_COLOR, timestamp=discord.utils.utcnow())
        if g.icon: embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Server ID", value=str(g.id), inline=True)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>" if g.owner_id else "Unknown", inline=True)
        embed.add_field(name="Members", value=str(g.member_count or 0), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, style="D"), inline=True)
        embed.add_field(name="Text channels", value=str(len(g.text_channels)), inline=True)
        embed.add_field(name="Roles", value=str(max(0, len(g.roles)-1)), inline=True)
        await ctx.reply(embed=embed)

    @app_commands.command(name="membercount", description="Show the server member count.")
    async def membercount_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👥 **{interaction.guild.name}** has **{interaction.guild.member_count or 0}** members.")

    @commands.command(name="membercount", aliases=["members", "mc"])
    async def membercount_prefix(self, ctx):
        await ctx.reply(f"👥 **{ctx.guild.name}** has **{ctx.guild.member_count or 0}** members.")

    @app_commands.command(name="slowmode", description="Set slowmode in this channel, in seconds.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a text channel.", ephemeral=True)
        await interaction.channel.edit(slowmode_delay=seconds, reason=f"Set by {interaction.user}")
        await interaction.response.send_message(f"🐢 Slowmode set to **{seconds} seconds**.")

    @commands.command(name="slowmode", aliases=["slow"])
    @commands.has_permissions(manage_channels=True)
    async def slowmode_prefix(self, ctx, seconds: int):
        if not 0 <= seconds <= 21600: return await ctx.reply("Choose a value between 0 and 21600 seconds.")
        if not isinstance(ctx.channel, discord.TextChannel): return await ctx.reply("This only works in a text channel.")
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Set by {ctx.author}")
        await ctx.reply(f"🐢 Slowmode set to **{seconds} seconds**.")

    @app_commands.command(name="lock", description="Prevent @everyone from sending messages in this channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_slash(self, interaction: discord.Interaction):
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel): return await interaction.response.send_message("This only works in a text channel.", ephemeral=True)
        ow = ch.overwrites_for(interaction.guild.default_role); ow.send_messages = False
        await ch.set_permissions(interaction.guild.default_role, overwrite=ow, reason=f"Locked by {interaction.user}")
        await interaction.response.send_message("🔒 Channel locked.")

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock_prefix(self, ctx):
        ch = ctx.channel
        if not isinstance(ch, discord.TextChannel): return await ctx.reply("This only works in a text channel.")
        ow = ch.overwrites_for(ctx.guild.default_role); ow.send_messages = False
        await ch.set_permissions(ctx.guild.default_role, overwrite=ow, reason=f"Locked by {ctx.author}")
        await ctx.reply("🔒 Channel locked.")

    @app_commands.command(name="unlock", description="Allow @everyone to send messages in this channel again.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock_slash(self, interaction: discord.Interaction):
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel): return await interaction.response.send_message("This only works in a text channel.", ephemeral=True)
        ow = ch.overwrites_for(interaction.guild.default_role); ow.send_messages = None
        await ch.set_permissions(interaction.guild.default_role, overwrite=ow, reason=f"Unlocked by {interaction.user}")
        await interaction.response.send_message("🔓 Channel unlocked.")

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock_prefix(self, ctx):
        ch = ctx.channel
        if not isinstance(ch, discord.TextChannel): return await ctx.reply("This only works in a text channel.")
        ow = ch.overwrites_for(ctx.guild.default_role); ow.send_messages = None
        await ch.set_permissions(ctx.guild.default_role, overwrite=ow, reason=f"Unlocked by {ctx.author}")
        await ctx.reply("🔓 Channel unlocked.")

    @app_commands.command(name="nick", description="Change a member's nickname.")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nick_slash(self, interaction: discord.Interaction, member: discord.Member, nickname: Optional[str] = None):
        await member.edit(nick=nickname, reason=f"Nickname changed by {interaction.user}")
        await interaction.response.send_message(f"Nickname updated for {member.mention}.", ephemeral=True)

    @commands.command(name="nick", aliases=["nickname"])
    @commands.has_permissions(manage_nicknames=True)
    async def nick_prefix(self, ctx, member: discord.Member, *, nickname: Optional[str] = None):
        await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
        await ctx.reply(f"Nickname updated for {member.mention}.")

    @app_commands.command(name="roleadd", description="Give a role to a member.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def roleadd_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role: return await interaction.response.send_message("That role is above or equal to my top role.", ephemeral=True)
        await member.add_roles(role, reason=f"Role added by {interaction.user}")
        await interaction.response.send_message(f"Added {role.mention} to {member.mention}.", ephemeral=True)

    @commands.command(name="roleadd", aliases=["addrole", "role"])
    @commands.has_permissions(manage_roles=True)
    async def roleadd_prefix(self, ctx, member: discord.Member, role: discord.Role):
        if role >= ctx.guild.me.top_role: return await ctx.reply("That role is above or equal to my top role.")
        await member.add_roles(role, reason=f"Role added by {ctx.author}")
        await ctx.reply(f"Added {role.mention} to {member.mention}.")

    @app_commands.command(name="roleremove", description="Remove a role from a member.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def roleremove_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role: return await interaction.response.send_message("That role is above or equal to my top role.", ephemeral=True)
        await member.remove_roles(role, reason=f"Role removed by {interaction.user}")
        await interaction.response.send_message(f"Removed {role.mention} from {member.mention}.", ephemeral=True)

    @commands.command(name="roleremove", aliases=["removerole", "delrole"])
    @commands.has_permissions(manage_roles=True)
    async def roleremove_prefix(self, ctx, member: discord.Member, role: discord.Role):
        if role >= ctx.guild.me.top_role: return await ctx.reply("That role is above or equal to my top role.")
        await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
        await ctx.reply(f"Removed {role.mention} from {member.mention}.")

    @app_commands.command(name="unban", description="Unban a user by their Discord ID.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_slash(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        try: uid = int(user_id)
        except ValueError: return await interaction.response.send_message("Enter a valid numeric Discord user ID.", ephemeral=True)
        try:
            entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
            await interaction.guild.unban(entry.user, reason=f"{interaction.user}: {reason}")
        except discord.NotFound: return await interaction.response.send_message("That user is not banned (or the ID is incorrect).", ephemeral=True)
        await db.add_case(interaction.guild_id, "unban", uid, interaction.user.id, reason)
        await log_to_server(interaction.guild, "🔓 Member unbanned", f"**User ID:** `{uid}`\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}")
        await interaction.response.send_message(f"Unbanned user ID `{uid}`.", ephemeral=True)

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban_prefix(self, ctx, user_id: int, *, reason="No reason provided"):
        try:
            entry = await ctx.guild.fetch_ban(discord.Object(id=user_id))
            await ctx.guild.unban(entry.user, reason=f"{ctx.author}: {reason}")
        except discord.NotFound: return await ctx.reply("That user is not banned (or the ID is incorrect).")
        await db.add_case(ctx.guild.id, "unban", user_id, ctx.author.id, reason)
        await log_to_server(ctx.guild, "🔓 Member unbanned", f"**User ID:** `{user_id}`\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}")
        await ctx.reply(f"Unbanned user ID `{user_id}`.")

class Utility(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="setlogs", description="Set the moderation log channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setlogs_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db.set_setting(interaction.guild_id, "log_channel", str(channel.id))
        await interaction.response.send_message(f"Logs will go to {channel.mention}.", ephemeral=True)

    @commands.command(name="setlogs")
    @moderator_check()
    async def setlogs_prefix(self, ctx, channel: discord.TextChannel):
        await db.set_setting(ctx.guild.id, "log_channel", str(channel.id))
        await ctx.reply(f"Logs will go to {channel.mention}.")

    @app_commands.command(name="setboostchannel", description="Set the channel for server boost announcements.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setboostchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db.set_setting(interaction.guild_id, "boost_channel", str(channel.id))
        await interaction.response.send_message(f"Boost announcements will go to {channel.mention}.", ephemeral=True)

    @commands.command(name="setboostchannel")
    @moderator_check()
    async def setboostchannel_prefix(self, ctx, channel: discord.TextChannel):
        await db.set_setting(ctx.guild.id, "boost_channel", str(channel.id))
        await ctx.reply(f"Boost announcements will go to {channel.mention}.")

    @app_commands.command(name="setwelcome", description="Set the welcome message channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcome_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db.set_setting(interaction.guild_id, "welcome_channel", str(channel.id))
        await interaction.response.send_message(f"Welcome messages will go to {channel.mention}.", ephemeral=True)

    @commands.command(name="setwelcome")
    @moderator_check()
    async def setwelcome_prefix(self, ctx, channel: discord.TextChannel):
        await db.set_setting(ctx.guild.id, "welcome_channel", str(channel.id))
        await ctx.reply(f"Welcome messages will go to {channel.mention}.")

    @app_commands.command(name="help", description="Show VantaHQ commands.")
    async def help_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="VantaHQ Bot Commands", color=DEFAULT_COLOR)
        embed.add_field(name="Moderation", value="`/ban` `,ban` · `/kick` `,kick` · `/warn` `,warn` · `/timeout` `,timeout` · `/purge` `,purge`", inline=False)
        embed.add_field(name="Server & Utility", value="`ping` · `avatar` · `userinfo` · `serverinfo` · `membercount` · `slowmode` · `lock` · `unlock` · `nick` · `roleadd` · `roleremove` · `unban`", inline=False)
        embed.add_field(name="Setup", value="`/setlogs` `,setlogs` · `/setwelcome` `,setwelcome` · `/setboostchannel` `,setboostchannel` · `/ticketsetup` · `/ticketpanel` `,ticketpanel`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="help")
    async def help_prefix(self, ctx):
        embed = discord.Embed(title="VantaHQ Bot Commands", color=DEFAULT_COLOR)
        embed.add_field(name="Moderation", value="`,ban @member reason` · `,kick @member reason` · `,warn @member reason` · `,timeout @member minutes reason` · `,purge 25`", inline=False)
        embed.add_field(name="Server & Utility", value="`,ping` · `,avatar @member` · `,userinfo @member` · `,serverinfo` · `,membercount` · `,slowmode seconds` · `,lock` · `,unlock` · `,nick @member nickname` · `,roleadd @member @role` · `,roleremove @member @role` · `,unban userID`", inline=False)
        embed.add_field(name="Setup", value="`,setlogs #channel` · `,setwelcome #channel` · `,setboostchannel #channel` · `,ticketpanel`", inline=False)
        await ctx.reply(embed=embed)

class VantaBot(commands.Bot):
    async def setup_hook(self):
        await db.initialize()
        await self.add_cog(Moderation(self))
        await self.add_cog(CoreCommands(self))
        await self.add_cog(Tickets(self))
        await self.add_cog(Utility(self))
        self.add_view(TicketPanel(self))
        self.add_view(TicketControls(self))
        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %s commands to test guild %s", len(synced), GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %s global commands", len(synced))

bot = VantaBot(command_prefix=commands.when_mentioned_or(PREFIX), intents=intents, help_command=None)

@bot.event
async def on_ready():
    log.info("Logged in as %s (ID %s)", bot.user, bot.user.id)

@bot.event
async def on_member_join(member: discord.Member):
    channel_id = await db.get_setting(member.guild.id, "welcome_channel")
    channel = member.guild.get_channel(int(channel_id)) if channel_id and channel_id.isdigit() else None
    if channel:
        embed = discord.Embed(title="Welcome to VantaHQ 🎬", description=f"Yo {member.mention}, welcome to **{member.guild.name}**!\nCheck out the rules and show us what you can edit.", color=DEFAULT_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        await channel.send(embed=embed)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # Discord exposes boosts through premium_since. Re-boost events can be detected when it changes from None.
    if before.premium_since is None and after.premium_since is not None:
        channel_id = await db.get_setting(after.guild.id, "boost_channel")
        channel = after.guild.get_channel(int(channel_id)) if channel_id and channel_id.isdigit() else None
        if channel:
            await channel.send(content=f"🚀 Huge thanks to {after.mention} for boosting VantaHQ!",
                embed=discord.Embed(title="💜 Thank You for Boosting!", description="Your support helps VantaHQ grow. We appreciate you helping our editing community level up!", color=DEFAULT_COLOR))

@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and not message.author.bot:
        await log_to_server(message.guild, "🗑️ Message deleted", f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Content:** {(message.content or '[No text content]')[:1500]}")

@bot.event
async def on_member_remove(member: discord.Member):
    await log_to_server(member.guild, "👋 Member left", f"**Member:** {member} (`{member.id}`)")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You don't have permission to use that command."
    else:
        log.error("Slash command error: %r", error)
        message = "Something went wrong. Check the bot logs and permissions."
    try:
        if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
        else: await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException: pass

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound): return
    if isinstance(error, commands.CheckFailure): return await ctx.reply("You don't have permission to use that command.")
    if isinstance(error, commands.MissingRequiredArgument): return await ctx.reply(f"Missing argument: `{error.param.name}`. Use `,help`.")
    if isinstance(error, commands.BadArgument): return await ctx.reply("I couldn't understand an argument. Check `,help`.")
    log.error("Prefix command error: %r", error)
    await ctx.reply("Something went wrong. Check the bot logs.")

set_bot(bot)

def run_api():
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        api_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

if __name__ == "__main__":
    api_thread = threading.Thread(
        target=run_api,
        daemon=True,
    )
    api_thread.start()
    bot.run(TOKEN)
