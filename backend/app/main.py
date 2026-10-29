import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, ratelimit
from app.config import settings
from app.routers import assistant, blobs, branches, cherrypick, commits, diffs, explore, merges, notes, repos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Kitsune", version="0.1.0", lifespan=lifespan)
app.middleware("http")(ratelimit.middleware)
# Added last so it wraps everything: even a 429 carries CORS headers the browser can read.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (repos, branches, commits, blobs, diffs, cherrypick, merges, notes, explore, assistant):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model_api_configured": bool(settings.model_api_key),
        "ai_offline": settings.ai_offline,
    }
