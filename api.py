
import json
import os
import secrets
import time
from urllib.parse import urlencode

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

app = FastAPI(title="VantaHQ API")

FRONTEND_URL = "https://shaontop.github.io/Vantadashboard/"
DISCORD_API = "https://discord.com/api/v10"
DATABASE_PATH = os.getenv("DATABASE_PATH", "vantahq.sqlite3")
SESSION_LIFETIME = 8 * 60 * 60

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://shaontop.github.io"],
    allow_credentials=True,
    allow_methods=["GET", "PUT", "OPTIONS"],
    allow_headers=["Content-Type"],
)

bot_client = None

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


async def initialize_auth_tables():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_ids TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        await db.commit()


@app.on_event("startup")
async def startup():
    await initialize_auth_tables()


def require_oauth_config():
    client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="Discord OAuth is not configured on the server.",
        )

    return client_id, client_secret


def require_bot_guild(guild_id: int):
    if bot_client is None or not bot_client.is_ready():
        raise HTTPException(status_code=503, detail="Bot is not ready.")

    guild = bot_client.get_guild(guild_id)

    if guild is None:
        raise HTTPException(
            status_code=404,
            detail="VantaHQ is not in this server.",
        )

    return guild


async def get_session(request: Request):
    session_id = request.cookies.get("vantahq_session")

    if not session_id:
        raise HTTPException(status_code=401, detail="Please log in with Discord.")

    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            """
            SELECT user_id, guild_ids, expires_at
            FROM dashboard_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row or row[2] <= int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired. Log in again.")

    return {
        "user_id": row[0],
        "guild_ids": set(json.loads(row[1])),
    }


async def require_managed_guild(request: Request, guild_id: int):
    session = await get_session(request)

    if str(guild_id) not in session["guild_ids"]:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to manage this server.",
        )

    guild = require_bot_guild(guild_id)
    return session, guild


@app.get("/auth/login")
async def login():
    client_id, _ = require_oauth_config()
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": client_id,
        "redirect_uri": "https://vantahq-api.onrender.com/auth/callback",
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
    }

    response = RedirectResponse(
        f"https://discord.com/oauth2/authorize?{urlencode(params)}",
        status_code=302,
    )

    response.set_cookie(
        "vantahq_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )

    return response


@app.get("/auth/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None):
    if not code or not state:
        raise HTTPException(status_code=400, detail="Discord login was cancelled or failed.")

    saved_state = request.cookies.get("vantahq_oauth_state")

    if not saved_state or not secrets.compare_digest(saved_state, state):
        raise HTTPException(status_code=400, detail="Invalid login state. Please try again.")

    client_id, client_secret = require_oauth_config()

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://vantahq-api.onrender.com/auth/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail="Discord could not complete login. Check the OAuth configuration.",
            )

        access_token = token_response.json().get("access_token")

        if not access_token:
            raise HTTPException(status_code=502, detail="Discord did not return a login token.")

        headers = {"Authorization": f"Bearer {access_token}"}

        user_response = await client.get(f"{DISCORD_API}/users/@me", headers=headers)
        guilds_response = await client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)

    if user_response.status_code != 200 or guilds_response.status_code != 200:
        raise HTTPException(status_code=502, detail="Could not retrieve your Discord account.")

    user = user_response.json()
    discord_guilds = guilds_response.json()

    # Administrator = 0x8; Manage Server = 0x20.
    manageable_guild_ids = [
        str(guild["id"])
        for guild in discord_guilds
        if guild.get("owner") is True
        or (int(guild.get("permissions", "0")) & (0x8 | 0x20)) != 0
    ]

    session_id = secrets.token_urlsafe(48)
    expires_at = int(time.time()) + SESSION_LIFETIME

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM dashboard_sessions WHERE expires_at <= ?",
            (int(time.time()),),
        )
        await db.execute(
            """
            INSERT INTO dashboard_sessions
                (session_id, user_id, guild_ids, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                session_id,
                str(user["id"]),
                json.dumps(manageable_guild_ids),
                expires_at,
            ),
        )
        await db.commit()

    response = RedirectResponse(FRONTEND_URL, status_code=303)

    response.set_cookie(
        "vantahq_session",
        session_id,
        max_age=SESSION_LIFETIME,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    response.delete_cookie(
        "vantahq_oauth_state",
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )

    return response


@app.post("/auth/logout")
async def logout(request: Request):
    session_id = request.cookies.get("vantahq_session")

    if session_id:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "DELETE FROM dashboard_sessions WHERE session_id = ?",
                (session_id,),
            )
            await db.commit()

    response = RedirectResponse(FRONTEND_URL, status_code=303)
    response.delete_cookie(
        "vantahq_session",
        path="/",
        secure=True,
        httponly=True,
        samesite="none",
    )
    return response


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


@app.get("/api/me")
async def me(request: Request):
    session = await get_session(request)
    return {"logged_in": True, "user_id": session["user_id"]}


@app.get("/api/guilds")
async def get_guilds(request: Request):
    session = await get_session(request)

    if bot_client is None or not bot_client.is_ready():
        raise HTTPException(status_code=503, detail="Bot is not ready.")

    return {
        "guilds": [
            {"id": str(guild.id), "name": guild.name}
            for guild in bot_client.guilds
            if str(guild.id) in session["guild_ids"]
        ]
    }


@app.get("/api/settings/{guild_id}")
async def get_settings(guild_id: int, request: Request):
    await require_managed_guild(request, guild_id)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT key, value FROM settings WHERE guild_id = ?",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()

    return {
        "guild_id": str(guild_id),
        "settings": {
            key: value for key, value in rows if key in ALLOWED_SETTINGS
        },
    }


@app.put("/api/settings/{guild_id}")
async def save_settings(guild_id: int, payload: dict, request: Request):
    await require_managed_guild(request, guild_id)

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
                INSERT INTO settings (guild_id, key, value)
                VALUES (?, ?, ?)
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
