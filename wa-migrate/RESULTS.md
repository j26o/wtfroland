# Results log

Counts, versions, timings and errors only. No names, phone numbers, message text or keys.

## Environment

- Computer OS: macOS 26.6.2 (Apple silicon, Homebrew)
- Python: 3.14.3 (.venv)
- Android model / version: Samsung Galaxy SM-F971B / Android 17
- WhatsApp for Android version: 2.26.41.77 (versionCode 264107700, targetSdk 36)
- iPhone backup encrypted: yes

## Phase 0: setup

- Branch up to date, `pip install -r requirements.txt` OK (wa-crypt-tools 0.2.0 from pinned commit, iphone_backup_decrypt 0.11.2).
- Tests: 10 passed in 2.8s.
- adb: was missing; installed via `brew install android-platform-tools` (adb 1.0.41, platform-tools 37.0.1).

## Phase 1: iPhone extract

- Full Disk Access: granting it to Claude.app alone was not enough. Commands run under the bundled Claude Code app (`~/Library/Application Support/Claude/claude-code/<version>/<id>/claude.app`), which needed its own Full Disk Access entry plus a restart.
- `ios-extract`: one backup found, dated today; finished in about 6 s. The WAL and SHM files were not in the backup.
- Warning from iphone_backup_decrypt: "decrypted 109580288 bytes, iOS claimed 120393728 bytes". The SQLite header matches the file (26753 pages × 4096 = 109580288) and `PRAGMA integrity_check` returns `ok`, so the copy is complete and consistent.
- `ios-inspect --summary`:

```
chats: 362 (234 one-to-one, 128 groups)
messages: 140818 total, 126593 text, 10064 media/other (placeholders)
date range: 2014-07-02 to 2026-10-23
```

- Archive: at the owner's request it lives inside the repo at `wa-migrate/archive/`, which is gitignored (the repo is public). It holds `ChatStorage-2026-10-23.sqlite` (byte-identical to the extract) and `html/`.
- `wtsexporter` 0.13.1 (MIT): 360 contacts, 140818 messages, 29 vCards; 360 chat pages, 365 MB, about 17 s. Text only, no media files.
- Gotcha: `wtsexporter` also writes the vCards into `AppDomainGroup-group.net.whatsapp.WhatsApp.shared/` in the folder it runs from, outside `-o`, and that path was not gitignored. It's now ignored, and the stray copy went to `work/` (an identical copy is in `archive/html/`).

- Test chat: none. The owner chose to skip the one-chat trial and use the full merge as the test (one fewer restore and SMS code). A failure there means stop and undo, as in Phase 3.

## Phase 2: Android template

- `adb devices`: exactly one device, authorized.
- Key file: 64 characters, no extra lines.
- Phone's `Databases/` held two backups: `msgstore-2026-10-23.1.db.crypt15` (336069 bytes, 14:24) and `msgstore.db.crypt15` (285346 bytes, 14:30, the one made after turning on the 64-digit key). `android-pull` took the second.
- `work/template.db.crypt15`: 285346 bytes. The undo copy is in `archive/template-2026-10-23.db.crypt15` (byte-identical).
- The key hasn't been tested against the template yet. `merge` decrypts it first, so a wrong key shows up there before anything touches the phone.

## Phase 3: trial (one chat)

Skipped by the owner's choice; see Phase 1.

## Phase 4: full run

## Wrap-up
