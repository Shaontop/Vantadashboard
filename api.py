

import os
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

@app.get("/api/status")
async def status():
    return {
        "status": "API online",
        "bot": "VantaHQ",
        "connected": False,
        "message": "API is running; Discord bot connection is next."
    }

