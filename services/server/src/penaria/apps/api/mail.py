"""The mail loop of the API process: it sends the queued email and forgets what can no longer be sent.

Every api replica runs it; a mail is taken by one of them at a time (use_cases/postman.py). Until the
worker process exists, this is where email leaves the install.
"""

import asyncio
import contextlib
import logging
import math
import time

from servicewright.adapters.builtin import DaemonEntrypoint
from servicewright.core.contracts import UnitScopeProtocol

from penaria.features.support.identity.use_cases.postman import BATCH, Postman

# A reset link asked for is in the mailbox within a few seconds; one indexed query per pass.
POLL_SECONDS = 3
SWEEP_SECONDS = 600

logger = logging.getLogger(__name__)


def build_mail_loop() -> DaemonEntrypoint:
    return DaemonEntrypoint(deliver_mail, kind="mail")


async def deliver_mail(scope: UnitScopeProtocol, stop: asyncio.Event) -> None:
    postman = await scope.get(Postman)
    swept_at = -math.inf
    while not stop.is_set():
        try:
            # A full batch may leave more due: take the next one at once.
            while await postman.deliver_due() == BATCH and not stop.is_set():
                pass
            if time.monotonic() - swept_at >= SWEEP_SECONDS:
                await postman.sweep()
                swept_at = time.monotonic()
        except Exception:
            # The database may be restarting; the API keeps serving and the mail waits for the next pass.
            logger.exception("The mail loop failed; it tries again in %d seconds", POLL_SECONDS)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), POLL_SECONDS)
