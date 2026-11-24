"""HTTP: the install's settings, for its admins: the mailbox and the mail log (sign-in.md, 9.1)."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query, status
from pydantic import BaseModel, Field
from servicewright.adapters.fastapi import UnitScopeDep

from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.identity.api.account import NAME_INPUT_MAX_LENGTH, PASSWORD_INPUT_MAX_LENGTH
from penaria.features.support.identity.domain.mail import Attempt, FailureReason, LoggedMail, MailKind, MailState
from penaria.features.support.identity.domain.mailbox import (
    EMAIL_MAX_LENGTH,
    HOST_MAX_LENGTH,
    LOGIN_MAX_LENGTH,
    MailboxFields,
    MailboxSource,
    MailSecurity,
)
from penaria.features.support.identity.domain.sessions import CurrentSession
from penaria.features.support.identity.use_cases.install import (
    CheckMailbox,
    GetMailbox,
    ListMail,
    MailboxHealth,
    MailboxView,
    RemoveMailbox,
    ResendMail,
    SaveMailbox,
    SendTestMail,
)

LOG_PAGE = 50

router = APIRouter(prefix="/api/v1/install", tags=["install"], dependencies=[SIGNED_IN])


class MailboxOut(BaseModel):
    source: MailboxSource | None = Field(
        description="environment: PENARIA_MAIL__*, and the fields are locked; interface: saved here; null: mail is off"
    )
    host: str | None
    port: int | None
    security: MailSecurity | None
    username: str | None
    from_address: str | None
    from_name: str | None
    password_set: bool = Field(description="The password is write-only: only whether one is set")

    @classmethod
    def of(cls, view: MailboxView) -> MailboxOut:
        fields = view.fields
        return cls(
            source=view.source,
            host=None if fields is None else fields.host,
            port=None if fields is None else fields.port,
            security=None if fields is None else fields.security,
            username=None if fields is None else fields.username,
            from_address=None if fields is None else fields.from_address,
            from_name=None if fields is None else fields.from_name,
            password_set=view.password_set,
        )


class MailboxIn(BaseModel):
    host: str = Field(min_length=1, max_length=HOST_MAX_LENGTH, examples=["smtp.example.org"])
    port: int = Field(ge=1, le=65535, examples=[587])
    security: MailSecurity
    username: str | None = Field(default=None, max_length=LOGIN_MAX_LENGTH, description="Empty: no sign-in")
    password: str | None = Field(
        default=None,
        max_length=PASSWORD_INPUT_MAX_LENGTH,
        description="Empty or omitted: keep the saved one; required again when the server or the login changes",
    )
    from_address: str = Field(min_length=1, max_length=EMAIL_MAX_LENGTH, examples=["home@example.org"])
    from_name: str | None = Field(default=None, max_length=NAME_INPUT_MAX_LENGTH, examples=["Penaria"])


class TestMailIn(BaseModel):
    to: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH, description="Omit for your own address")


class SendResultOut(BaseModel):
    ok: bool
    error: str | None = Field(description="The server's words, credentials hidden, when it was not sent")
    reason: FailureReason | None
    mail_id: UUID

    @classmethod
    def of(cls, attempt: Attempt) -> SendResultOut:
        failure = attempt.failure
        return cls(
            ok=failure is None,
            error=None if failure is None else failure.describe(),
            reason=None if failure is None else failure.reason,
            mail_id=attempt.mail_id,
        )


class MailboxStatusOut(BaseModel):
    health: MailboxHealth
    error: str | None


class AttemptOut(BaseModel):
    at: datetime
    ok: bool
    reason: FailureReason | None
    smtp_code: int | None
    error: str | None
    duration_ms: int
    manual: bool = Field(description="Sent by an admin: a test or a resend")


class MailOut(BaseModel):
    id: UUID
    kind: MailKind
    to: str
    subject: str
    locale: str
    state: MailState
    created_at: datetime
    next_attempt_at: datetime | None
    resendable: bool = Field(description="Whether it can be sent again now: done, and its link still works")
    attempts: list[AttemptOut] = Field(description="The latest first")

    @classmethod
    def of(cls, logged: LoggedMail, now: datetime) -> MailOut:
        mail = logged.mail
        return cls(
            id=mail.id,
            kind=mail.kind,
            to=mail.to_address,
            subject=mail.subject,
            locale=mail.locale,
            state=mail.state,
            created_at=mail.created_at,
            next_attempt_at=mail.next_attempt_at,
            resendable=mail.state is not MailState.QUEUED and mail.sendable(now),
            attempts=[
                AttemptOut(
                    at=a.at,
                    ok=a.sent,
                    reason=None if a.failure is None else a.failure.reason,
                    smtp_code=None if a.failure is None else a.failure.smtp_code,
                    error=None if a.failure is None else a.failure.text,
                    duration_ms=a.duration_ms,
                    manual=a.by is not None,
                )
                for a in logged.attempts
            ],
        )


@router.get("/mail")
async def get_mailbox(scope: UnitScopeDep) -> MailboxOut:
    return MailboxOut.of(await (await scope.get(GetMailbox)).execute(await scope.get(CurrentSession)))


@router.put("/mail")
async def save_mailbox(body: Annotated[MailboxIn, Body()], scope: UnitScopeDep) -> MailboxOut:
    """Connect the install's mailbox or change it; needs a recent sign-in. Refused when PENARIA_MAIL__* sets it."""
    fields = MailboxFields.check(
        host=body.host,
        port=body.port,
        security=body.security,
        username=body.username,
        from_address=body.from_address,
        from_name=body.from_name,
    )
    view = await (await scope.get(SaveMailbox)).execute(await scope.get(CurrentSession), fields, body.password or None)
    return MailboxOut.of(view)


@router.delete("/mail", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mailbox(scope: UnitScopeDep) -> None:
    """Turn email off; needs a recent sign-in."""
    await (await scope.get(RemoveMailbox)).execute(await scope.get(CurrentSession))


@router.post("/mail:test")
async def send_test_mail(body: Annotated[TestMailIn, Body()], scope: UnitScopeDep) -> SendResultOut:
    """Send a test email through the saved mailbox now; a failure is an answer, not an error."""
    attempt = await (await scope.get(SendTestMail)).execute(await scope.get(CurrentSession), body.to or None)
    return SendResultOut.of(attempt)


@router.get("/mail/status")
async def mailbox_status(scope: UnitScopeDep) -> MailboxStatusOut:
    """Connect to the mailbox and sign in, without sending."""
    result = await (await scope.get(CheckMailbox)).execute(await scope.get(CurrentSession))
    return MailboxStatusOut(health=result.health, error=result.error)


@router.get("/mail/messages")
async def list_mail(
    scope: UnitScopeDep,
    before: Annotated[UUID | None, Query(description="The last mail of the previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = LOG_PAGE,
) -> list[MailOut]:
    """The mail log, the newest first."""
    logged = await (await scope.get(ListMail)).execute(await scope.get(CurrentSession), before=before, limit=limit)
    now = datetime.now(UTC)
    return [MailOut.of(entry, now) for entry in logged]


@router.post("/mail/messages/{mail_id}:resend")
async def resend_mail(mail_id: UUID, scope: UnitScopeDep) -> SendResultOut:
    """Send a mail again now, while its link still works."""
    attempt = await (await scope.get(ResendMail)).execute(await scope.get(CurrentSession), mail_id)
    return SendResultOut.of(attempt)
