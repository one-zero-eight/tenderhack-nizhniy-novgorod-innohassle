from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_derive_responses import AutoDeriveResponsesAPIRoute
from fastapi_swagger import patch_fastapi

import src.api.logging_  # noqa: F401
from src.api.lifespan import lifespan
from src.api.repositories.ping import router as ping_router
from src.config import api_settings

app = FastAPI(
    docs_url=None, swagger_ui_oauth2_redirect_url=None, root_path=api_settings.app_root_path, lifespan=lifespan
)
app.router.route_class = AutoDeriveResponsesAPIRoute

patch_fastapi(app)

app.include_router(ping_router)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=api_settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
