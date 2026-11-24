import pytest

from penaria.features.support.identity.domain.secrets import SecretUnreadableError
from penaria.features.support.identity.infra.fernet import FernetSecretBox, derive_key, key_id

pytestmark = pytest.mark.unit

KEY = "the-install-key-of-at-least-32-characters"
OLD_KEY = "the-key-before-the-rotation-of-32-chars"
CELL = "identity_install_settings/secret/mail"


def test_a_sealed_secret_opens_in_the_cell_it_was_sealed_for() -> None:
    box = FernetSecretBox.of(KEY)

    sealed = box.seal("smtp password", bound_to=CELL)

    assert box.open(sealed, bound_to=CELL) == "smtp password"


def test_the_envelope_names_its_version_and_key_and_hides_the_secret() -> None:
    sealed = FernetSecretBox.of(KEY).seal("smtp password", bound_to=CELL)

    version, found_id, token = sealed.split(":", 2)
    assert (version, found_id) == ("pnr1", key_id(derive_key(KEY)))
    assert "smtp password" not in sealed
    assert token


def test_a_secret_moved_to_another_cell_does_not_open() -> None:
    box = FernetSecretBox.of(KEY)
    sealed = box.seal("smtp password", bound_to=CELL)

    with pytest.raises(SecretUnreadableError, match="another record"):
        box.open(sealed, bound_to="identity_mail/content/0190")


def test_a_binding_that_starts_like_another_does_not_open_it() -> None:
    box = FernetSecretBox.of(KEY)
    sealed = box.seal("x", bound_to="identity_mail/content/1")

    with pytest.raises(SecretUnreadableError):
        box.open(sealed, bound_to="identity_mail/content/")


def test_a_damaged_secret_does_not_open() -> None:
    box = FernetSecretBox.of(KEY)
    sealed = box.seal("smtp password", bound_to=CELL)

    with pytest.raises(SecretUnreadableError, match="damaged"):
        box.open(sealed[:-4] + "AAAA", bound_to=CELL)


def test_another_key_does_not_open_it() -> None:
    sealed = FernetSecretBox.of(OLD_KEY).seal("smtp password", bound_to=CELL)

    with pytest.raises(SecretUnreadableError, match="PENARIA_RETIRED_SECRET_KEYS"):
        FernetSecretBox.of(KEY).open(sealed, bound_to=CELL)


def test_a_retired_key_still_opens_what_it_sealed_and_the_new_key_seals() -> None:
    sealed_before = FernetSecretBox.of(OLD_KEY).seal("smtp password", bound_to=CELL)
    rotated = FernetSecretBox.of(KEY, [OLD_KEY])

    opened = rotated.open(sealed_before, bound_to=CELL)
    sealed_after = rotated.seal("smtp password", bound_to=CELL)

    assert opened == "smtp password"
    assert sealed_after.split(":")[1] == key_id(derive_key(KEY))
    assert FernetSecretBox.of(KEY).open(sealed_after, bound_to=CELL) == "smtp password"


def test_something_else_than_an_envelope_does_not_open() -> None:
    with pytest.raises(SecretUnreadableError, match="not an envelope"):
        FernetSecretBox.of(KEY).open("plain text", bound_to=CELL)
