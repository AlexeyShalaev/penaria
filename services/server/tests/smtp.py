"""An SMTP server in the test's event loop (aiosmtpd) that keeps what it receives."""

import asyncio
import email
import email.policy
from email.message import EmailMessage
from typing import Any

from aiosmtpd.smtp import SMTP, Envelope, Session


class FakeSmtp:
    """Receives mail on a free local port; ``refuse`` makes it answer every recipient with that reply."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self.refuse: str | None = None
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._server = await loop.create_server(lambda: SMTP(self), "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def handle_RCPT(  # noqa: N802 - aiosmtpd's hook
        self, server: SMTP, session: Session, envelope: Envelope, address: str, options: list[str]
    ) -> str:
        if self.refuse is not None:
            return self.refuse
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:  # noqa: N802 - aiosmtpd's hook
        content: Any = envelope.original_content or envelope.content
        message = email.message_from_bytes(content, policy=email.policy.default)
        assert isinstance(message, EmailMessage)
        self.messages.append(message)
        return "250 OK"

    def mailbox(self) -> dict[str, Any]:
        """The settings of a mailbox on this server, as the install's settings take them."""
        return {"host": "127.0.0.1", "port": self.port, "security": "none", "from_address": "home@example.org"}


def text_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return str(part.get_content())


def html_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("html",))
    assert part is not None
    return str(part.get_content())
