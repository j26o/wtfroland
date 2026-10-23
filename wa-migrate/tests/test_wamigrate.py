import importlib.util
import plistlib
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wamigrate  # noqa: E402

APPLE = wamigrate.APPLE_EPOCH
T0 = 1_700_000_000  # unix seconds, Nov 2023


def ios_date(unix_s):
    return unix_s - APPLE


@pytest.fixture
def ios_db(tmp_path):
    p = tmp_path / "ChatStorage.sqlite"
    db = sqlite3.connect(p)
    db.executescript("""
        CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID TEXT, ZPARTNERNAME TEXT,
                                     ZSESSIONTYPE INTEGER, ZARCHIVED INTEGER);
        CREATE TABLE ZWAGROUPMEMBER (Z_PK INTEGER PRIMARY KEY, ZMEMBERJID TEXT, ZCONTACTNAME TEXT, ZCHATSESSION INTEGER);
        CREATE TABLE ZWAMEDIAITEM (Z_PK INTEGER PRIMARY KEY, ZMESSAGE INTEGER, ZTITLE TEXT, ZLATITUDE REAL,
                                   ZLONGITUDE REAL, ZVCARDNAME TEXT);
        CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER, ZSTANZAID TEXT,
                                 ZGROUPMEMBER INTEGER, ZFROMJID TEXT, ZMESSAGEDATE REAL, ZTEXT TEXT,
                                 ZSTARRED INTEGER, ZMESSAGETYPE INTEGER, ZMEDIAITEM INTEGER);
    """)
    db.executemany("INSERT INTO ZWACHATSESSION VALUES (?,?,?,?,?)", [
        (1, "6591110000@s.whatsapp.net", "Mum", 0, 0),
        (2, "120363000000000001@g.us", "Family", 1, 0),
        (3, "status@broadcast", "Status", 3, 0),
        (4, "6592220000@s.whatsapp.net", "Existing friend", 0, 0),
    ])
    db.executemany("INSERT INTO ZWAGROUPMEMBER VALUES (?,?,?,?)", [
        (1, "6591110000@s.whatsapp.net", "Mum", 2),
        (2, "6593330000@s.whatsapp.net", "Dad", 2),
    ])
    db.executemany("INSERT INTO ZWAMEDIAITEM VALUES (?,?,?,?,?,?)", [
        (1, 4, "beach day", None, None, None),
        (2, 5, None, 1.29, 103.85, None),
    ])
    db.executemany("INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (1, 1, 0, "A1", None, "6591110000@s.whatsapp.net", ios_date(T0 + 10), "hi dear", 0, 0, None),
        (2, 1, 1, "A2", None, None, ios_date(T0 + 20), "hi mum", 1, 0, None),
        (3, 2, 0, "G1", 2, "120363000000000001@g.us", ios_date(T0 + 30), "dinner?", 0, 0, None),
        (4, 2, 1, "G2", None, None, ios_date(T0 + 40), None, 0, 1, 1),
        (5, 1, 0, "A3", None, None, ios_date(T0 + 50), None, 0, 5, 2),
        (6, 3, 0, "S1", None, None, ios_date(T0 + 60), "status post", 0, 0, None),
        (7, 1, 0, "A4", None, None, ios_date(T0 + 70), None, 0, 6, None),   # system event: skipped
        (8, 4, 0, "E1", None, None, ios_date(T0 + 5), "old hello", 0, 7, None),
    ])
    db.commit()
    db.close()
    return p


@pytest.fixture
def android_db(tmp_path):
    p = tmp_path / "msgstore.db"
    db = sqlite3.connect(p)
    db.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, server TEXT NOT NULL,
                          agent INTEGER, device INTEGER, type INTEGER, raw_string TEXT);
        CREATE UNIQUE INDEX jid_key_new_index ON jid (user, server, agent, device);
        CREATE TABLE jid_map (lid_row_id INTEGER PRIMARY KEY, jid_row_id INTEGER);
        CREATE TABLE chat (_id INTEGER PRIMARY KEY AUTOINCREMENT, jid_row_id INTEGER UNIQUE, hidden INTEGER,
                           subject TEXT, created_timestamp INTEGER, display_message_row_id INTEGER,
                           last_message_row_id INTEGER, last_read_message_row_id INTEGER,
                           last_read_message_sort_id INTEGER, display_message_sort_id INTEGER,
                           last_message_sort_id INTEGER, archived INTEGER, sort_timestamp INTEGER,
                           unseen_message_count INTEGER, unseen_row_count INTEGER);
        CREATE TABLE message (_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_row_id INTEGER NOT NULL,
                              from_me INTEGER NOT NULL, key_id TEXT NOT NULL, sender_jid_row_id INTEGER,
                              status INTEGER, broadcast INTEGER, recipient_count INTEGER, participant_hash TEXT,
                              origination_flags INTEGER, origin INTEGER, timestamp INTEGER,
                              received_timestamp INTEGER, receipt_server_timestamp INTEGER,
                              message_type INTEGER, text_data TEXT, starred INTEGER, lookup_tables INTEGER,
                              sort_id INTEGER NOT NULL DEFAULT 0);
        CREATE UNIQUE INDEX message_key_index ON message (chat_row_id, from_me, key_id);
        CREATE UNIQUE INDEX message_sort_id_index ON message (sort_id);
    """)
    db.executemany("INSERT INTO jid(_id,user,server,agent,device,type,raw_string) VALUES (?,?,?,?,?,?,?)", [
        (1, "6599990000", "s.whatsapp.net", 0, 0, 7, "6599990000@s.whatsapp.net"),  # me
        (2, "6592220000", "s.whatsapp.net", 0, 0, 0, "6592220000@s.whatsapp.net"),
        (3, "6593330000", "s.whatsapp.net", 0, 0, 0, "6593330000@s.whatsapp.net"),
        (4, "88880000", "lid", 0, 0, 18, "88880000@lid"),
    ])
    db.execute("INSERT INTO jid_map VALUES (4, 3)")  # Dad's phone jid -> lid
    db.execute("INSERT INTO chat(_id, jid_row_id, hidden, created_timestamp, display_message_row_id, "
               "last_message_row_id, last_read_message_row_id, last_read_message_sort_id, display_message_sort_id, "
               "last_message_sort_id, archived, sort_timestamp) VALUES (1,2,0,?,1,1,1,1,1,1,0,?)",
               ((T0 + 100) * 1000, (T0 + 100) * 1000))
    db.execute("INSERT INTO message(_id, chat_row_id, from_me, key_id, status, timestamp, message_type, text_data, "
               "sort_id) VALUES (1,1,0,'NEW1',0,?,0,'sent after switching',1)", ((T0 + 100) * 1000,))
    db.commit()
    db.close()
    return p


def rows(p, sql, args=()):
    db = sqlite3.connect(p)
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def test_merge_adds_chats_and_messages(ios_db, android_db):
    stats = wamigrate.merge(ios_db, android_db)
    assert stats["integrity"] == "ok"
    assert stats["chats"] == 3          # Mum, Family, Existing friend (status skipped)
    assert stats["new_chats"] == 2      # Existing friend reuses chat 1
    assert stats["inserted"] == 6       # 3 Mum + 2 Family + 1 friend; system event skipped

    texts = dict(rows(android_db, "SELECT key_id, text_data FROM message"))
    assert texts["G2"] == "[Photo] beach day"
    assert texts["A3"] == "[Location] https://maps.google.com/?q=1.29,103.85"
    assert "S1" not in texts and "A4" not in texts

    # Group sender is stored by Dad's LID, since jid_map knows it.
    assert rows(android_db, "SELECT sender_jid_row_id FROM message WHERE key_id='G1'") == [(4,)]
    # From-me messages have no sender and status 13; starred carries over.
    assert rows(android_db, "SELECT sender_jid_row_id, status, starred FROM message WHERE key_id='A2'") == [(0, 13, 1)]
    # Group chat gets its subject.
    assert rows(android_db, "SELECT subject FROM chat c JOIN jid j ON j._id=c.jid_row_id "
                            "WHERE j.raw_string='120363000000000001@g.us'") == [("Family",)]


def test_sort_order_follows_time_and_pointers_are_consistent(ios_db, android_db):
    wamigrate.merge(ios_db, android_db)
    ordered = [k for (k,) in rows(android_db, "SELECT key_id FROM message ORDER BY sort_id")]
    by_time = [k for (k,) in rows(android_db, "SELECT key_id FROM message ORDER BY timestamp, _id")]
    assert ordered == by_time
    assert ordered[0] == "E1" and ordered[-1] == "NEW1"

    # The existing chat still points at its newest message, with a matching sort id.
    assert rows(android_db, "SELECT c.last_message_sort_id = m.sort_id FROM chat c "
                            "JOIN message m ON m._id = c.last_message_row_id WHERE c._id=1") == [(1,)]
    # New chats point at their newest migrated message.
    mum = rows(android_db, "SELECT c.last_message_row_id, c.last_message_sort_id, c.sort_timestamp FROM chat c "
                           "JOIN jid j ON j._id=c.jid_row_id WHERE j.raw_string='6591110000@s.whatsapp.net'")[0]
    newest = rows(android_db, "SELECT _id, sort_id, timestamp FROM message WHERE key_id='A3'")[0]
    assert mum == newest


def test_running_twice_adds_nothing(ios_db, android_db):
    wamigrate.merge(ios_db, android_db)
    again = wamigrate.merge(ios_db, android_db)
    assert again["inserted"] == 0 and again["duplicates"] == 6
    assert rows(android_db, "SELECT COUNT(*) FROM message") == [(7,)]


def test_chat_filter_and_no_placeholders(ios_db, android_db):
    stats = wamigrate.merge(ios_db, android_db, chat_filters=["mum"], placeholders=False)
    assert stats["chats"] == 1
    assert sorted(k for (k,) in rows(android_db, "SELECT key_id FROM message")) == ["A1", "A2", "NEW1"]


def test_failed_merge_leaves_database_untouched(ios_db, android_db, monkeypatch):
    before = rows(android_db, "SELECT * FROM message")
    monkeypatch.setattr(wamigrate, "ios_messages", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        wamigrate.merge(ios_db, android_db)
    assert rows(android_db, "SELECT * FROM message") == before
    assert rows(android_db, "SELECT COUNT(*) FROM chat") == [(1,)]


def test_extract_from_unencrypted_backup(tmp_path, ios_db):
    backup = tmp_path / "backup"
    backup.mkdir()
    with open(backup / "Manifest.plist", "wb") as f:
        plistlib.dump({"IsEncrypted": False}, f)
    file_id = "ab" + "0" * 38
    (backup / "ab").mkdir()
    (backup / "ab" / file_id).write_bytes(ios_db.read_bytes())
    m = sqlite3.connect(backup / "Manifest.db")
    m.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    m.execute("INSERT INTO Files VALUES (?,?,?,1,NULL)", (file_id, wamigrate.WA_DOMAIN, "ChatStorage.sqlite"))
    m.commit()
    m.close()

    out = wamigrate.extract_chatstorage(backup, tmp_path / "work", None)
    assert rows(out, "SELECT COUNT(*) FROM ZWAMESSAGE") == [(8,)]


def test_key_normalisation():
    key = "ab12 " * 16
    assert wamigrate.normalise_key(key) == "ab12" * 16
    with pytest.raises(SystemExit):
        wamigrate.normalise_key("not a key")


@pytest.mark.skipif(importlib.util.find_spec("wa_crypt_tools") is None, reason="wa-crypt-tools not installed")
def test_full_pipeline_through_crypt15(tmp_path, ios_db, android_db):
    key = secrets.token_hex(32)
    template = tmp_path / "template.db.crypt15"
    # Stand-in for the phone's own backup: encrypt the template with default header values.
    subprocess.run([sys.executable, "-m", "wa_crypt_tools.waencrypt", "--jid", "00", key,
                    str(android_db), str(template)], check=True, capture_output=True)

    result = wamigrate.run_merge(ios_db, template, key, tmp_path / "out", [], True)

    check = tmp_path / "check.db"
    subprocess.run([sys.executable, "-m", "wa_crypt_tools.wadecrypt", key, str(result), str(check)],
                   check=True, capture_output=True)
    assert rows(check, "SELECT COUNT(*) FROM message") == [(7,)]
    # Header carried over from the reference, so the files start the same way.
    assert result.read_bytes()[:3] == template.read_bytes()[:3]


def test_secret_lookup_order(tmp_path, monkeypatch):
    f = tmp_path / "key.txt"
    monkeypatch.delenv("WAMIGRATE_KEY", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        wamigrate.secret(None, "WAMIGRATE_KEY", f, "key: ")
    f.write_text("from-file\n")
    assert wamigrate.secret(None, "WAMIGRATE_KEY", f, "key: ") == "from-file"
    monkeypatch.setenv("WAMIGRATE_KEY", "from-env")
    assert wamigrate.secret(None, "WAMIGRATE_KEY", f, "key: ") == "from-env"
    assert wamigrate.secret("from-arg", "WAMIGRATE_KEY", f, "key: ") == "from-arg"


def test_inspect_summary_has_no_names(ios_db, capsys):
    wamigrate.main(["ios-inspect", str(ios_db), "--summary"])
    out = capsys.readouterr().out
    assert "chats: 3 (2 one-to-one, 1 groups)" in out
    assert "2023-11-14 to 2023-11-14" in out
    assert "Mum" not in out and "6591110000" not in out
