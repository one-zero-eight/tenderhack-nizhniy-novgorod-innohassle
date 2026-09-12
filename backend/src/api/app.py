from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_derive_responses import AutoDeriveResponsesAPIRoute
from fastapi_swagger import patch_fastapi

import src.api.logging_  # noqa: F401
from src.api.lifespan import lifespan
from src.api.repositories.admin import router as admin_router
from src.api.repositories.auth import router as auth_router
from src.api.repositories.chats import router as chats_router
from src.api.repositories.ml_assets import router as ml_assets_router
from src.api.repositories.ping import router as ping_router
from src.api.repositories.support import router as support_router
from src.config import api_settings
from src.config_schema import ApiSettings


def create_app(settings: ApiSettings) -> FastAPI:
    app = FastAPI(
        title="TenderHack Support API",
        version="0.1.0",
        docs_url=None,
        swagger_ui_oauth2_redirect_url=None,
        root_path=settings.app_root_path,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.router.route_class = AutoDeriveResponsesAPIRoute
    patch_fastapi(app)
    for router in (ping_router, auth_router, chats_router, support_router, admin_router, ml_assets_router):
        app.include_router(router)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app(api_settings)
