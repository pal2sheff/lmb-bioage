"""Приложение FastAPI. Спецификация OpenAPI доступна по /api/v1/openapi.json."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .routers import admin, attachments, auth, catalog, clinical, frax, patients


def create_app() -> FastAPI:
    app = FastAPI(title="LMB BioAge API", version=__version__, openapi_url="/api/v1/openapi.json",
                  docs_url="/api/v1/docs", redoc_url=None)
    for r in (auth.router, patients.router, clinical.router, frax.router, attachments.router, catalog.router,
              admin.router):
        app.include_router(r, prefix="/api/v1")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # технические подробности не уходят клиенту
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": __version__}

    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI) -> None:
    """Раздача собранного интерфейса (LMB_STATIC_DIR). В рабочем окружении это делает обратный прокси."""
    import os
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    root = os.environ.get("LMB_STATIC_DIR")
    if not root or not Path(root, "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=Path(root, "assets")), name="assets")
    index = Path(root, "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(index, headers={"Cache-Control": "no-store"})


app = create_app()
