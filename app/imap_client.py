import base64
import email
import imaplib
import re
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
import os
import logging
import time
from bs4 import BeautifulSoup, NavigableString


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


def _html_body_with_lists(html: str) -> str:
    """Extract text while preserving HTML ordered and unordered lists."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for item in soup.find_all("li"):
        parent = item.find_parent(["ol", "ul"])
        depth = len(item.find_parents("li"))
        if parent and parent.name == "ol":
            siblings = parent.find_all("li", recursive=False)
            try:
                start = int(parent.get("start", 1))
            except (ValueError, TypeError):
                start = 1
            marker = f"{start + siblings.index(item)}. "
        else:
            marker = "• "
        item.insert(0, NavigableString("  " * depth + marker))
    for tag in soup.find_all(["li", "p", "div", "br", "ul", "ol"]):
        if tag.name == "br":
            tag.replace_with(NavigableString("\n"))
        else:
            tag.append(NavigableString("\n"))
    return "\n".join(line.rstrip() for line in soup.get_text().splitlines() if line.strip()).strip()


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
    if html and BeautifulSoup(html, "html.parser").find(["ul", "ol"]):
        return _html_body_with_lists(html)
    if plain.strip():
        return plain.strip()
    return _html_body_with_lists(html)


def _attachment_count_from_bodystructure(bodystructure: bytes) -> int:
    """Count attachment body parts from an IMAP BODYSTRUCTURE response."""
    return len(re.findall(rb'\("ATTACHMENT"(?:\s|\))', bodystructure, re.IGNORECASE))


logger = logging.getLogger('email_reader.imap')


def _debug(task, started=None, **fields):
    if logger.isEnabledFor(logging.DEBUG):
        duration = f' duration_ms={int((time.monotonic()-started)*1000)}' if started is not None else ''
        details = ' '.join(f'{key}={value}' for key, value in fields.items())
        logger.debug('%s%s %s', task, duration, details)


class Mailbox:
    def __init__(self):
        self.host = os.environ["IMAP_HOST"]
        self.port = int(os.getenv("IMAP_PORT", "993"))
        self.username = os.environ["IMAP_USERNAME"]
        self.password = os.environ["IMAP_PASSWORD"]
        self.folder = os.getenv("IMAP_FOLDER", "INBOX")
        self.timeout = int(os.getenv("IMAP_TIMEOUT", "15"))

    def _connect(self, folder=None):
        started = time.monotonic()
        _debug('IMAP connect start', host=self.host, port=self.port)
        client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        _debug('IMAP TLS connected', started)
        client.login(self.username, self.password)
        _debug('IMAP authenticated', started)
        selected = folder or self.folder
        status, _ = client.select(selected, readonly=True)
        _debug('IMAP folder selected', started, folder=selected)
        if status != "OK":
            client.logout()
            raise RuntimeError(f"Could not select mailbox: {selected}")
        return client

    def _connect_unselected(self):
        started = time.monotonic()
        _debug('IMAP connect start', host=self.host, port=self.port)
        client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        _debug('IMAP TLS connected', started)
        client.login(self.username, self.password)
        _debug('IMAP authenticated', started)
        return client

    def list_folders(self):
        started = time.monotonic()
        _debug('Folder listing start')
        client = self._connect_unselected()
        try:
            _debug('IMAP LIST start')
            status, data = client.list()
            _debug('IMAP LIST completed', started, entries=len(data or []))
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
            _debug('Folder listing completed', started, count=len(folders))
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
        started = time.monotonic()
        _debug('Header listing start', folder=folder or self.folder, limit=limit, search=bool(search))
        client = self._connect(folder)
        try:
            criteria = f'(TEXT "{search.replace(chr(34), "")}")' if search else "ALL"
            _debug('IMAP UID SEARCH start')
            status, data = client.uid("search", None, criteria)
            _debug('IMAP UID SEARCH completed', started)
            if status != "OK":
                return []
            uids = data[0].split()[-limit:][::-1]
            # Fetch headers in batches instead of one IMAP round trip per UID.
            # UID FETCH replies can arrive in any order, so use the UID response field.
            messages_by_uid = {}
            for offset in range(0, len(uids), 50):
                batch = uids[offset:offset + 50]
                _debug('IMAP UID FETCH batch start', count=len(batch))
                status, fetched = client.uid(
                    "fetch", b",".join(batch).decode("ascii"),
                    "(UID BODY.PEEK[HEADER.FIELDS (DATE FROM TO CC SUBJECT MESSAGE-ID)] RFC822.SIZE BODYSTRUCTURE)",
                )
                _debug('IMAP UID FETCH batch completed', started, count=len(batch))
                if status != "OK":
                    raise RuntimeError("Could not fetch email headers")
                for item in fetched:
                    if not isinstance(item, tuple):
                        continue
                    metadata, raw = item
                    uid_match = re.search(rb"\bUID\s+(\d+)\b", metadata, re.IGNORECASE)
                    if not uid_match:
                        continue
                    uid = uid_match.group(1)
                    size_match = re.search(rb"RFC822\.SIZE\s+(\d+)", metadata, re.IGNORECASE)
                    size = int(size_match.group(1)) if size_match else None
                    message = self._parse(uid, raw, size=size)
                    message["attachment_count"] = _attachment_count_from_bodystructure(metadata)
                    messages_by_uid[uid] = message
            messages = [messages_by_uid[uid] for uid in uids if uid in messages_by_uid]
            _debug('Header listing completed', started, count=len(messages))
            return messages
        finally:
            client.logout()

    def move_to_trash(self, uids: list[str], folder: str | None = None):
        """Move messages to the IMAP Trash mailbox without permanent deletion."""
        if not uids or any(not re.fullmatch(r"[1-9][0-9]*", uid) for uid in uids):
            raise ValueError("Invalid message UIDs")
        client = self._connect_unselected()
        try:
            status, folders = client.list()
            if status != "OK":
                raise RuntimeError("Could not list IMAP folders")
            trash = None
            fallback = None
            for entry in folders:
                if not entry:
                    continue
                line = entry.decode("utf-8", errors="replace")
                match = re.match(r'\(([^)]*)\)\s+(?:"[^"]*"|\S+)\s+(.+)$', line)
                if not match:
                    continue
                flags, raw_name = match.groups()
                name = _decode_mailbox_name(raw_name.strip('"'))
                if "\\Trash" in flags.split():
                    trash = raw_name
                    break
                if name.casefold().split("/")[-1] in ("trash", "deleted items", "deleted messages", "papierkorb"):
                    fallback = raw_name
            trash = trash or fallback
            if trash is None:
                raise ValueError("No Trash folder found")
            source = folder or self.folder
            if _decode_mailbox_name(trash.strip('"')).casefold() == source.casefold():
                raise ValueError("Messages are already in Trash")
            status, _ = client.select(source, readonly=False)
            if status != "OK":
                raise RuntimeError("Could not select source folder")
            status, _ = client.uid("MOVE", ",".join(uids), trash)
            if status != "OK":
                raise RuntimeError("IMAP MOVE to Trash failed")
            return {"moved": len(uids), "trash_folder": _decode_mailbox_name(trash.strip('"'))}
        finally:
            client.logout()

    def restore_from_trash(self, uids: list[str], folder: str):
        """Move selected messages from a Trash mailbox back to INBOX."""
        if not uids or any(not re.fullmatch(r"[1-9][0-9]*", uid) for uid in uids):
            raise ValueError("Invalid message UIDs")
        client = self._connect_unselected()
        try:
            status, folders = client.list()
            if status != "OK":
                raise RuntimeError("Could not list IMAP folders")
            trash_names = set()
            for entry in folders:
                if not entry:
                    continue
                match = re.match(r'\\(([^)]*)\\)\\s+(?:"[^"]*"|\\S+)\\s+(.+)
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
, entry.decode("utf-8", errors="replace"))
                if not match:
                    continue
                flags, raw_name = match.groups()
                name = _decode_mailbox_name(raw_name.strip('"'))
                if "\\Trash" in flags.split() or name.casefold().split("/")[-1] in ("trash", "deleted items", "deleted messages", "papierkorb"):
                    trash_names.add(name.casefold())
            if folder.casefold() not in trash_names:
                raise ValueError("Select the Trash folder to restore messages")
            status, _ = client.select(folder, readonly=False)
            if status != "OK":
                raise RuntimeError("Could not select Trash folder")
            status, _ = client.uid("MOVE", ",".join(uids), "INBOX")
            if status != "OK":
                raise RuntimeError("IMAP MOVE to INBOX failed")
            return {"restored": len(uids), "destination_folder": "INBOX"}
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
