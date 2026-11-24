"""PostgreSQL repositories of the install's settings, its mail and the one-time account links."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from penaria.features.support.identity.domain.mail import (
    Attempt,
    Failure,
    FailureReason,
    LoggedMail,
    Mail,
    MailKind,
    MailState,
)
from penaria.features.support.identity.domain.mailbox import MailboxFields, MailSecurity, StoredMailbox
from penaria.features.support.identity.domain.recovery import AccountLink, LinkPurpose
from penaria.features.support.identity.infra.orm import AccountLinkDB, InstallSettingDB, MailAttemptDB, MailDB

MAILBOX_KEY = "mail"


class PostgresInstallSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mailbox(self, *, for_update: bool = False) -> StoredMailbox | None:
        statement = select(InstallSettingDB).where(InstallSettingDB.key == MAILBOX_KEY)
        row = await self._session.scalar(statement.with_for_update() if for_update else statement)
        if row is None:
            return None
        value = row.value
        fields = MailboxFields(
            host=str(value["host"]),
            port=int(str(value["port"])),
            security=MailSecurity(str(value["security"])),
            username=None if value["username"] is None else str(value["username"]),
            from_address=str(value["from_address"]),
            from_name=str(value["from_name"]),
        )
        return StoredMailbox(fields=fields, sealed_password=row.secret)

    async def save_mailbox(self, mailbox: StoredMailbox, by: UUID, now: datetime) -> None:
        fields = mailbox.fields
        value: dict[str, object] = {
            "host": fields.host,
            "port": fields.port,
            "security": fields.security.value,
            "username": fields.username,
            "from_address": fields.from_address,
            "from_name": fields.from_name,
        }
        row = {"value": value, "secret": mailbox.sealed_password, "updated_at": now, "updated_by": by}
        statement = insert(InstallSettingDB).values(key=MAILBOX_KEY, **row)
        await self._session.execute(statement.on_conflict_do_update(index_elements=[InstallSettingDB.key], set_=row))

    async def remove_mailbox(self) -> bool:
        removed = await self._session.scalar(
            delete(InstallSettingDB).where(InstallSettingDB.key == MAILBOX_KEY).returning(InstallSettingDB.key)
        )
        return removed is not None


class PostgresMailRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, mail: Mail) -> None:
        self._session.add(MailDB(id=mail.id, **_mail_fields(mail)))
        # Attempts reference the row; see PostgresHomeRepository.add.
        await self._session.flush()

    async def get(self, mail_id: UUID, *, for_update: bool = False) -> Mail | None:
        statement = select(MailDB).where(MailDB.id == mail_id)
        row = await self._session.scalar(statement.with_for_update() if for_update else statement)
        return None if row is None else _mail(row)

    async def claim_due(self, now: datetime, lease_until: datetime, limit: int) -> list[Mail]:
        due = (
            select(MailDB.id)
            .where(MailDB.state == MailState.QUEUED.value, MailDB.next_attempt_at <= now)
            .order_by(MailDB.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = await self._session.scalars(
            update(MailDB)
            .where(MailDB.id.in_(due))
            .values(next_attempt_at=lease_until)
            .returning(MailDB)
            .execution_options(synchronize_session=False)
        )
        return sorted((_mail(row) for row in rows), key=lambda mail: mail.created_at)

    async def save(self, mail: Mail) -> None:
        await self._session.execute(
            update(MailDB)
            .where(MailDB.id == mail.id)
            .values(
                state=mail.state.value,
                attempts=mail.attempts,
                next_attempt_at=mail.next_attempt_at,
                content=mail.sealed_content,
            )
        )

    async def add_attempt(self, attempt: Attempt) -> None:
        failure = attempt.failure
        self._session.add(
            MailAttemptDB(
                id=attempt.id,
                mail_id=attempt.mail_id,
                at=attempt.at,
                duration_ms=attempt.duration_ms,
                reason=None if failure is None else failure.reason.value,
                smtp_code=None if failure is None else failure.smtp_code,
                error=None if failure is None else failure.text,
                message_id=attempt.message_id,
                next_attempt_at=attempt.next_attempt_at,
                by=attempt.by,
            )
        )

    async def page(self, before: UUID | None, limit: int) -> list[LoggedMail]:
        statement = select(MailDB).order_by(MailDB.created_at.desc(), MailDB.id.desc()).limit(limit)
        if before is not None:
            anchor = select(MailDB.created_at).where(MailDB.id == before).scalar_subquery()
            statement = statement.where(
                (MailDB.created_at < anchor) | ((MailDB.created_at == anchor) & (MailDB.id < before))
            )
        mails = [_mail(row) for row in await self._session.scalars(statement)]
        if not mails:
            return []
        attempts = await self._session.scalars(
            select(MailAttemptDB)
            .where(MailAttemptDB.mail_id.in_([mail.id for mail in mails]))
            .order_by(MailAttemptDB.at.desc(), MailAttemptDB.id.desc())
        )
        by_mail: dict[UUID, list[Attempt]] = {mail.id: [] for mail in mails}
        for row in attempts:
            by_mail[row.mail_id].append(_attempt(row))
        return [LoggedMail(mail=mail, attempts=by_mail[mail.id]) for mail in mails]

    async def forget_content(self, now: datetime) -> None:
        await self._session.execute(
            update(MailDB)
            .where(MailDB.content.is_not(None), MailDB.expires_at <= now, MailDB.state != MailState.QUEUED.value)
            .values(content=None)
        )

    async def delete_created_before(self, cutoff: datetime) -> None:
        await self._session.execute(delete(MailDB).where(MailDB.created_at < cutoff))


class PostgresAccountLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, link: AccountLink) -> None:
        self._session.add(
            AccountLinkDB(
                id=link.id,
                user_id=link.user_id,
                purpose=link.purpose.value,
                token_hash=link.token_hash,
                email=link.email,
                created_at=link.created_at,
                expires_at=link.expires_at,
                used_at=link.used_at,
                created_by=link.created_by,
            )
        )

    async def by_token_hash(
        self, token_hash: bytes, purpose: LinkPurpose, *, for_update: bool = False
    ) -> AccountLink | None:
        statement = select(AccountLinkDB).where(
            AccountLinkDB.token_hash == token_hash, AccountLinkDB.purpose == purpose.value
        )
        row = await self._session.scalar(statement.with_for_update() if for_update else statement)
        if row is None:
            return None
        return AccountLink(
            id=row.id,
            user_id=row.user_id,
            purpose=LinkPurpose(row.purpose),
            token_hash=row.token_hash,
            email=row.email,
            created_at=row.created_at,
            expires_at=row.expires_at,
            used_at=row.used_at,
            created_by=row.created_by,
        )

    async def use(self, link_id: UUID, now: datetime) -> None:
        await self._session.execute(update(AccountLinkDB).where(AccountLinkDB.id == link_id).values(used_at=now))

    async def forget_unused(self, user_id: UUID, purpose: LinkPurpose) -> None:
        await self._session.execute(
            delete(AccountLinkDB).where(
                AccountLinkDB.user_id == user_id,
                AccountLinkDB.purpose == purpose.value,
                AccountLinkDB.used_at.is_(None),
            )
        )

    async def forget_expired(self, now: datetime) -> None:
        await self._session.execute(delete(AccountLinkDB).where(AccountLinkDB.expires_at <= now))


def _mail_fields(mail: Mail) -> dict[str, object]:
    return {
        "kind": mail.kind.value,
        "to_address": mail.to_address,
        "user_id": mail.user_id,
        "locale": mail.locale,
        "subject": mail.subject,
        "content": mail.sealed_content,
        "created_at": mail.created_at,
        "created_by": mail.created_by,
        "expires_at": mail.expires_at,
        "state": mail.state.value,
        "attempts": mail.attempts,
        "next_attempt_at": mail.next_attempt_at,
        "retried": mail.retried,
    }


def _mail(row: MailDB) -> Mail:
    return Mail(
        id=row.id,
        kind=MailKind(row.kind),
        to_address=row.to_address,
        user_id=row.user_id,
        locale=row.locale,
        subject=row.subject,
        sealed_content=row.content,
        created_at=row.created_at,
        created_by=row.created_by,
        expires_at=row.expires_at,
        state=MailState(row.state),
        attempts=row.attempts,
        next_attempt_at=row.next_attempt_at,
        retried=row.retried,
    )


def _attempt(row: MailAttemptDB) -> Attempt:
    failure = (
        None
        if row.reason is None
        else Failure(reason=FailureReason(row.reason), smtp_code=row.smtp_code, text=row.error)
    )
    return Attempt(
        id=row.id,
        mail_id=row.mail_id,
        at=row.at,
        duration_ms=row.duration_ms,
        failure=failure,
        message_id=row.message_id,
        next_attempt_at=row.next_attempt_at,
        by=row.by,
    )
