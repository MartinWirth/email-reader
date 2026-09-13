import email
import imaplib
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
import os
from bs4 import BeautifulSoup


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            out.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def _decode_mailbox_name(value: str) -> str:
    """Decode an IMAP LIST mailbox name, including modified UTF-7."""
    try:
        return imaplib.IMAP4._decode_utf7(value)
    except (AttributeError, UnicodeError):
        return value


def _body(msg: Message) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if content_type == "text/plain" and not plain:
                plain = text
            elif content_type == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            plain = text if msg.get_content_type() == "text/plain" else ""
            html = text if msg.get_content_type() == "text/html" else ""
    if plain.strip():
        return plain.strip()
    return BeautifulSoup(unescape(html), "html.parser").get_text("\n", strip=True)


class Mailbox:
    def __init__(self):
        self.host = os.environ["IMAP_HOST"]
        self.port = int(os.getenv("IMAP_PORT", "993"))
        self.username = os.environ["IMAP_USERNAME"]
        self.password = os.environ["IMAP_PASSWORD"]
        self.folder = os.getenv("IMAP_FOLDER", "INBOX")
        self.timeout = int(os.getenv("IMAP_TIMEOUT", "15"))

    def _connect(self, select_folder=True):
        client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        client.login(self.username, self.password)
        if select_folder:
            status, _ = client.select(self.folder, readonly=True)
            if status != "OK":
                client.logout()
                raise RuntimeError(f"Could not select mailbox: {self.folder}")
        return client

    def list_folders(self):
        client = self._connect(select_folder=False)
        try:
            status, data = client.list()
            if status != "OK":
                raise RuntimeError("Could not list mailboxes")

            folders = []
            for item in data:
                if not item:
                    continue
                line = item.decode("utf-8", errors="replace")
                # IMAP LIST format: (flags) "delimiter" "mailbox"
                # Use the final quoted/unquoted token as the mailbox name.
                try:
                    prefix, raw_name = line.rsplit(" ", 1)
                    raw_name = raw_name.strip('"')
                    flags_text = prefix.split(" ", 1)[0].strip("()")
                    flags = [flag for flag in flags_text.split() if flag]
                    delimiter = prefix.rsplit(" ", 1)[-1].strip('"')
                    folders.append({
                        "name": _decode_mailbox_name(raw_name),
                        "flags": flags,
                        "delimiter": delimiter,
                    })
                except ValueError:
                    folders.append({"name": _decode_mailbox_name(line), "flags": [], "delimiter": "/"})

            return folders
        finally:
            client.logout()

    def _parse(self, uid: bytes, raw: bytes, include_body=False):
        msg = email.message_from_bytes(raw)
        date = ""
        try:
            date = parsedate_to_datetime(msg.get("Date", "")).isoformat()
        except (TypeError, ValueError, OverflowError):
            date = msg.get("Date", "")
        result = {
            "uid": uid.decode(),
            "subject": _decode(msg.get("Subject")),
            "from": _decode(msg.get("From")),
            "to": _decode(msg.get("To")),
            "date": date,
            "message_id": msg.get("Message-ID", ""),
            "attachments": [
                {"filename": _decode(p.get_filename()), "content_type": p.get_content_type()}
                for p in msg.walk()
                if p.get_content_disposition() == "attachment"
            ],
        }
        if include_body:
            result["body"] = _body(msg)
        return result

    def list_messages(self, limit=25, search=None):
        client = self._connect()
        try:
            criteria = f'(TEXT "{search.replace(chr(34), "")}")' if search else "ALL"
            status, data = client.uid("search", None, criteria)
            if status != "OK":
                return []
            uids = data[0].split()[-limit:][::-1]
            messages = []
            for uid in uids:
                status, fetched = client.uid("fetch", uid, "(BODY.PEEK[HEADER])")
                if status == "OK":
                    raw = b"".join(x[1] for x in fetched if isinstance(x, tuple))
                    messages.append(self._parse(uid, raw))
            return messages
        finally:
            client.logout()

    def get_message(self, uid: str):
        client = self._connect()
        try:
            status, fetched = client.uid("fetch", uid.encode(), "(BODY.PEEK[])")
            if status != "OK":
                return None
            raw = b"".join(x[1] for x in fetched if isinstance(x, tuple))
            return self._parse(uid.encode(), raw, include_body=True)
        finally:
            client.logout()
