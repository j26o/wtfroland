# wa-migrate: instructions for Claude

You are driving a WhatsApp iPhone-to-Android migration on the owner's own computer, with their phones attached. Work through `TODO.md` from the top. Tick each box (`- [x]`) as you finish it.

## Hard rules

- **The iPhone backup is read-only.** Never write to, move or delete anything in the MobileSync backup folder.
- **Secrets stay out of the conversation.** The iPhone backup password and the WhatsApp 64-digit key live in `work/iphone-backup-password.txt` and `work/backup-key.txt`, which the owner writes themselves. Never `cat`, print, echo or pass them on a command line. `wamigrate.py` reads them on its own.
- **Don't read chat content.** Use counts and `ios-inspect --summary`. Only show chat names when the owner is choosing a test chat.
- **Nothing personal goes to git.** Only code, `TODO.md` and `RESULTS.md` are committed. `RESULTS.md` holds counts, versions, timings and error text with names and numbers redacted. The repo may be public. `work/` and `out/` are gitignored, so keep it that way.
- **Ask before anything destructive on the phone.** That means `adb shell pm clear com.whatsapp`, `android-push`, and uninstalling anything. Say what will happen and wait for an explicit yes.
- **Steps marked HUMAN are the owner's.** Explain exactly what to tap, then wait for them to say it's done.
- **On failure, stop.** Record the exact error in `RESULTS.md` and use the undo steps in `TODO.md`. Don't hand-edit databases on the phone or retry restores in a loop: every restore costs an SMS verification code, and WhatsApp rate-limits them.

## Working on the code

- `wamigrate.py` is the whole tool. Tests live in `tests/`. Run `python -m pytest -q tests` before and after any change.
- If a fix is needed, keep it small, add a test, and commit it.

## Git

- Work on branch `kdx/vigilant-newton-7qkjjn`. Commit and push after each phase so progress is visible remotely.
- Before committing, check that `git status` shows nothing from `work/` or `out/`.
