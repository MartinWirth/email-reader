import base64
import email
import imaplib
import re
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
    """Decode IMAP modified UTF-7 mailbox names, including common malformed output."""
    result = []
    pos = 0
    while pos < len(value):
        amp = value.find("&", pos)
        if amp < 0:
            result.append(value[pos:])
            break
        result.append(value[pos:amp])
        end = value.find("-", amp + 1)
        if end >= 0:
            encoded = value[amp + 1:end]
            if not encoded:
                result.append("&")
            else:
                result.append(_decode_utf7_segment(encoded, value[amp:end + 1]))
            pos = end + 1
            continue

        # Some servers omit the terminating '-' for a single UTF-16BE code
        # unit, e.g. Entw&APwrfe instead of Entw&APw-rfe.
        remainder = value[amp + 1:]
        if len(remainder) >= 3:
            encoded = remainder[:3]
            try:
                raw = base64.b64decode(encoded + "=", altchars=b",+")
                text = raw.decode("utf-16-be")
                if len(text) == 1 and ord(text) > 127:
                    result.append(text)
                    result.append(remainder[3:])
                    break
            except (ValueError, UnicodeDecodeError):
                pass
        result.append(value[amp:])
        break
    return "".join(result)


def _decode_utf7_segment(encoded: str, original: str) -> str:
    try:
        encoded = encoded.replace(",", "/")
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.b64decode(padded, validate=True)
        return raw.decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return original


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


def _attachment_count_from_bodystructure(bodystructure: bytes) -> int:
    """Count attachment body parts from an IMAP BODYSTRUCTURE response."""
    return len(re.findall(rb'\("ATTACHMENT"(?:\s|\))', bodystructure, re.IGNORECASE))


class Mailbox:
    def __init__(self):
        self.host = os.environ["IMAP_HOST"]
        self.port = int(os.getenv("IMAP_PORT", "993"))
        self.username = os.environ["IMAP_USERNAME"]
        self.password = os.environ["IMAP_PASSWORD"]
        self.folder = os.getenv("IMAP_FOLDER", "INBOX")
        self.timeout = int(os.getenv("IMAP_TIMEOUT", "15"))

    def _connect(self, folder=None):
        client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        client.login(self.username, self.password)
        selected = folder or self.folder
        status, _ = client.select(selected, readonly=True)
        if status != "OK":
            client.logout()
            raise RuntimeError(f"Could not select mailbox: {selected}")
        return client

    def _connect_unselected(self):
        client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        client.login(self.username, self.password)
        return client

    def list_folders(self):
        client = self._connect_unselected()
        try:
            status, data = client.list()
            if status != "OK":
                raise RuntimeError("Could not list mailboxes")
            folders = []
            for item in data:
                if not item:
                    continue
                line = item.decode("utf-8", errors="replace")
                try:
                    prefix, raw_name = line.rsplit(" ", 1)
                    raw_name = raw_name.strip('"')
                    flags_text = prefix.split(" ", 1)[0].strip("()")
                    flags = [flag for flag in flags_text.split() if flag]
                    delimiter = prefix.rsplit(" ", 1)[-1].strip('"')
                    folders.append({"name": _decode_mailbox_name(raw_name), "flags": flags, "delimiter": delimiter})
                except ValueError:
                    folders.append({"name": _decode_mailbox_name(line), "flags": [], "delimiter": "/"})
            return folders
        finally:
            client.logout()

    def _parse(self, uid: bytes, raw: bytes, include_body=False, size=None):
        msg = email.message_from_bytes(raw)
        date = ""
        try:
            dt = parsedate_to_datetime(msg.get("Date", ""))
            date = dt.strftime("%Y-%m-%dT%H:%M")
        except (TypeError, ValueError, OverflowError):
            date = msg.get("Date", "")

        participants = []
        for header in ("From", "To", "Cc"):
            value = _decode(msg.get(header))
            if value and value not in participants:
                participants.append(value)

        attachments = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                payload = part.get_payload(decode=False)
                if isinstance(payload, str):
                    raw_size = len(payload.encode("ascii", errors="replace"))
                elif isinstance(payload, bytes):
                    raw_size = len(payload)
                else:
                    raw_size = 0
                attachments.append({
                    "filename": _decode(part.get_filename()),
                    "content_type": part.get_content_type(),
                    "size": raw_size,
                })

        result = {
            "uid": uid.decode(),
            "subject": _decode(msg.get("Subject")),
            "from": _decode(msg.get("From")),
            "to": _decode(msg.get("To")),
            "involved": ", ".join(participants),
            "date": date,
            "message_id": msg.get("Message-ID", ""),
            "size": size,
            "attachments": attachments,
        }
        if include_body:
            result["body"] = _body(msg)
        return result

    def list_messages(self, limit=25, search=None, folder=None):
        client = self._connect(folder)
        try:
            criteria = f'(TEXT "{search.replace(chr(34), "")}")' if search else "ALL"
            status, data = client.uid("search", None, criteria)
            if status != "OK":
                return []
            uids = data[0].split()[-limit:][::-1]
            messages = []
            for uid in uids:
                status, fetched = client.uid("fetch", uid, "(BODY.PEEK[HEADER] RFC822.SIZE BODYSTRUCTURE)")
                if status == "OK":
                    raw_parts = []
                    size = None
                    attachment_count = 0
                    for item in fetched:
                        if isinstance(item, tuple):
                            raw_parts.append(item[1])
                            match = re.search(rb"RFC822\.SIZE\s+(\d+)", item[0])
                            if match:
                                size = int(match.group(1))
                            attachment_count = _attachment_count_from_bodystructure(item[0])
                        elif isinstance(item, bytes):
                            match = re.search(rb"RFC822\.SIZE\s+(\d+)", item)
                            if match:
                                size = int(match.group(1))
                            attachment_count = max(attachment_count, _attachment_count_from_bodystructure(item))
                    raw = b"".join(raw_parts)
                    message = self._parse(uid, raw, size=size)
                    message["attachment_count"] = attachment_count
                    messages.append(message)
            return messages
        finally:
            client.logout()

    def get_message(self, uid: str, folder=None):
        client = self._connect(folder)
        try:
            status, fetched = client.uid("fetch", uid.encode(), "(BODY.PEEK[] RFC822.SIZE)")
            if status != "OK":
                return None
            raw_parts = []
            size = None
            for item in fetched:
                if isinstance(item, tuple):
                    raw_parts.append(item[1])
                    match = re.search(rb"RFC822\.SIZE\s+(\d+)", item[0])
                    if match:
                        size = int(match.group(1))
                elif isinstance(item, bytes):
                    match = re.search(rb"RFC822\.SIZE\s+(\d+)", item)
                    if match:
                        size = int(match.group(1))
            raw = b"".join(raw_parts)
            return self._parse(uid.encode(), raw, include_body=True, size=size)
        finally:
            client.logout()
