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

- `merge` (no `--chat`) took 1 min 54 s; the 64-digit key decrypted the template.

```
chats: 362 (new: 249), messages added: 136657, already there: 0, integrity: ok
ready: out/msgstore.db.crypt15
```

- Round-trip check passed. `out/msgstore.db.crypt15` is 8170820 bytes (plain merged db 19124224 bytes).
- 136657 added = 126593 text + 10064 placeholders. The other 4161 iPhone messages (system or other types) were not carried over.
- Template before merge: 133 chats (105 groups, 28 `@lid` one-to-one), 345 messages, from WhatsApp syncing groups at registration. So 113 iPhone chats matched an existing chat and 249 were added.
- Merged: 382 chats (126 groups, 190 `@lid`, 66 `@s.whatsapp.net`), 137002 messages.
- Thing to check after restore: 1:1 chats now use two ID types (`@lid` and phone number). A contact could show up as two separate chats.
- Before `pm clear`: adb lost the phone twice. The Mac saw the Samsung on USB, but only its file-transfer and modem connections, with no debugging connection. Cause: Samsung Auto Blocker ("Block commands by USB cable") was on. With it off, adb worked again.
- `adb shell pm clear com.whatsapp`: `Success`, 15:26.
- `pm clear` on Android 17 also emptied `Android/media/com.whatsapp/WhatsApp/Databases/`. Both phone backups were gone before the push, so `android-push` had nothing to move to `Databases.before-wamigrate/`. The template survives in `work/` and `archive/`, but the README's "the phone's backups are moved aside" doesn't hold on this phone.
- `android-push`: exit 0. The phone's `Databases/` now holds only `msgstore.db.crypt15` (8170820 bytes), and its SHA-256 matches `out/msgstore.db.crypt15`.

### First restore (15:3x): worked, but incomplete display

- The restore succeeded. Owner's report: `[Photo]` placeholders show (expected, since media isn't migrated), and "some of the newer messages are not displayed".
- Cause, found in the merged db (counts only), was two bugs in `merge()`:
  1. **Stale chat pointers.** WhatsApp seeds 105 chats at registration (104 groups, 1 one-to-one) with system messages (type 7), some dated years back. `merge()` updated `last_message_row_id`, `display_message_row_id`, `last_read_message_row_id`, their sort ids and `sort_timestamp` only for chats with **no** Android messages. In these 105 chats, about 48,000 migrated messages were newer than the chat's last-message pointer.
  2. **Hidden chats.** 27 one-to-one `@lid` chats in the template had `hidden=1`. iPhone chats were merged into them unchanged, so about 4,800 messages sat in invisible chats.
- Fix (commit after this note): every chat that gets iPhone messages is unhidden, and its pointers move to the newest iPhone message unless the Android already has a newer one. Messages that are already there count too, so rerunning `merge` on a backup of a migrated phone repairs the pointers. Two tests were added; 12 pass. The new test fails on the old code.
- Rebuilt `out/msgstore.db.crypt15` from the same 14:30 template. Stats are unchanged (`chats: 362 (new: 249), messages added: 136657, already there: 0, integrity: ok`). Migrated messages newer than their chat pointer: 0. In hidden chats: 0. Pointer sort-id mismatches: 0. The 134 remaining type-7 system messages after their chat pointers are the same as in WhatsApp's own template.
- The first push is kept as `out/first-push.db.crypt15`.

### Second push (corrected backup)

- `pm clear`: `Success`. `android-push`: exit 0 at 15:48. The phone holds only `msgstore.db.crypt15` (8170802 bytes, built 15:41), and its SHA-256 matches `out/msgstore.db.crypt15`.
- Second restore (about 15:50): no error message, but **one-to-one chats (DMs) don't show**. Afterwards the pushed file is still on the phone, unchanged (8170802 bytes), and WhatsApp is still 2.26.41.77. Stopped here; nothing retried.
- Diff of the first and second pushed dbs: the same 382 chats and the same messages. The only differences are pointer and `sort_timestamp` changes in 98 chats (95 groups, 3 `@lid`) and `hidden` cleared on 5 `@lid` chats. So the fix barely touched DMs. DMs were probably missing after the first restore too, which would be the "newer messages not displayed" report.
- Every DM chat in the merged db (162 `@lid`, 66 `@s.whatsapp.net`) was created by `merge()`. Compared with the 133 chats WhatsApp created itself, ours have no `account_jid_row_id` (WhatsApp sets it equal to `jid_row_id` on every chat), no `chat_encryption_state` (WhatsApp uses 2 on 129 of 133 chats), and no `lid_chat_state` row (WhatsApp has one for 26 of its 28 `@lid` chats). The 21 groups we created have the same gaps. `chat_view` coalesces `account_jid_row_id` back to `jid_row_id`, so that column alone may not hide them. This is a hypothesis; it hasn't been confirmed on the phone.
- adb dropped again before `logcat` could be read.
- Owner's answers: **all** DMs were missing, all groups were visible, and **DMs did show after the first restore**. WhatsApp has since reset. The owner suspects setup didn't complete. This fits the evidence better than the missing-fields hypothesis: the DM rows are near-identical in both pushes and showed the first time. Groups are visible anyway because WhatsApp syncs the group list from the server, and DMs only exist in the restored history. Most likely the restore didn't finish, so the plan is to clear, re-push the same corrected backup and restore again, letting it finish.

### Third push (same corrected backup)

- Before this, the Mac saw no USB device at all; a different cable or port fixed it. `pm clear`: `Success`. `android-push`: exit 0 at 16:57. The phone holds only `msgstore.db.crypt15` (8170802 bytes), and its SHA-256 matches `out/msgstore.db.crypt15`.

- Third restore (about 17:00): the chat list loads with groups, DMs and older chats dated back to September. Owner reports "an error in the sync" (text not captured) and that contact **names are gone**, so DMs show as phone numbers.
- Cause of the missing names: `pm clear` also resets runtime permissions, and WhatsApp's `READ_CONTACTS` is now `granted=false`. The phone itself has 824 contacts. Names come from the address book, not from the backup, so the fix is to grant Contacts again and refresh. No new push or SMS code needed.
- `logcat` (16:51 to 17:04, read at the owner's request): no restore, database or crash errors from WhatsApp. At 16:58:17 WhatsApp opened the system permission dialog, which closed about 1.6 s later, and `READ_CONTACTS` was still `granted=false` at 17:04. Android's SyncManager logged `SYNC_OP_STATE_INVALID: NOT_SYNCABLE` at 17:04, consistent with WhatsApp's contact sync being off without the permission. The log copy was deleted after reading.

- The owner says the migrated messages are **not there** after this setup either. The WhatsApp screens in `logcat` explain why: `EULA` → `waffle.sso.ui.LinkedUsersActivity` (sign-in through a linked Meta account) → `HomeActivity` → `backup.google.GoogleDriveNewUserSetupActivity`. No phone-number verification screen and **no restore screen** appeared. Signing in through the linked account skips the local-backup restore. The chats in the list are groups synced from the server plus messages delivered since. The pushed backup is still untouched on the phone (8170802 bytes, 15:41). The second restore (DMs missing) was probably the same.
- Lesson for the runbook: at setup, don't use the linked-account or "Continue as" sign-in. Verify by phone number and SMS so that WhatsApp looks for the local backup and offers **Restore**.

### Next attempt: fresh template

- The owner chose to keep the Android's messages from today: take a fresh 64-digit backup, re-merge the iPhone chats into it, then clear and restore by SMS. Set aside first (all gitignored): `work/backup-key-1430.txt`, `work/template-1430.db.crypt15` (also in `archive/`) and `out/corrected-1541.db.crypt15`.

## Wrap-up
