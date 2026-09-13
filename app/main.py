import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from .imap_client import Mailbox

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Email Reader", version="0.1.0", lifespan=lifespan)


def mailbox():
    try:
        return Mailbox()
    except KeyError as exc:
        raise HTTPException(500, f"Missing environment variable: {exc.args[0]}")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/emails")
def emails(limit: int = Query(25, ge=1, le=100)):
    return mailbox().list_messages(limit=limit)


@app.get("/api/emails/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(25, ge=1, le=100)):
    return mailbox().list_messages(limit=limit, search=q)


@app.get("/api/emails/{uid}")
def email_detail(uid: str):
    result = mailbox().get_message(uid)
    if result is None:
        raise HTTPException(404, "Email not found")
    return result


@app.get("/", response_class=HTMLResponse)
def index():
    return Path(os.path.join(os.path.dirname(__file__), "static", "index.html")).read_text(encoding="utf-8")
