# Email Reader

A small, self-hosted email reader built with Python and FastAPI. It connects to an IMAP mailbox, lists messages, searches the inbox, and renders readable message content without storing mailbox credentials or email data on disk.

## Features

- IMAP over TLS
- Inbox listing with sender, subject and date
- Full-text search through the IMAP server
- Message detail view
- Plain-text extraction from HTML messages
- Attachment metadata
- Environment-based configuration
- No mailbox data persisted by the application

## Requirements

- Python 3.11+
- An IMAP-enabled mailbox

## Quick start

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Configuration

Set these variables in `.env`:

```text
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USERNAME=you@example.com
IMAP_PASSWORD=your-password
IMAP_FOLDER=INBOX
IMAP_TIMEOUT=15
```

For Gmail, use an App Password when 2-Step Verification is enabled; do not put your normal account password into source code.

## API

- `GET /` — web interface
- `GET /api/emails?limit=25` — recent inbox messages
- `GET /api/emails/search?q=invoice&limit=25` — IMAP search
- `GET /api/emails/{uid}` — message details
- `GET /health` — health check

## Security

This is intended as a local/self-hosted application. Do not expose it directly to the public internet without authentication, HTTPS, and appropriate access controls. Keep `.env` out of Git.

## License

MIT
