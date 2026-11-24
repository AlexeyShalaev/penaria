"""What every feature's HTTP routes share."""

from fastapi import Depends
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.actor import Actor


async def _signed_in(scope: UnitScopeDep) -> None:
    # Resolving the actor answers 401 when the request has no open session.
    await scope.get(Actor)


# On a router, makes every route of it answer 401 to a request without a session, before
# anything else, the validation of the body included.
SIGNED_IN = Depends(_signed_in)
