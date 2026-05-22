from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import DEV_TOKEN, PORT
from .db import init_db
from .errors import envelope, ns_error_response
from .routers import auth as auth_router
from .routers import journalentry as je_router
from .routers import records as records_router
from .routers import suiteql as suiteql_router
from .routers import ui as ui_router
from .routers import vendorbill as vb_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="MiniSuite",
    description=(
        "Mock NetSuite REST API for the Ridgeline Foods freight-accrual demo "
        "(Finance Engineer Cup). The base path and payload shapes mirror real NetSuite "
        "REST so a client can swap host + token to repoint at a real account."
    ),
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_router.router)
app.include_router(je_router.router)
app.include_router(vb_router.router)
app.include_router(records_router.router)
app.include_router(suiteql_router.router)
app.include_router(ui_router.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "o:errorDetails" in exc.detail:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    if request.url.path.startswith("/services/"):
        return ns_error_response(exc.status_code, str(exc.detail), "USER_ERROR")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return ns_error_response(400, msg or "Invalid request.", "USER_ERROR")


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    if request.url.path.startswith("/services/"):
        return ns_error_response(500, f"Internal error: {exc}", "UNEXPECTED_ERROR")
    raise exc


@app.on_event("startup")
def _startup():
    init_db()


if __name__ == "__main__":
    import uvicorn
    print(f"MiniSuite listening on http://127.0.0.1:{PORT}")
    print(f"  Swagger:    http://127.0.0.1:{PORT}/docs")
    print(f"  UI:         http://127.0.0.1:{PORT}/")
    print(f"  Bearer:     {DEV_TOKEN}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)
