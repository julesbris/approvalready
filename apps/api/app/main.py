"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import (
    OriginCheckMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.resources import create_resources
from app.modules.assessments.router import router as assessments_router
from app.modules.checklists.router import definitions_router as checklist_definitions_router
from app.modules.checklists.router import router as checklists_router
from app.modules.documents.router import router as documents_router
from app.modules.entities.router import router as entities_router
from app.modules.grants.router import router as grants_router
from app.modules.identity.router import router as auth_router
from app.modules.lookups.router import router as lookups_router
from app.modules.lookups.service import Lookups
from app.modules.marketplace.router import router as marketplace_router
from app.modules.notifications.router import router as notifications_router
from app.modules.projects.router import router as projects_router
from app.modules.questionnaires.router import router as questionnaires_router
from app.modules.regulatory.router import router as sources_router
from app.modules.rentals.router import router as rentals_router
from app.modules.review.router import admin_router as review_admin_router
from app.modules.review.router import customer_router as review_customer_router
from app.modules.review.router import professional_router
from app.modules.rules.router import router as rules_router
from app.modules.sales.router import router as sales_router
from app.modules.tenancy.router import router as tenancy_router
from app.modules.vessels.router import router as vessels_router


def create_app(
    settings: Settings | None = None, lookup_transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.resources = create_resources(settings)
        app.state.lookups = Lookups(settings, lookup_transport)
        try:
            yield
        finally:
            await app.state.lookups.aclose()
            await app.state.resources.close()

    show_docs = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )
    app.state.settings = settings

    # Starlette applies middleware in reverse order of registration: the last added runs
    # first. Request context is outermost so every response (including rejections from the
    # host and CORS checks) carries a request ID and security headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type", "x-csrf-token", "x-request-id"],
        expose_headers=["x-request-id"],
        max_age=600,
    )
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(tenancy_router)
    app.include_router(projects_router)
    app.include_router(entities_router)
    app.include_router(questionnaires_router)
    app.include_router(assessments_router)
    app.include_router(documents_router)
    app.include_router(sources_router)
    app.include_router(rules_router)
    app.include_router(marketplace_router)
    app.include_router(checklist_definitions_router)
    app.include_router(checklists_router)
    app.include_router(vessels_router)
    app.include_router(grants_router)
    app.include_router(lookups_router)
    app.include_router(sales_router)
    app.include_router(rentals_router)
    app.include_router(notifications_router)
    app.include_router(review_customer_router)
    app.include_router(professional_router)
    app.include_router(review_admin_router)
    return app


app = create_app()
