# wamigrate (prototype)

> Want Claude to run this for you? Open a Claude Code session in this folder and say "work through TODO.md". It follows `CLAUDE.md` and stops whenever it needs you.

Moves WhatsApp chat history from an iPhone into WhatsApp on Android. No root, no factory reset, no paid tools.

**Status:** tested against synthetic databases only. Your first run is the real test. The iPhone is never modified, so the worst case is redoing the Android side.

## How it works

1. Read the chats from a normal iPhone backup on your computer.
2. Take a backup that your Android WhatsApp makes itself, and decrypt it with your 64-digit key.
3. Add the iPhone chats into that backup, sorted by time.
4. Encrypt it again with the same key, then let WhatsApp restore it the normal way.

Because it builds on your phone's own backup, the result matches your exact WhatsApp version. Any chats already on the Android are kept.

## What comes across

| Comes across | Doesn't (yet) |
|---|---|
| Text messages and links, 1:1 and groups | Photos, videos, voice notes and files (you get a `[Photo] caption` line instead) |
| Who sent what in groups | Reactions, polls, edits, quoted replies |
| Original dates and order | Call history, status, broadcast lists, channels |
| Starred messages | |
| Locations (as a map link) and contact names | |

## Before you start

You need:

- A Mac or Windows computer with Python 3.10 or newer.
- Android platform-tools (`adb`):
  - Mac: `brew install android-platform-tools`
  - Windows: download from https://developer.android.com/tools/releases/platform-tools, unzip it, and add the folder to your PATH.
- Cables for both phones.

Set up the tool:

```bash
git clone https://github.com/j26o/wtfroland && cd wtfroland
git checkout kdx/vigilant-newton-7qkjjn
cd wa-migrate
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run every command below from the `wa-migrate` folder.

## Step 1: get the chats off the iPhone

Don't delete WhatsApp from the iPhone, and don't verify your number on it again.

1. Back up the iPhone to your computer (iCloud backups won't work):
   - Mac: in Finder, select the iPhone, choose "Back up all of the data on your iPhone to this Mac", then click **Back Up Now**.
   - Windows: use the Apple Devices app or iTunes and click **Back Up Now**.

   An encrypted backup is fine. You'll be asked for its password, or you can put it on one line in `work/iphone-backup-password.txt`.
2. On a Mac, give Terminal Full Disk Access first. Go to System Settings > Privacy & Security > Full Disk Access, add Terminal, then reopen Terminal. Without this, macOS blocks access to the backup folder.
3. Extract the chats and list them:

   ```bash
   python wamigrate.py ios-extract
   python wamigrate.py ios-inspect
   ```

   Pick one small chat for a trial run, for example a 1:1 chat with a few hundred messages.

## Step 2: make a backup on the Android

1. Install WhatsApp on the Android and verify your number. If it offers to restore anything, skip it.
2. In WhatsApp, go to **Settings > Chats > Chat backup**:
   - Set **Back up to Google Account** to **Never**. This stops WhatsApp offering an older Google Drive backup later instead of ours.
   - Tap **End-to-end encrypted backup > Turn on**, then choose **Use 64-digit encryption key instead** and **Generate**.
   - Save the key in a password manager and take a screenshot. You'll need it twice.
   - Tap **Back up**.
3. Turn on USB debugging. Go to Settings > About phone and tap **Build number** 7 times. Then go to Settings > System > Developer options and turn on **USB debugging**.
4. Plug the Android into the computer and accept the "Allow USB debugging" prompt. `adb devices` should list the phone.
5. Copy the backup over:

   ```bash
   python wamigrate.py android-pull
   ```

   This saves `work/template.db.crypt15`. Keep it. It's also your undo button.

## Step 3: trial run with one chat

```bash
python wamigrate.py merge --chat "Name of the test chat"
```

Type or paste the 64-digit key when asked, or put it on one line in `work/backup-key.txt`. The tool decrypts, merges, encrypts, then checks that the result decrypts back correctly. You get `out/msgstore.db.crypt15`.

Next, restore it:

1. On the Android, go to **Settings > Apps > WhatsApp > Storage > Clear storage**. This wipes WhatsApp on that phone. Its chats are already inside the file we're about to restore.
2. Push the new backup:

   ```bash
   python wamigrate.py android-push
   ```

3. Open WhatsApp, verify your number, tap **Restore**, and enter the 64-digit key.
4. Open the test chat and check it:
   - Messages are in the right order.
   - Each message is on the correct side.
   - Dates are right.
   - In a group, the sender names show.

## Step 4: the full run

If the trial looks right, do the same again without `--chat`. It reuses the original template from step 2:

```bash
python wamigrate.py merge
```

Then clear WhatsApp storage, run `python wamigrate.py android-push`, and restore again.

Each restore needs a new SMS code. WhatsApp makes you wait longer between codes if you ask too often, so don't loop through restores quickly.

## If something goes wrong

**WhatsApp doesn't offer to restore, or offers a Google Drive backup instead**
- Check that the file is on the phone: `adb shell ls -l /sdcard/Android/media/com.whatsapp/WhatsApp/Databases/`
- If a Drive backup exists for your number, delete it at drive.google.com > Storage > Backups, then clear storage and push again.

**The restore fails, or WhatsApp crashes**
- Undo with: Clear storage, then `python wamigrate.py android-push work/template.db.crypt15`, then restore. You're back to where you started.
- Note the exact error message so it can be fixed.

**"adb: no devices"**
- Unlock the phone and accept the USB debugging prompt.
- Set the USB mode to File transfer.

**Wrong key**
- The key is 64 characters of 0–9 and a–f. Spaces don't matter. A single typo is usually corrected automatically.

## Privacy

Everything runs on your computer. Nothing is uploaded anywhere.

`work/` and `out/` hold your chats, some of them unencrypted. Delete both folders when you're done. They're gitignored so they can't be committed by accident.

## Credits

- The merge logic follows [divyarthjain/wa-ios-to-android](https://github.com/divyarthjain/wa-ios-to-android) (MIT).
- Encryption uses [ElDavoo/wa-crypt-tools](https://github.com/ElDavoo/wa-crypt-tools) (GPL-3.0).
- Encrypted iPhone backups use [iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt).

This tool isn't affiliated with WhatsApp or Meta. Use it only on your own account.
