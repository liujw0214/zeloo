"""Telegram platform adapter.

Uses ``python-telegram-bot`` v21.x. The adapter receives the gateway's
``handle_message`` callback and routes Telegram updates through it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter:
    """Telegram Bot adapter for the Zeloo gateway."""

    def __init__(
        self,
        token: str,
        allowed_users: list[str] | None = None,
    ) -> None:
        self._token = token
        self._allowed_users = set(allowed_users) if allowed_users else None
        self._application: Any = None
        self._handler: Callable[[str, str, str], str] | None = None

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the Telegram bot.

        Args:
            handler: Callback receiving (platform, user_id, message) and
                     returning the assistant's reply string.
        """
        self._handler = handler
        try:
            from telegram import Update
            from telegram.ext import (
                ApplicationBuilder,
                ContextTypes,
                MessageHandler,
                filters,
            )
        except ImportError:
            logger.error(
                "python-telegram-bot is not installed. "
                "Install with: pip install python-telegram-bot==21.6"
            )
            raise

        self._application = (
            ApplicationBuilder().token(self._token).build()
        )

        async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if update.effective_message is None or update.effective_user is None:
                return
            user_id = str(update.effective_user.id)

            # Access control
            if self._allowed_users is not None and user_id not in self._allowed_users:
                await update.effective_message.reply_text(
                    "Sorry, you are not authorized to use this bot."
                )
                return

            text = update.effective_message.text or ""
            attachments: list[str] = []

            # Photo attachments (pick the highest-resolution version)
            if update.effective_message.photo:
                photo = update.effective_message.photo[-1]
                try:
                    file_obj = await context.bot.get_file(photo.file_id)
                    path = await _download_telegram_file(file_obj, prefix="tg_photo_")
                    attachments.append(f"[Image: {path}]")
                except Exception:
                    logger.exception("Failed to download Telegram photo")

            # Document / file attachments
            if update.effective_message.document:
                doc = update.effective_message.document
                try:
                    file_obj = await context.bot.get_file(doc.file_id)
                    path = await _download_telegram_file(
                        file_obj, prefix="tg_doc_", suffix=doc.file_name
                    )
                    attachments.append(f"[File: {path}]")
                except Exception:
                    logger.exception("Failed to download Telegram document")

            # Combine text + attachment markers
            message_parts: list[str] = []
            if text:
                message_parts.append(text)
            message_parts.extend(attachments)
            if not message_parts:
                return

            combined = "\n".join(message_parts)

            try:
                reply = self._handler("telegram", user_id, combined)  # type: ignore[misc]
            except Exception:
                logger.exception("Telegram handler failed for user %s", user_id)
                reply = "An internal error occurred. Please try again."

            # Reply to the original message for context threading
            for chunk in _split_message(reply):
                await update.effective_message.reply_text(chunk)

        self._application.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.Document.ALL)
                & ~filters.COMMAND,
                _on_message,
            )
        )

        logger.info("Telegram adapter starting")
        self._application.run_polling(stop_signals=None)

    def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._application is not None:
            logger.info("Telegram adapter stopping")
            self._application.stop()


def _split_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to break at a newline for readability
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def _download_telegram_file(
    file_obj: Any,
    prefix: str = "tg_",
    suffix: str | None = None,
) -> str:
    """Download a Telegram file to a temp path and return the local path.

    Args:
        file_obj: A ``telegram.File`` instance returned by ``bot.get_file``.
        prefix: Prefix for the temp filename.
        suffix: Optional suffix (e.g. original filename). Used to preserve
                the file extension when provided.

    Returns:
        Absolute path to the downloaded file.
    """
    import tempfile

    ext = ""
    if suffix:
        # Keep only the extension part to avoid path traversal
        dot = suffix.rfind(".")
        if dot != -1:
            ext = suffix[dot:]
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=ext)
    import os

    os.close(fd)
    await file_obj.download_to_drive(path)
    return path
