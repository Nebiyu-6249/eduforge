from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.builder_routes import router as builder_router
from .api.drafts_routes import router as drafts_router
from .api.grading_routes import router as grading_router
from .api.grading_routes import status_router as grading_status_router
from .api.lms_routes import open_router as lms_open_router
from .api.lms_routes import router as lms_router
from .api.materials_routes import router as materials_router
from .api.routes import router
from .auth import router as auth_router
from .config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="EduForge — AI Teaching Resource & Assessment Support Tool", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,  # SSO session cookie (plan H.1)
        expose_headers=["Content-Disposition"],  # lets the UI read export filenames
    )
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(drafts_router)
    app.include_router(materials_router)
    app.include_router(builder_router)
    app.include_router(grading_status_router)
    app.include_router(grading_router)
    app.include_router(lms_open_router)
    app.include_router(lms_router)
    return app


app = create_app()
