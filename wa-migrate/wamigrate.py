#!/usr/bin/env python3
"""wamigrate: move WhatsApp chat history from an iPhone into WhatsApp on Android.

Prototype. Text messages only; photos, videos, voice notes etc. arrive as a
"[Photo] caption" style line so the conversation still reads correctly.

Pipeline (no root needed):
  1. ios-extract   pull ChatStorage.sqlite out of a Finder/iTunes backup
  2. ios-inspect   list the chats found, so you can pick a test chat
  3. android-pull  fetch the Android phone's own encrypted backup (the "template")
  4. merge         decrypt template, add the iPhone chats, re-encrypt, verify
  5. android-push  put the result back, then restore it inside WhatsApp

The merge logic follows divyarthjain/wa-ios-to-android (MIT), which was tested
against WhatsApp for Android 2.26.40.76. Encryption is done by
ElDavoo/wa-crypt-tools (GPL-3.0), called as a separate program.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

APPLE_EPOCH = 978307200
WA_DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
ANDROID_DB_DIR = "/sdcard/Android/media/com.whatsapp/WhatsApp/Databases"

# iOS ZWACHATSESSION.ZSESSIONTYPE: 0 one-to-one, 1 group, 4 community group.
# Broadcast lists, status and channels are skipped.
CHAT_SESSION_TYPES = (0, 1, 4)
GROUP_SESSION_TYPES = (1, 4)

# iOS ZWAMESSAGE.ZMESSAGETYPE values carried over. 0 is text, 7 is text with a
# link preview. Everything else in this map becomes a one-line placeholder.
TEXT_TYPES = (0, 7)
PLACEHOLDERS = {
    1: "[Photo]",
    2: "[Video]",
    3: "[Audio]",
    4: "[Contact]",
    5: "[Location]",
    8: "[Document]",
    11: "[GIF]",
    15: "[Sticker]",
}

# Android jid.type for ordinary contacts and groups. Type 7 on s.whatsapp.net is
# the account's own jid and must never be created by us.
JID_TYPE = {"s.whatsapp.net": 0, "lid": 18, "g.us": 1}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def secret(value: str | None, env: str, file: Path, prompt: str) -> str:
    """A password or key, from (in order) the command line, an environment variable,
    a one-line file, or an interactive prompt. Files and env vars let an agent run
    the tool without the secret ever appearing in a command or its output."""
    if value:
        return value
    if os.environ.get(env):
        return os.environ[env].strip()
    if file.is_file():
        return file.read_text().strip()
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    die(f"{prompt.rstrip(': ')} needed. Put it on one line in {file}, or set {env}.")


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


# ---------------------------------------------------------------- iPhone side

def default_backup_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Library/Application Support/MobileSync/Backup"]  # macOS
    if os.environ.get("APPDATA"):
        roots.append(Path(os.environ["APPDATA"]) / "Apple Computer/MobileSync/Backup")
    roots.append(home / "Apple/MobileSync/Backup")  # Windows, Microsoft Store iTunes / Apple Devices
    return roots


def find_backups() -> list[tuple[Path, dict]]:
    found = []
    for root in default_backup_roots():
        try:
            entries = list(root.iterdir())
        except PermissionError:
            die(f"cannot read {root}. On macOS, give your Terminal app Full Disk Access in "
                "System Settings > Privacy & Security, then reopen it.")
        except OSError:
            continue
        for d in entries:
            if (d / "Manifest.plist").exists():
                info = {}
                if (d / "Info.plist").exists():
                    with open(d / "Info.plist", "rb") as f:
                        info = plistlib.load(f)
                found.append((d, info))
    found.sort(key=lambda b: (b[0] / "Manifest.plist").stat().st_mtime, reverse=True)
    return found


def extract_chatstorage(backup: Path, out: Path, password: str | None) -> Path:
    with open(backup / "Manifest.plist", "rb") as f:
        manifest = plistlib.load(f)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "ChatStorage.sqlite"
    names = ["ChatStorage.sqlite", "ChatStorage.sqlite-wal", "ChatStorage.sqlite-shm"]

    if manifest.get("IsEncrypted"):
        try:
            from iphone_backup_decrypt import EncryptedBackup
        except ImportError:
            die("this backup is encrypted. Run: pip install iphone_backup_decrypt")
        password = secret(password, "WAMIGRATE_BACKUP_PASSWORD", out / "iphone-backup-password.txt",
                          "iPhone backup password: ")
        eb = EncryptedBackup(backup_directory=str(backup), passphrase=password)
        for name in names:
            try:
                eb.extract_file(relative_path=name, domain_like=WA_DOMAIN, output_filename=str(out / name))
            except Exception:
                if name == names[0]:
                    raise
    else:
        manifest_db = sqlite3.connect(f"file:{backup / 'Manifest.db'}?mode=ro", uri=True)
        for name in names:
            row = manifest_db.execute(
                "SELECT fileID FROM Files WHERE domain=? AND relativePath=?", (WA_DOMAIN, name)).fetchone()
            if row:
                shutil.copyfile(backup / row[0][:2] / row[0], out / name)
        manifest_db.close()

    if not target.exists():
        die("no WhatsApp database in this backup. Is WhatsApp installed on that iPhone, "
            "and was the backup made to this computer (not iCloud)?")
    # Fold any write-ahead log into the main file so we work with one plain file.
    db = sqlite3.connect(target)
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.execute("PRAGMA journal_mode=DELETE")
    db.close()
    for extra in names[1:]:
        (out / extra).unlink(missing_ok=True)
    return target


def ios_chats(ios: sqlite3.Connection) -> list[tuple]:
    return ios.execute(
        "SELECT s.Z_PK, s.ZCONTACTJID, s.ZPARTNERNAME, s.ZSESSIONTYPE, s.ZARCHIVED, "
        "       (SELECT COUNT(*) FROM ZWAMESSAGE m WHERE m.ZCHATSESSION = s.Z_PK) "
        f"FROM ZWACHATSESSION s WHERE s.ZSESSIONTYPE IN {CHAT_SESSION_TYPES} "
        "AND s.ZCONTACTJID IS NOT NULL ORDER BY 6 DESC").fetchall()


def chat_matches(name: str | None, jid: str, filters: list[str]) -> bool:
    if not filters:
        return True
    hay = f"{name or ''} {jid}".lower()
    return any(f.lower() in hay for f in filters)


# --------------------------------------------------------------- the merge

def ios_messages(ios: sqlite3.Connection, session_pks: set[int], placeholders: bool) -> list[tuple]:
    mcols = columns(ios, "ZWAMESSAGE")
    icols = columns(ios, "ZWAMEDIAITEM") if ios.execute(
        "SELECT 1 FROM sqlite_master WHERE name='ZWAMEDIAITEM'").fetchone() else set()

    use_items = bool(icols) and "ZMEDIAITEM" in mcols

    def m(col):
        return f"m.{col}" if col in mcols else "NULL"

    def i(col):
        return f"i.{col}" if use_items and col in icols else "NULL"

    join = "LEFT JOIN ZWAMEDIAITEM i ON i.Z_PK = m.ZMEDIAITEM" if use_items else ""
    types = TEXT_TYPES + (tuple(PLACEHOLDERS) if placeholders else ())
    rows = ios.execute(
        f"SELECT m.Z_PK, m.ZCHATSESSION, m.ZISFROMME, m.ZSTANZAID, {m('ZGROUPMEMBER')}, {m('ZFROMJID')}, "
        f"m.ZMESSAGEDATE, m.ZTEXT, {m('ZSTARRED')}, m.ZMESSAGETYPE, "
        f"{i('ZTITLE')}, {i('ZLATITUDE')}, {i('ZLONGITUDE')}, {i('ZVCARDNAME')} "
        f"FROM ZWAMESSAGE m {join} "
        f"WHERE m.ZMESSAGETYPE IN ({','.join(map(str, types))}) AND m.ZMESSAGEDATE IS NOT NULL "
        "ORDER BY m.ZMESSAGEDATE, m.Z_PK").fetchall()

    out = []
    for (pk, sess, from_me, stanza, gm, from_jid, mdate, text, starred, mtype,
         title, lat, lon, vcard_name) in rows:
        if sess not in session_pks:
            continue
        if mtype in TEXT_TYPES:
            body = text
        else:
            label = PLACEHOLDERS[mtype]
            if mtype == 5 and lat is not None and lon is not None:
                detail = f"https://maps.google.com/?q={lat},{lon}"
            elif mtype == 4:
                detail = vcard_name
            else:
                detail = title or text
            body = f"{label} {detail}" if detail else label
        if not body:
            continue
        out.append((pk, sess, from_me, stanza, gm, from_jid, mdate, body, starred))
    return out


def merge(ios_path: Path, android_path: Path, chat_filters: list[str] | None = None,
          placeholders: bool = True) -> dict:
    """Add iPhone chats to a decrypted Android msgstore.db, in place."""
    ios = sqlite3.connect(f"file:{ios_path}?mode=ro", uri=True)
    db = sqlite3.connect(android_path)
    db.execute("PRAGMA foreign_keys=OFF")
    cur = db.cursor()
    chat_cols = columns(db, "chat")
    has_jid_map = bool(cur.execute("SELECT 1 FROM sqlite_master WHERE name='jid_map'").fetchone())
    jid_cache: dict[str, int] = {}

    def jid_row(raw: str) -> int:
        if raw in jid_cache:
            return jid_cache[raw]
        r = cur.execute("SELECT _id FROM jid WHERE raw_string=?", (raw,)).fetchone()
        if r is None:
            user, _, server = raw.partition("@")
            cur.execute("INSERT INTO jid(user, server, agent, device, type, raw_string) VALUES (?,?,0,0,?,?)",
                        (user, server, JID_TYPE.get(server, 0), raw))
            r = (cur.lastrowid,)
        jid_cache[raw] = r[0]
        return r[0]

    def linked_rows(jrow: int) -> set[int]:
        rows = {jrow}
        if has_jid_map:
            rows |= {r[0] for r in cur.execute("SELECT lid_row_id FROM jid_map WHERE jid_row_id=?", (jrow,))}
            rows |= {r[0] for r in cur.execute("SELECT jid_row_id FROM jid_map WHERE lid_row_id=?", (jrow,))}
        return rows

    def lid_of(jrow: int) -> int:
        # Current WhatsApp addresses group senders by LID when it knows one.
        if not has_jid_map:
            return jrow
        r = cur.execute("SELECT lid_row_id FROM jid_map WHERE jid_row_id=?", (jrow,)).fetchone()
        return r[0] if r else jrow

    try:
        chats_with_messages = {r[0] for r in cur.execute("SELECT DISTINCT chat_row_id FROM message")}

        sessions = [s for s in ios_chats(ios) if chat_matches(s[2], s[1], chat_filters or [])]
        if not sessions:
            raise SystemExit("error: no iPhone chats matched --chat")
        chat_for_session, created_chats = {}, set()
        session_type = {}
        for pk, raw, name, stype, archived, _ in sessions:
            session_type[pk] = stype
            cands = linked_rows(jid_row(raw))
            existing = cur.execute(
                f"SELECT _id FROM chat WHERE jid_row_id IN ({','.join('?' * len(cands))})", tuple(cands)).fetchone()
            if existing:
                chat_for_session[pk] = existing[0]
                continue
            target = max(cands, key=lambda c: cur.execute("SELECT server='lid' FROM jid WHERE _id=?", (c,)).fetchone()[0])
            cur.execute("INSERT INTO chat(jid_row_id, hidden, subject, archived, created_timestamp, sort_timestamp) "
                        "VALUES (?,0,?,?,0,0)",
                        (target, name if stype in GROUP_SESSION_TYPES else None, int(archived or 0)))
            chat_for_session[pk] = cur.lastrowid
            created_chats.add(cur.lastrowid)

        member_jid = dict(ios.execute("SELECT Z_PK, ZMEMBERJID FROM ZWAGROUPMEMBER"))
        rows = ios_messages(ios, set(chat_for_session), placeholders)

        # Make room: sort_id may be unique, so shift existing rows out of the way first.
        offset = len(rows) + 10
        cur.execute("UPDATE message SET sort_id = sort_id + ? WHERE sort_id > 0", (offset,))
        sort_cols = [c for c in ("last_read_message_sort_id", "display_message_sort_id", "last_message_sort_id",
                                 "last_read_receipt_sent_message_sort_id") if c in chat_cols]
        for col in sort_cols:
            cur.execute(f"UPDATE chat SET {col} = {col} + ? WHERE {col} > 0", (offset,))

        inserted = skipped = 0
        newest: dict[int, tuple[int, int]] = {}
        oldest: dict[int, int] = {}
        for sort_id, (pk, sess, from_me, stanza, gm, from_jid, mdate, text, starred) in enumerate(rows, 1):
            chat = chat_for_session[sess]
            ts = int((mdate + APPLE_EPOCH) * 1000)
            sender = 0
            if not from_me and session_type[sess] in GROUP_SESSION_TYPES:
                raw = member_jid.get(gm) or (from_jid if from_jid and not from_jid.endswith("@g.us") else None)
                sender = lid_of(jid_row(raw)) if raw else 0
            cur.execute(
                "INSERT OR IGNORE INTO message(chat_row_id, from_me, key_id, sender_jid_row_id, status, broadcast, "
                "origin, timestamp, received_timestamp, receipt_server_timestamp, message_type, text_data, starred, "
                "lookup_tables, sort_id) VALUES (?,?,?,?,?,0,0,?,?,-1,0,?,?,0,?)",
                (chat, int(from_me or 0), stanza or f"MIGRATED{pk:012d}", sender, 13 if from_me else 0,
                 ts, ts, text, int(starred or 0), sort_id))
            if cur.rowcount == 0:
                skipped += 1
                continue
            inserted += 1
            newest[chat] = (ts, cur.lastrowid)
            oldest.setdefault(chat, ts)

        # Chats that had no messages on Android: point them at their newest migrated message.
        pointer_cols = [c for c in ("last_message_row_id", "display_message_row_id", "last_read_message_row_id")
                        if c in chat_cols]
        for chat, (ts, mid) in newest.items():
            if chat in chats_with_messages:
                continue
            sets = ", ".join(f"{c}=?" for c in pointer_cols)
            extra = [c for c in ("unseen_message_count", "unseen_row_count") if c in chat_cols]
            sets += "".join(f", {c}=0" for c in extra)
            cur.execute(f"UPDATE chat SET {sets}, sort_timestamp=? WHERE _id=?",
                        (*([mid] * len(pointer_cols)), ts, chat))
            cur.execute("UPDATE chat SET created_timestamp=? WHERE _id=? AND created_timestamp=0", (oldest[chat], chat))

        # Renumber the whole timeline by real time so old and new messages interleave correctly.
        cur.execute("CREATE TEMP TABLE rn AS SELECT _id, row_number() OVER (ORDER BY timestamp, _id) n FROM message")
        cur.execute("UPDATE message SET sort_id = -(SELECT n FROM rn WHERE rn._id = message._id)")
        cur.execute("UPDATE message SET sort_id = -sort_id")
        cur.execute("DROP TABLE rn")
        for row_col, sort_col in (("last_message_row_id", "last_message_sort_id"),
                                  ("display_message_row_id", "display_message_sort_id"),
                                  ("last_read_message_row_id", "last_read_message_sort_id"),
                                  ("last_read_receipt_sent_message_row_id", "last_read_receipt_sent_message_sort_id")):
            if row_col in chat_cols and sort_col in chat_cols:
                cur.execute(f"UPDATE chat SET {sort_col} = (SELECT sort_id FROM message WHERE _id = chat.{row_col}) "
                            f"WHERE {row_col} > 0 AND EXISTS (SELECT 1 FROM message WHERE _id = chat.{row_col})")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        ios.close()

    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    db.execute("PRAGMA journal_mode=DELETE")
    db.close()
    return {"chats": len(chat_for_session), "new_chats": len(created_chats),
            "inserted": inserted, "duplicates": skipped, "integrity": integrity}


# ------------------------------------------------------------ crypt15 wrapper

def normalise_key(raw: str) -> str:
    if Path(raw).is_file():
        return raw  # a key file or screenshot; wa-crypt-tools works out which
    key = re.sub(r"[\s-]", "", raw).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        die("the encryption key should be the 64 characters WhatsApp showed you (0-9 and a-f)")
    return key


def crypt_tool(tool: str, *args: str) -> None:
    proc = subprocess.run([sys.executable, "-m", f"wa_crypt_tools.{tool}", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"{tool} failed:\n{proc.stdout}{proc.stderr}".rstrip())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_merge(ios_db: Path, template: Path, key: str, out: Path, chats: list[str], placeholders: bool) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    plain_template = out / "template.db"
    merged = out / "msgstore.db"
    result = out / "msgstore.db.crypt15"
    verify = out / "verify.db"

    print("1/4 decrypting the Android backup")
    crypt_tool("wadecrypt", "-y", key, str(template), str(plain_template))
    shutil.copyfile(plain_template, merged)

    print("2/4 adding iPhone chats")
    stats = merge(ios_db, merged, chats, placeholders)
    print(f"    chats: {stats['chats']} (new: {stats['new_chats']}), messages added: {stats['inserted']}, "
          f"already there: {stats['duplicates']}, integrity: {stats['integrity']}")
    if stats["integrity"] != "ok":
        die("the merged database failed SQLite's integrity check, so nothing was written")

    # --reference copies the header, IV and compression level from the phone's own
    # backup, so the result looks like something this phone produced.
    print("3/4 encrypting with your key")
    crypt_tool("waencrypt", "-y", "--reference", str(template), key, str(merged), str(result))

    print("4/4 checking the result decrypts back to the same database")
    crypt_tool("wadecrypt", "-y", key, str(result), str(verify))
    if sha256(verify) != sha256(merged):
        die("round-trip check failed: the encrypted file does not decrypt to the merged database")
    verify.unlink()
    print(f"\nready: {result}")
    print(f"note: {plain_template.name} and {merged.name} in {out} hold your chats unencrypted. "
          "Delete them once you are done testing.")
    return result


# ---------------------------------------------------------------- adb helpers

def adb(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    if not shutil.which("adb"):
        die("adb not found. Install Android platform-tools and make sure 'adb' is on your PATH.")
    proc = subprocess.run(["adb", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        die(f"adb {' '.join(args)} failed:\n{proc.stdout}{proc.stderr}".rstrip())
    return proc


def android_pull(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    listing = adb("shell", f"ls -l {ANDROID_DB_DIR}/", check=False).stdout
    print(listing.strip() or f"(nothing in {ANDROID_DB_DIR})")
    if "msgstore.db.crypt15" not in listing:
        die("no msgstore.db.crypt15 on the phone. In WhatsApp go to Settings > Chats > Chat backup, "
            "turn on end-to-end encrypted backup with a 64-digit key, then tap Back up.")
    dest = out / "template.db.crypt15"
    adb("pull", f"{ANDROID_DB_DIR}/msgstore.db.crypt15", str(dest))
    print(f"saved {dest}")


def android_push(crypt: Path) -> None:
    if not crypt.exists():
        die(f"{crypt} not found")
    adb("shell", f"mkdir -p {ANDROID_DB_DIR}")
    listing = adb("shell", f"ls {ANDROID_DB_DIR}/", check=False).stdout.split()
    stale = [f for f in listing if f.startswith("msgstore") and f.endswith(".crypt15")]
    if stale:
        adb("shell", f"mkdir -p {ANDROID_DB_DIR}/../Databases.before-wamigrate")
        for f in stale:
            adb("shell", f"mv {ANDROID_DB_DIR}/{f} {ANDROID_DB_DIR}/../Databases.before-wamigrate/")
        print(f"moved {len(stale)} existing backup file(s) to WhatsApp/Databases.before-wamigrate/")
    adb("push", str(crypt), f"{ANDROID_DB_DIR}/msgstore.db.crypt15")
    print("pushed. Now open WhatsApp, verify your number, tap Restore and enter the 64-digit key.")


# ------------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="wamigrate", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ios-extract", help="pull ChatStorage.sqlite out of an iPhone backup")
    s.add_argument("--backup", type=Path, help="backup folder (default: newest one on this computer)")
    s.add_argument("--password", help="backup password if encrypted (default: work/iphone-backup-password.txt or prompt)")
    s.add_argument("--out", type=Path, default=Path("work"))

    s = sub.add_parser("ios-inspect", help="list the chats in ChatStorage.sqlite")
    s.add_argument("ios_db", type=Path, nargs="?", default=Path("work/ChatStorage.sqlite"))
    s.add_argument("--summary", action="store_true", help="counts only, no names or numbers")

    s = sub.add_parser("android-pull", help="copy the phone's encrypted backup to this computer")
    s.add_argument("--out", type=Path, default=Path("work"))

    s = sub.add_parser("merge", help="build a new encrypted backup with the iPhone chats added")
    s.add_argument("--ios", type=Path, default=Path("work/ChatStorage.sqlite"))
    s.add_argument("--template", type=Path, default=Path("work/template.db.crypt15"))
    s.add_argument("--key", help="64-digit key or key file (default: work/backup-key.txt, $WAMIGRATE_KEY or prompt)")
    s.add_argument("--chat", action="append", default=[],
                   help="only chats whose name or number contains this text (repeatable)")
    s.add_argument("--no-placeholders", action="store_true", help="skip media messages instead of adding [Photo] lines")
    s.add_argument("--out", type=Path, default=Path("out"))

    s = sub.add_parser("android-push", help="put the new backup on the phone, ready to restore")
    s.add_argument("crypt", type=Path, nargs="?", default=Path("out/msgstore.db.crypt15"))

    a = p.parse_args(argv)

    if a.cmd == "ios-extract":
        backup = a.backup
        if backup is None:
            backups = find_backups()
            if not backups:
                die("no iPhone backups found. Back up the iPhone to this computer first (Finder on Mac, "
                    "Apple Devices or iTunes on Windows), or pass --backup.")
            for d, info in backups:
                print(f"  {info.get('Device Name', '?'):<20} {info.get('Last Backup Date', '?')}  {d}")
            backup = backups[0][0]
            print(f"using the newest: {backup}")
        path = extract_chatstorage(backup, a.out, a.password)
        print(f"saved {path}")
    elif a.cmd == "ios-inspect":
        ios = sqlite3.connect(f"file:{a.ios_db}?mode=ro", uri=True)
        chats = ios_chats(ios)
        if a.summary:
            groups = [c for c in chats if c[3] in GROUP_SESSION_TYPES]
            counts = dict(ios.execute("SELECT ZMESSAGETYPE, COUNT(*) FROM ZWAMESSAGE GROUP BY 1"))
            text = sum(counts.get(t, 0) for t in TEXT_TYPES)
            media = sum(counts.get(t, 0) for t in PLACEHOLDERS)
            dates = ios.execute("SELECT MIN(ZMESSAGEDATE), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE").fetchone()
            print(f"chats: {len(chats)} ({len(chats) - len(groups)} one-to-one, {len(groups)} groups)")
            print(f"messages: {sum(counts.values())} total, {text} text, {media} media/other (placeholders)")
            if dates[0] is not None:
                span = [datetime.fromtimestamp(d + APPLE_EPOCH, timezone.utc).date() for d in dates]
                print(f"date range: {span[0]} to {span[1]}")
        else:
            print(f"{'messages':>8}  {'type':<6} name / number")
            for _, jid, name, stype, _, count in chats:
                kind = "group" if stype in GROUP_SESSION_TYPES else "1:1"
                print(f"{count:>8}  {kind:<6} {name or ''}  ({jid})")
            print(f"\n{len(chats)} chats, {sum(c[5] for c in chats)} messages")
    elif a.cmd == "android-pull":
        android_pull(a.out)
    elif a.cmd == "merge":
        key = normalise_key(secret(a.key, "WAMIGRATE_KEY", Path("work/backup-key.txt"),
                                   "64-digit WhatsApp backup key: "))
        for f in (a.ios, a.template):
            if not f.exists():
                die(f"{f} not found")
        run_merge(a.ios, a.template, key, a.out, a.chat, not a.no_placeholders)
    elif a.cmd == "android-push":
        android_push(a.crypt)


if __name__ == "__main__":
    main()
