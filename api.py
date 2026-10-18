
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="VantaHQ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shaontop.github.io",
    ],
    allow_methods=["GET"],
    allow_headers=["GET"],
)

bot_client = None


def set_bot(bot):
    global bot_client
    bot_client = bot


@app.get("/api/status")
async def status():
    connected = (
        bot_client is not None
        and bot_client.is_ready()
    )

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
