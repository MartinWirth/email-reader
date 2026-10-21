import os
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from .imap_client import Mailbox

load_dotenv()
DEBUG_MODE=os.getenv('EMAIL_READER_DEBUG','').lower() in ('1','true','yes','on')
logging.basicConfig(level=logging.DEBUG if DEBUG_MODE else logging.INFO)
logger=logging.getLogger('email_reader.api')

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Email Reader", version="0.1.0", lifespan=lifespan)


def mailbox():
    try:
        return Mailbox()
    except KeyError as exc:
        raise HTTPException(500, f"Missing environment variable: {exc.args[0]}")


@app.middleware('http')
async def log_requests(request, call_next):
    started=time.monotonic()
    if DEBUG_MODE:
        logger.debug('Request started: %s',request.url.path)
    response=await call_next(request)
    if DEBUG_MODE:
        logger.debug('Request finished: %s status=%s elapsed_ms=%d',request.url.path,response.status_code,int((time.monotonic()-started)*1000))
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/folders")
def folders():
    return mailbox().list_folders()


@app.get("/api/emails")
def emails(folder: str | None = Query(None), limit: int = Query(25, ge=1, le=100)):
    return mailbox().list_messages(limit=limit, folder=folder)


@app.get("/api/emails/search")
def search(q: str = Query(..., min_length=1), folder: str | None = Query(None), limit: int = Query(25, ge=1, le=100)):
    return mailbox().list_messages(limit=limit, search=q, folder=folder)


class TrashRequest(BaseModel):
    folder: str
    uids: list[str] = Field(min_length=1, max_length=100)


@app.post("/api/emails/trash")
def trash_emails(request: TrashRequest):
    try:
        return mailbox().move_to_trash(request.uids, folder=request.folder)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/emails/restore")
def restore_emails(request: TrashRequest):
    try:
        return mailbox().restore_from_trash(request.uids, folder=request.folder)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/emails/restore-available")
def restore_available(folder: str = Query(...)):
    try:
        return mailbox().restore_available(folder)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


class RestoreFolderRequest(BaseModel):
    folder: str


@app.post("/api/emails/restore-folder")
def restore_folder(request: RestoreFolderRequest):
    try:
        return mailbox().restore_to_folder(request.folder)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/emails/{uid}")
def email_detail(uid: str, folder: str | None = Query(None)):
    result = mailbox().get_message(uid, folder=folder)
    if result is None:
        raise HTTPException(404, "Email not found")
    return result


@app.get("/", response_class=HTMLResponse)
def index():
    return Path(os.path.join(os.path.dirname(__file__), "static", "index.html")).read_text(encoding="utf-8")
