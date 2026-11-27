"""One transaction class for every context; each use case sees it through its own protocol."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUowTransaction

from penaria.features.core.registry.infra.repository import PostgresEntityRepository
from penaria.features.support.documents.infra.repository import PostgresFileRepository
from penaria.features.support.identity.infra.mail_repositories import (
    PostgresAccountLinkRepository,
    PostgresInstallSettingsRepository,
    PostgresMailRepository,
)
from penaria.features.support.identity.infra.repositories import (
    PostgresChallengeRepository,
    PostgresExternalIdentityRepository,
    PostgresFailureRepository,
    PostgresGrantRepository,
    PostgresHomeRepository,
    PostgresInvitationRepository,
    PostgresOidcFlowRepository,
    PostgresPasskeyRepository,
    PostgresPasswordRepository,
    PostgresPendingSignInRepository,
    PostgresRoleRepository,
    PostgresSessionRepository,
    PostgresSetupTokenRepository,
    PostgresTokenRepository,
    PostgresTotpRepository,
    PostgresUserRepository,
)
from penaria.features.support.platform.infra.journal import PostgresJournal


class PenariaTransaction(AsyncSQLAlchemyUowTransaction):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._users = PostgresUserRepository(session)
        self._passwords = PostgresPasswordRepository(session)
        self._sessions = PostgresSessionRepository(session)
        self._passkeys = PostgresPasskeyRepository(session)
        self._challenges = PostgresChallengeRepository(session)
        self._totp = PostgresTotpRepository(session)
        self._pending_sign_ins = PostgresPendingSignInRepository(session)
        self._setup_tokens = PostgresSetupTokenRepository(session)
        self._failures = PostgresFailureRepository(session)
        self._homes = PostgresHomeRepository(session)
        self._roles = PostgresRoleRepository(session)
        self._grants = PostgresGrantRepository(session)
        self._invitations = PostgresInvitationRepository(session)
        self._tokens = PostgresTokenRepository(session)
        self._install_settings = PostgresInstallSettingsRepository(session)
        self._mail = PostgresMailRepository(session)
        self._account_links = PostgresAccountLinkRepository(session)
        self._external_identities = PostgresExternalIdentityRepository(session)
        self._oidc_flows = PostgresOidcFlowRepository(session)
        self._entities = PostgresEntityRepository(session)
        self._files = PostgresFileRepository(session)
        self._journal = PostgresJournal(session)

    @property
    def users(self) -> PostgresUserRepository:
        return self._users

    @property
    def passwords(self) -> PostgresPasswordRepository:
        return self._passwords

    @property
    def sessions(self) -> PostgresSessionRepository:
        return self._sessions

    @property
    def passkeys(self) -> PostgresPasskeyRepository:
        return self._passkeys

    @property
    def challenges(self) -> PostgresChallengeRepository:
        return self._challenges

    @property
    def totp(self) -> PostgresTotpRepository:
        return self._totp

    @property
    def pending_sign_ins(self) -> PostgresPendingSignInRepository:
        return self._pending_sign_ins

    @property
    def setup_tokens(self) -> PostgresSetupTokenRepository:
        return self._setup_tokens

    @property
    def failures(self) -> PostgresFailureRepository:
        return self._failures

    @property
    def homes(self) -> PostgresHomeRepository:
        return self._homes

    @property
    def roles(self) -> PostgresRoleRepository:
        return self._roles

    @property
    def grants(self) -> PostgresGrantRepository:
        return self._grants

    @property
    def invitations(self) -> PostgresInvitationRepository:
        return self._invitations

    @property
    def tokens(self) -> PostgresTokenRepository:
        return self._tokens

    @property
    def install_settings(self) -> PostgresInstallSettingsRepository:
        return self._install_settings

    @property
    def mail(self) -> PostgresMailRepository:
        return self._mail

    @property
    def account_links(self) -> PostgresAccountLinkRepository:
        return self._account_links

    @property
    def external_identities(self) -> PostgresExternalIdentityRepository:
        return self._external_identities

    @property
    def oidc_flows(self) -> PostgresOidcFlowRepository:
        return self._oidc_flows

    @property
    def entities(self) -> PostgresEntityRepository:
        return self._entities

    @property
    def files(self) -> PostgresFileRepository:
        return self._files

    @property
    def journal(self) -> PostgresJournal:
        return self._journal
