from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, jobs, library, movies, subs, video_files
from app.api import settings as settings_api
from app.core.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    init_db()
    yield


app = FastAPI(title="subs-manager-ai", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # LAN trust
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(library.router, prefix="/library", tags=["library"])
app.include_router(movies.router, prefix="/movies", tags=["movies"])
# /movies/{id}/subs/upload lives in subs router (needs movie_id in path)
app.include_router(subs.router, tags=["subs"])
app.include_router(video_files.router, tags=["video-files"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(settings_api.router, prefix="/settings", tags=["settings"])
