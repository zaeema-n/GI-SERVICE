from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core import settings, setup_logging
from src.routers import (
    organisation_router,
    data_router,
    search_router,
    person_router,
    document_router,
)
from src.middleware import ThrottlingMiddleware
from src.utils import http_client
from src.cache import close_cache, connect_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-apply after Uvicorn's dictConfig so worker INFO logs still reach stdout.
    setup_logging()
    # Same lifecycle as HTTP: open shared resources once per worker, close on shutdown
    await http_client.start()
    try:
        await connect_cache()  # Redis connect + wire SingleFlight locks when enabled
        yield
    finally:
        # Always close even if connect_cache() raises (client may exist before PING)
        await close_cache()
        await http_client.close()


app = FastAPI(
    title="GI - Service",
    description="API Adapter to the OpenGIn (Open General Information Network)",
    version="1.0.0",
    lifespan=lifespan,
)

allowed_origins = [
    origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()
]
if not allowed_origins:
    raise ValueError("ALLOWED_ORIGINS is not configured")


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ThrottlingMiddleware)

app.include_router(organisation_router)
app.include_router(data_router)
app.include_router(search_router)
app.include_router(person_router)
app.include_router(document_router)
