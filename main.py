"""
SABAGeo Land Registry: builds the web app from the modules in the sabageo/ folder.

Start it with:  uvicorn main:app --reload
The names below (DB, find_overlaps, next_code, add_ledger_record, add_removal_record) are
re-exported because ingest_cities.py, reset_dataset.py and the tests use them as main.<name>.
"""
import base64
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from sabageo.config import DB  # noqa: F401
from sabageo.geo import find_overlaps, next_code  # noqa: F401
from sabageo.ledger import add_ledger_record, add_removal_record  # noqa: F401
from sabageo.routes import admin, clients, ledger, pages, payments, paystack, plots, verify

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# CSS and JS live in the static folder
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------- Optional site password (keeps the project private) ----------
@app.middleware("http")
async def site_gate(request: Request, call_next):
    password = os.getenv("SITE_PASSWORD")
    if not password or request.url.path == "/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            _, _, given = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(given, password):
                return await call_next(request)
        except Exception:
            pass
    return PlainTextResponse(
        "Private project. Password needed.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="SABAGeo"'},
    )


for module in (pages, plots, ledger, payments, paystack, clients, verify, admin):
    app.include_router(module.router)
