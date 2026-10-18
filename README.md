# VantaHQ Discord Bot (free starter)

A Python/discord.py starter bot for a VantaHQ editing server. Run locally on Windows; it costs nothing to run on your own PC.

## Included
- Slash and comma-prefix commands: ban, kick, warn, timeout/mute, purge
- Moderation logs and warning/ban/kick DMs
- Ticket panel with open, claim and close buttons
- Custom embeds
- Welcome messages
- Boost notification with text mention outside the embed
- Editing community commands: rate, portfolio, suggest
- SQLite settings and moderation case storage

**Rep notification:** not included yet because the bot needs to know how your server's rep system works (which command/bot handles reps). Configure that once you tell us the rep method.

## 1. Install Python
Install Python 3.11 or newer from https://www.python.org/downloads/windows/
During setup, tick **Add Python to PATH**.

## 2. Create the Discord application
Go to https://discord.com/developers/applications and create an application named VantaHQ.
Under **Bot**, create/reset the token and keep it private.
Enable **Server Members Intent** and **Message Content Intent**.
Under **OAuth2 > URL Generator**, select scopes `bot` and `applications.commands`; choose permissions the bot needs (Manage Channels, Manage Messages, Kick Members, Ban Members, Moderate Members, Send Messages, Embed Links, Read Message History, View Channels). Open the generated URL to add it to your server. Give the bot role only the permissions it needs and place its role above roles it must moderate.

## 3. Set up the bot files
- Extract the ZIP into a folder, e.g. `C:\\VantaHQ_Bot`.
- Rename `.env.example` to `.env`.
- Paste your bot token after `DISCORD_TOKEN=` in `.env`. Never share this file or token.
- Optional but recommended while testing: enter your server ID after `GUILD_ID=`. Enable Developer Mode in Discord, right-click your server, and choose Copy Server ID.

## 4. Install libraries
Open the extracted folder in File Explorer. Click the address bar, type `cmd`, and press Enter. In the terminal run:

```bat
py -3 -m pip install -r requirements.txt
```

## 5. Start the bot
Double-click `run.bat`. Keep that window open while you want the bot online. When it logs in, try `/help` or `,help`.

## 6. Configure in your server
- `/setlogs #mod-logs` — choose log channel
- `/setwelcome #welcome` — choose welcome channel
- Create a category for tickets, then `/ticketsetup` and select that category; optionally select a staff role
- `/ticketpanel` — post the ticket panel
- `/setboostchannel #boosts` — choose where boost announcements go. Discord boost notifications are included; rep notifications need your rep system details.

## Troubleshooting
- Slash commands may take time to appear if no `GUILD_ID` is set. Put your server ID in `.env` to sync commands to that server immediately during testing.
- If prefix commands don't respond, check Message Content Intent is enabled in the Developer Portal and that the bot role can read/send messages.
- The bot must have a role above members it moderates.
- If the token was exposed, reset it immediately in the Developer Portal.
