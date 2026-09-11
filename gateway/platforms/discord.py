"""Discord platform adapter.

Uses ``discord.py``. The adapter receives the gateway's ``handle_message``
callback and routes Discord messages through it. Supports markdown and
code-block friendly replies.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DISCORD_MAX_MESSAGE_LENGTH = 2000


class DiscordAdapter:
    """Discord Bot adapter for the Zeloo gateway."""

    def __init__(
        self,
        token: str,
        allowed_users: list[str] | None = None,
        guild_id: str | None = None,
        allowed_guilds: list[str] | None = None,
        allowed_roles: list[str] | None = None,
    ) -> None:
        self._token = token
        self._allowed_users = set(allowed_users) if allowed_users else None
        self._guild_id = guild_id
        self._allowed_guilds = set(allowed_guilds) if allowed_guilds else None
        self._allowed_roles = set(allowed_roles) if allowed_roles else None
        self._client: Any = None
        self._handler: Callable[[str, str, str], str] | None = None

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the Discord bot.

        Args:
            handler: Callback receiving (platform, user_id, message) and
                     returning the assistant's reply string.
        """
        self._handler = handler
        try:
            import discord
        except ImportError:
            logger.error(
                "discord.py is not installed. "
                "Install with: pip install discord"
            )
            raise

        intents = discord.Intents.default()
        intents.message_content = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord adapter logged in as %s", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self._client.user:
                return
            if message.author.bot:
                return

            user_id = str(message.author.id)

            # Access control — guild allow-list
            if self._allowed_guilds is not None and message.guild is not None:
                if str(message.guild.id) not in self._allowed_guilds:
                    return

            # Access control — user allow-list
            if self._allowed_users is not None and user_id not in self._allowed_users:
                await message.channel.send("You are not authorized to use this bot.")
                return

            # Access control — role allow-list
            if self._allowed_roles is not None and message.guild is not None:
                member_roles = {str(r.id) for r in message.author.roles}
                if not (member_roles & self._allowed_roles):
                    await message.channel.send(
                        "You do not have the required role to use this bot."
                    )
                    return

            text = message.content
            attachments: list[str] = []

            # Download any attached files (images, documents, etc.)
            for att in message.attachments:
                try:
                    path = await _download_discord_attachment(att)
                    if att.content_type and att.content_type.startswith("image/"):
                        attachments.append(f"[Image: {path}]")
                    else:
                        attachments.append(f"[File: {path}]")
                except Exception:
                    logger.exception("Failed to download Discord attachment %s", att.filename)

            message_parts: list[str] = []
            if text:
                message_parts.append(text)
            message_parts.extend(attachments)
            if not message_parts:
                return

            combined = "\n".join(message_parts)

            try:
                reply = self._handler("discord", user_id, combined)  # type: ignore[misc]
            except Exception:
                logger.exception("Discord handler failed for user %s", user_id)
                reply = "An internal error occurred. Please try again."

            # Reply to the original message for context threading
            for chunk in _split_message(reply):
                await message.reply(chunk)

        logger.info("Discord adapter starting")
        self._client.run(self._token)

    def stop(self) -> None:
        """Stop the Discord bot."""
        if self._client is not None:
            logger.info("Discord adapter stopping")
            self._client.loop.run_until_complete(self._client.close())


def _split_message(text: str, limit: int = DISCORD_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long message into chunks that fit Discord's limit.

    Tries to break on code-block boundaries and newlines to keep
    markdown formatting intact.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Prefer breaking at a double newline (paragraph boundary)
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            # Fall back to a single newline
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit

        chunk = remaining[:split_at]
        remaining = remaining[split_at:].lstrip("\n")

        # If the chunk breaks inside a fenced code block, close it
        if chunk.count("```") % 2 == 1:
            chunk += "\n```"
            remaining = "```\n" + remaining

        chunks.append(chunk)

    return chunks


async def _download_discord_attachment(attachment: Any) -> str:
    """Download a Discord attachment to a temp file and return its path.

    Args:
        attachment: A ``discord.Attachment`` object.

    Returns:
        Absolute path to the downloaded file.
    """
    import os
    import tempfile

    ext = ""
    dot = attachment.filename.rfind(".")
    if dot != -1:
        ext = attachment.filename[dot:]
    fd, path = tempfile.mkstemp(prefix="disc_", suffix=ext)
    os.close(fd)
    await attachment.save(path)
    return path
