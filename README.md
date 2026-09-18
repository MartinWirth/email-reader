# Email Reader

A small, self-hosted email reader built with Python and FastAPI. It connects to an IMAP mailbox, lists messages, searches the inbox, and renders readable message content without storing mailbox credentials or email data on disk.

## Features

- IMAP over TLS
- Inbox listing with sender, subject and date
- Full-text search through the IMAP server
- Message detail view
- Plain-text extraction from HTML messages
- Attachment metadata
- Total email size including attachments
- Sortable and resizable email-list columns
- Environment-based configuration
- No mailbox data persisted by the application

## Requirements

- Python 3.11+
- An IMAP-enabled mailbox
- VS Code with the Python and Python Debugger extensions (optional, for debugging)

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

## Restart

```bash
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Development workflow

Before starting or restarting the application, pull the latest changes from GitHub:

```bash
git pull
```

After pulling, start or restart the FastAPI debugger so the running application uses the latest code.

## Debugging with VS Code

The repository contains a VS Code debug configuration in `.vscode/launch.json`.

1. Open the repository in VS Code.
2. Make sure the virtual environment is selected as the Python interpreter.
3. Set a breakpoint in `app/main.py` or `app/imap_client.py`.
4. Open **Run and Debug** and select **Debug FastAPI**.
5. Start the debugger with **F5**.
6. Open http://127.0.0.1:8000 in your browser.

The debug configuration starts Uvicorn as a Python module:

```text
python -m uvicorn app.main:app
```

It deliberately does **not** use `--reload`, because the reload process can make debugger breakpoints harder to follow. Stop the debugger and start it again after code changes.

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
