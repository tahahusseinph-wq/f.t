"""تطبيق FastAPI الذي يخدم تطبيق الموبايل على الشبكة المحلية."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ftapp import VERSION
from ftapp.api.deps import is_lan_address
from ftapp.api.routers import auth, dashboard, inventory, products, sales, sync, users
from ftapp.services.errors import NotFound, PermissionDenied, ServiceError

log = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def create_app(lan_only: bool = True) -> FastAPI:
    app = FastAPI(title="Farouk Toumma Trading API", version=VERSION, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)

    @app.middleware("http")
    async def lan_guard(request: Request, call_next):
        host = request.client.host if request.client else ""
        if lan_only and not is_lan_address(host):
            return JSONResponse({"detail": "الوصول مسموح من الشبكة المحلية فقط"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        code = 404 if isinstance(exc, NotFound) else 403 if isinstance(exc, PermissionDenied) else 400
        return JSONResponse({"detail": str(exc)}, status_code=code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "بيانات الطلب غير صحيحة", "errors": exc.errors()[:5]}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        log.exception("unhandled API error")
        return JSONResponse({"detail": "حدث خطأ غير متوقع في السيرفر"}, status_code=500)

    for module in (auth, products, dashboard, sales, inventory, users, sync):
        app.include_router(module.router, prefix=API_PREFIX)
    return app
