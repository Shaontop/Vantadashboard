
import os
import secrets

import aiosqlite
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="VantaHQ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://shaontop.github.io"],
    allow_methods=["GET", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-VantaHQ-Key"],
)

bot_client = None
DATABASE_PATH = os.getenv("DATABASE_PATH", "vantahq.sqlite3")

ALLOWED_SETTINGS = {
    "welcome_channel",
    "boost_channel",
    "log_channel",
    "ticket_category",
    "ticket_staff_role",
}


def set_bot(bot):
    global bot_client
    bot_client = bot


def require_dashboard_key(key: str | None):
    expected = os.getenv("VANTAHQ_DASHBOARD_KEY", "").strip()

    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Dashboard key is not configured on the server.",
        )

    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_guild(guild_id: int):
    if bot_client is None or not bot_client.is_ready():
        raise HTTPException(status_code=503, detail="Bot is not ready.")

    guild = bot_client.get_guild(guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail="Bot is not in this server.")

    return guild


@app.get("/api/status")
async def status():
    connected = bot_client is not None and bot_client.is_ready()
    return {
        "status": "API online",
        "bot": "VantaHQ",
        "connected": connected,
        "message": (
            "Discord bot connected"
            if connected
            else "Discord bot is not connected"
        ),
    }


@app.get("/api/guilds")
async def get_guilds(
    x_vantahq_key: str | None = Header(default=None),
):
    require_dashboard_key(x_vantahq_key)

    if bot_client is None or not bot_client.is_ready():
        raise HTTPException(status_code=503, detail="Bot is not ready.")

    return {
        "guilds": [
            {"id": str(guild.id), "name": guild.name}
            for guild in bot_client.guilds
        ]
    }


@app.get("/api/settings/{guild_id}")
async def get_settings(
    guild_id: int,
    x_vantahq_key: str | None = Header(default=None),
):
    require_dashboard_key(x_vantahq_key)
    require_guild(guild_id)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT key, value FROM settings WHERE guild_id = ?",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()

    return {
        "guild_id": str(guild_id),
        "settings": {
            key: value for key, value in rows
            if key in ALLOWED_SETTINGS
        },
    }


@app.put("/api/settings/{guild_id}")
async def save_settings(
    guild_id: int,
    payload: dict,
    x_vantahq_key: str | None = Header(default=None),
):
    require_dashboard_key(x_vantahq_key)
    require_guild(guild_id)

    settings = payload.get("settings")

    if not isinstance(settings, dict) or not settings:
        raise HTTPException(
            status_code=400,
            detail="Provide a non-empty settings object.",
        )

    unknown = set(settings) - ALLOWED_SETTINGS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Unsupported settings: " + ", ".join(sorted(unknown)),
        )

    async with aiosqlite.connect(DATABASE_PATH) as db:
        for key, value in settings.items():
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be text or a numeric ID.",
                )

            value = str(value).strip()

            if len(value) > 32 or (value and not value.isdigit()):
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be a numeric Discord ID.",
                )

            await db.execute(
                """
                INSERT INTO settings(guild_id, key, value)
                VALUES(?, ?, ?)
                ON CONFLICT(guild_id, key)
                DO UPDATE SET value = excluded.value
                """,
                (guild_id, key, value),
            )

        await db.commit()

    return {
        "ok": True,
        "guild_id": str(guild_id),
        "saved": sorted(settings),
    }
