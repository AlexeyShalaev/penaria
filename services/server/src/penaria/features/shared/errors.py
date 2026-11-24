"""The kinds of failure every feature reports; the transports turn them into statuses."""

from servicewright import ErrorKind, ServiceError


class UnauthenticatedError(ServiceError):
    """The request carries no valid session; sign in first."""

    kind = ErrorKind.UNAUTHENTICATED
    code = "unauthenticated"


class NotFoundError(ServiceError):
    kind = ErrorKind.NOT_FOUND


class ForbiddenError(ServiceError):
    kind = ErrorKind.FORBIDDEN


class ConflictError(ServiceError):
    kind = ErrorKind.CONFLICT


class InvalidError(ServiceError):
    kind = ErrorKind.INVALID


class TooManyRequestsError(ServiceError):
    kind = ErrorKind.TOO_MANY_REQUESTS


class StaleVersionError(ConflictError):
    """The resource changed since the caller read it; read it again and retry."""

    code = "stale_version"
