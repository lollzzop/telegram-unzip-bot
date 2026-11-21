import os
import tempfile
import zipfile
from pathlib import Path

import py7zr
import rarfile

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]

MAX_DOWNLOAD = 20 * 1024 * 1024  # 20 MB Bot API limit
MAX_EXTRACT = 500 * 1024 * 1024  # 500 MB safety limit
MAX_FILES = 100

ALLOWED = {".zip", ".rar", ".7z"}


def safe_path(root, name):
    target = (root / name).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError("Unsafe archive path detected")
    return target


def extract_zip(archive, folder):
    files = []

    with zipfile.ZipFile(archive) as z:
        total = 0

        for item in z.infolist():
            if item.is_dir():
                continue

            total += item.file_size

            if total > MAX_EXTRACT:
                raise ValueError("Extracted data is too large")

            if len(files) >= MAX_FILES:
                raise ValueError("Too many files in archive")

            destination = safe_path(folder, item.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)

            with z.open(item) as src, open(destination, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)

            files.append(destination)

    return files


def extract_archive(archive, folder):
    ext = archive.suffix.lower()

    if ext == ".zip":
        return extract_zip(archive, folder)

    if ext == ".7z":
        with py7zr.SevenZipFile(archive, mode="r") as z:
            names = z.getnames()
            if len(names) > MAX_FILES:
                raise ValueError("Too many files in archive")
            for name in names:
                safe_path(folder, name)
            z.extractall(path=folder)

    elif ext == ".rar":
        with rarfile.RarFile(archive) as r:
            names = r.namelist()
            if len(names) > MAX_FILES:
                raise ValueError("Too many files in archive")
            for name in names:
                safe_path(folder, name)
            r.extractall(path=folder)

    else:
        raise ValueError("Unsupported archive")

    files = [p for p in folder.rglob("*") if p.is_file()]

    total = sum(p.stat().st_size for p in files)
    if total > MAX_EXTRACT:
        raise ValueError("Extracted data is too large")

    return files


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\nSend ZIP, RAR or 7z file and I will extract it."
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    if not doc:
        return

    filename = doc.file_name or "archive.zip"

    if Path(filename).suffix.lower() not in ALLOWED:
        await update.message.reply_text("❌ Send ZIP, RAR or 7z only.")
        return

    if doc.file_size and doc.file_size > MAX_DOWNLOAD:
        await update.message.reply_text("❌ File is too large (20 MB max).")
        return

    msg = await update.message.reply_text("⏳ Extracting...")

    try:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / filename
            output = root / "extracted"
            output.mkdir()

            tgfile = await context.bot.get_file(doc.file_id)
            await tgfile.download_to_drive(str(archive))

            files = extract_archive(archive, output)

            if not files:
                await msg.edit_text("Archive is empty.")
                return

            await msg.edit_text(f"✅ Extracted {len(files)} file(s). Sending...")

            sent = 0

            for file in files:
                if file.stat().st_size > 49 * 1024 * 1024:
                    await update.message.reply_text(
                        f"⚠️ Skipped large file: {file.name}"
                    )
                    continue

                try:
                    with file.open("rb") as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=f,
                            filename=file.name,
                        )
                    sent += 1

                except Exception as e:
                    await update.message.reply_text(
                        f"Failed: {file.name} ({e})"
                    )

            await msg.edit_text(f"🎉 Done! Sent {sent}/{len(files)} files.")

    except Exception as e:
        await msg.edit_text(f"❌ Extraction failed: {e}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.run_polling()


if __name__ == "__main__":
    main()
