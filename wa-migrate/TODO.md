# Migration checklist

Run from the `wa-migrate` folder. **HUMAN** marks a step only the owner can do. Everything else is Claude's. Record outcomes in `RESULTS.md` as you go. Rules are in `CLAUDE.md`.

## Phase 0: set up the computer

- [x] Check that `git branch --show-current` is `kdx/vigilant-newton-7qkjjn` and run `git pull`.
- [x] Check that Python is 3.10 or newer, and note the OS (macOS or Windows) in `RESULTS.md`.
- [x] Create `.venv`, activate it, and run `pip install -r requirements.txt`.
- [x] Run `python -m pytest -q tests`. All tests must pass before going on.
- [x] Check `adb version`. If it's missing, install Android platform-tools. On macOS use `brew install android-platform-tools`. On Windows, download it from developer.android.com and add it to PATH. Ask the owner before installing.

## Phase 1: save every message from the iPhone

- [x] **HUMAN:** back up the iPhone to this computer. On a Mac, use Finder > iPhone > "Back up all of the data on your iPhone to this Mac" > Back Up Now. On Windows, use the Apple Devices app or iTunes > Back Up Now. Don't delete or re-verify WhatsApp on the iPhone.
- [x] **HUMAN, only if the backup is encrypted:** create `work/iphone-backup-password.txt` with the password on one line, using a text editor.
- [x] **HUMAN, macOS only:** give Full Disk Access to the app Claude runs in (Terminal, iTerm or VS Code; for the Claude desktop app, both Claude and its bundled `claude-code/<version>/<id>/claude.app`). It's under System Settings > Privacy & Security > Full Disk Access. Restart that app afterwards. Without this, the backup folder can't be read.
- [x] Run `python wamigrate.py ios-extract` (add `--media` to bring photos, videos and files). Check that the device name and backup date it prints are this iPhone and today. If several backups are listed and the newest isn't the right one, rerun with `--backup <folder>`.
- [x] Run `python wamigrate.py ios-inspect --summary` and copy the output into `RESULTS.md`.
- [x] Ask the owner where to keep a permanent copy, outside the repo. The default is `~/WhatsApp-iPhone-archive/`. Copy `work/ChatStorage.sqlite` there as `ChatStorage-<YYYY-MM-DD>.sqlite`.
- [x] Make a readable archive in the same folder. Run `pip install whatsapp-chat-exporter`, then `wtsexporter -i -d work/ChatStorage.sqlite -o <archive>/html`. Tell the owner to open `<archive>/html` in a browser and check it. Note that it's text only.
- [x] Run `python wamigrate.py ios-inspect`. With the owner, pick a **test chat**: one-to-one, 50 to 500 messages, mostly text. Record only "1:1, N messages" in `RESULTS.md`, not the name.
  - 2026-10-23: the owner chose no test chat. The full merge is the test, so Phase 3 is skipped.
- [x] Commit and push `RESULTS.md` and `TODO.md`.

## Phase 2: Android template backup

- [x] **HUMAN:** install WhatsApp on the Android and verify your number. Skip any restore it offers.
- [x] **HUMAN:** in WhatsApp, go to Settings > Chats > Chat backup:
  - Set "Back up to Google Account" to **Never**.
  - Tap End-to-end encrypted backup > Turn on > **Use 64-digit encryption key instead** > Generate. Save the key in a password manager.
  - Create `work/backup-key.txt` with the 64 characters on one line.
  - Tap **Back up**.
- [x] **HUMAN:** turn on USB debugging. Go to Settings > About phone and tap Build number 7 times. Then go to Developer options and turn on USB debugging. Plug the phone in and accept the prompt.
- [x] Run `adb devices` and confirm exactly one device is listed.
- [x] Record the following in `RESULTS.md`:
  - Phone model: `adb shell getprop ro.product.model`
  - Android version: `adb shell getprop ro.build.version.release`
  - WhatsApp version: `adb shell dumpsys package com.whatsapp | grep versionName`
- [x] Run `python wamigrate.py android-pull`. Copy `work/template.db.crypt15` into the archive folder. It's the undo point.
- [x] Commit and push.

## Phase 3: trial with one chat

**Skipped (owner's choice, 2026-10-23).** Phase 4 is the test. If it fails, use the undo steps at the end of this phase.

- [ ] Run `python wamigrate.py merge --chat "<test chat>"` and record the stats line in `RESULTS.md`. It must end with `integrity: ok` and `ready:`.
- [ ] Ask the owner for approval, then run `adb shell pm clear com.whatsapp`. This wipes WhatsApp on the Android. Its chats are already inside the file about to be restored.
- [ ] Ask the owner for approval, then run `python wamigrate.py android-push`.
- [ ] **HUMAN:** open WhatsApp, verify the number, tap **Restore**, and enter the 64-digit key. Tell Claude exactly what the screens said.
- [ ] **HUMAN:** check the test chat:
  - Messages are in the right order.
  - Your messages are on the right side.
  - Dates are right.
  - The count roughly matches the trial.
- [ ] Record the outcome in `RESULTS.md`, then commit and push.
  - **If it worked**, go to Phase 4.
  - **If it failed**, undo it. Run `pm clear` (with approval), then `python wamigrate.py android-push work/template.db.crypt15`, then have the owner restore. Record the error and stop.

## Phase 4: full run (only if Phase 3 worked, or Phase 3 was skipped)

- [x] Run `python wamigrate.py merge` with no `--chat`, and record the stats line.
- [x] Ask the owner for approval, then run `adb shell pm clear com.whatsapp` and `python wamigrate.py android-push`.
- [x] **HUMAN:** restore as in Phase 3, then spot-check 3 to 5 chats, including one group.
- [x] Record the outcome, then commit and push.

## Phase 5: clean up

- [ ] Ask before deleting, then delete `work/` and `out/`. This includes both secret files and all unencrypted copies. The archive folder stays.
- [ ] **HUMAN:** turn off USB debugging on the Android.
- [ ] **HUMAN:** once happy, consider setting WhatsApp Google Drive backup back to daily.
- [ ] Write a short wrap-up in `RESULTS.md`: what worked, what was missing, and what to build next (media is the likely next step). Then commit and push.
