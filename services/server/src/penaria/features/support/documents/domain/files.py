"""A file, its attachments to entities, and who may see it (docs/design/documents.md, 3, 6 and 8)."""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from penaria.features.shared.access import Access, Permission
from penaria.features.shared.errors import ConflictError, InvalidError, NotFoundError
from penaria.features.shared.ids import new_id

NAME_MAX_LENGTH = 255
EXTENSION_MAX_LENGTH = 16
# A removed file can be restored this long, and is then deleted from storage.
TRASH_RETENTION = timedelta(days=30)


class FileKind(StrEnum):
    PHOTO = "photo"
    RECEIPT = "receipt"
    WARRANTY = "warranty"
    MANUAL = "manual"
    OTHER = "other"


# What says what a thing cost needs a permission of its own to be seen.
FINANCIAL_KINDS = frozenset({FileKind.RECEIPT, FileKind.WARRANTY})


class Visibility(StrEnum):
    NORMAL = "normal"
    PRIVATE = "private"
    GUESTS = "guests"


class FileStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class FileFailure(StrEnum):
    """Why a file could not be processed."""

    # Its content is not what its first bytes say, or it is damaged.
    BROKEN = "broken"
    TOO_MANY_PIXELS = "too_many_pixels"
    # A variant of its format whose metadata cannot be removed safely.
    UNSUPPORTED = "unsupported"
    # Processing crashed or took too long every time it was tried.
    PROCESSING_FAILED = "processing_failed"
    # The upload is no longer in storage.
    CONTENT_MISSING = "content_missing"


class FileNotFoundInHomeError(NotFoundError):
    code = "file_not_found"


class InvalidFileError(InvalidError):
    code = "invalid_file"


class NotAPhotoError(InvalidError):
    """A photo is an image whose metadata can be removed: JPEG, PNG, WebP or HEIC."""

    code = "not_a_photo"


class CoverNotAnImageError(InvalidError):
    code = "cover_not_an_image"


class FileNotReadyError(ConflictError):
    """Nothing can be read before the worker has cleaned it."""

    code = "file_processing"


class FileFailedError(ConflictError):
    code = "file_failed"


class FileRemovedError(ConflictError):
    """The file is in the trash: restore it first."""

    code = "file_removed"


class FileNotRemovedError(ConflictError):
    code = "file_not_removed"


JPEG = "image/jpeg"
PNG = "image/png"
WEBP = "image/webp"
HEIC = "image/heic"
PDF = "application/pdf"
# What is uploaded: these images are cleaned of metadata, and HEIC becomes JPEG.
UPLOADED_IMAGES = frozenset({JPEG, PNG, WEBP, HEIC})
# What a ready image is stored as.
STORED_IMAGES = frozenset({JPEG, PNG, WEBP})


def default_visibility(kind: FileKind) -> Visibility:
    return Visibility.GUESTS if kind is FileKind.PHOTO else Visibility.NORMAL


@dataclass(slots=True)
class File:
    home_id: UUID
    kind: FileKind
    visibility: Visibility
    name: str
    # From the content, never from the name or the browser.
    media_type: str
    size: int
    added_by: dict[str, Any]
    created_at: datetime
    status: FileStatus = FileStatus.PROCESSING
    failure: FileFailure | None = None
    sha256: str | None = None
    # Of an image, as it is shown (the orientation applied).
    width: int | None = None
    height: int | None = None
    taken_at: datetime | None = None
    previews: bool = False
    removed_at: datetime | None = None
    # How many times the worker has taken the file.
    attempts: int = 0
    id: UUID = field(default_factory=new_id)

    @classmethod
    def create(
        cls,
        *,
        file_id: UUID,
        home_id: UUID,
        kind: FileKind,
        name: str,
        media_type: str,
        size: int,
        added_by: dict[str, Any],
        now: datetime,
    ) -> File:
        check_kind(kind, media_type)
        return cls(
            id=file_id,
            home_id=home_id,
            kind=kind,
            visibility=default_visibility(kind),
            name=name,
            media_type=media_type,
            size=size,
            added_by=added_by,
            created_at=now,
        )

    @property
    def is_ready_image(self) -> bool:
        """Whether it is a cleaned image: what can be a cover."""
        return self.status is FileStatus.READY and self.media_type in STORED_IMAGES

    @property
    def removed(self) -> bool:
        return self.removed_at is not None

    @property
    def purge_at(self) -> datetime | None:
        return None if self.removed_at is None else self.removed_at + TRASH_RETENTION

    def expired(self, now: datetime) -> bool:
        """Past its time in the trash: gone for everyone, whether the worker has deleted it yet or not."""
        return self.purge_at is not None and self.purge_at <= now

    def ensure_ready(self) -> None:
        """Its content is there to be read only once the worker has cleaned it."""
        if self.status is FileStatus.PROCESSING:
            raise FileNotReadyError(params={"file_id": str(self.id)})
        if self.status is FileStatus.FAILED:
            raise FileFailedError(params={"file_id": str(self.id)})

    def ensure_not_removed(self) -> None:
        if self.removed:
            raise FileRemovedError(params={"file_id": str(self.id)})

    def change(
        self, *, kind: FileKind | None, name: str | None, visibility: Visibility | None
    ) -> dict[str, dict[str, str]]:
        """Change the given fields; return what changed, as the journal records it."""
        self.ensure_not_removed()
        changes: dict[str, dict[str, str]] = {}
        if kind is not None and kind is not self.kind:
            check_kind(kind, self.media_type)
            changes["kind"] = {"from": self.kind.value, "to": kind.value}
            # Documents are shown to guests only when someone says so: a photo that becomes a
            # document stops being shown to them. No change of kind shows a file to more people.
            if visibility is None and self.visibility is Visibility.GUESTS and kind is not FileKind.PHOTO:
                visibility = default_visibility(kind)
            self.kind = kind
        if name is not None and (cleaned := clean_name(name)) != self.name:
            changes["name"] = {"from": self.name, "to": cleaned}
            self.name = cleaned
        if visibility is not None and visibility is not self.visibility:
            changes["visibility"] = {"from": self.visibility.value, "to": visibility.value}
            self.visibility = visibility
        return changes

    def remove(self, now: datetime) -> None:
        self.ensure_not_removed()
        self.removed_at = now

    def restore(self, now: datetime) -> None:
        if not self.removed:
            raise FileNotRemovedError(params={"file_id": str(self.id)})
        if self.expired(now):
            raise FileNotFoundInHomeError(params={"file_id": str(self.id)})
        self.removed_at = None


@dataclass(frozen=True, slots=True)
class Attachment:
    file_id: UUID
    entity_id: UUID
    position: int
    is_cover: bool = False


def check_kind(kind: FileKind, media_type: str) -> None:
    # Photos are shown to guests by default, so a photo is only what can be cleaned of metadata.
    if kind is FileKind.PHOTO and media_type not in UPLOADED_IMAGES:
        raise NotAPhotoError("a photo is a JPEG, PNG, WebP or HEIC image", params={"media_type": media_type})


def permissions_to_see(kind: FileKind, visibility: Visibility) -> list[Permission]:
    """What seeing such a file takes, beyond seeing an entity it is attached to."""
    needed = []
    if visibility is Visibility.PRIVATE:
        needed.append(Permission.ENTITIES_VIEW_PRIVATE)
    if kind in FINANCIAL_KINDS:
        needed.append(Permission.DOCUMENTS_VIEW_FINANCIAL)
    return needed


def sees_every_file(access: Access) -> bool:
    """Whether someone with ``access`` at an entity sees whatever file might be there."""
    return all(shows_to(kind, visibility, access) for kind in FileKind for visibility in Visibility)


def shows_to(kind: FileKind, visibility: Visibility, access: Access) -> bool:
    """Whether someone with ``access`` at an entity whose contents they read sees such a file there."""
    if access.guest_view and visibility is not Visibility.GUESTS:
        return False
    return all(access.can(permission) for permission in permissions_to_see(kind, visibility))


def cover_of(attached: Sequence[tuple[Attachment, File]]) -> UUID | None:
    """The file that stands for an entity, among those its reader sees there: the one chosen as the
    cover, or else the first photo."""
    images = sorted(
        ((attachment, file) for attachment, file in attached if file.is_ready_image and not file.removed),
        key=lambda pair: (pair[0].position, pair[1].id),
    )
    chosen = [file.id for attachment, file in images if attachment.is_cover]
    photos = [file.id for _, file in images if file.kind is FileKind.PHOTO]
    return next(iter(chosen or photos), None)


def clean_name(name: str) -> str:
    """A file's name as people see it and as it is offered for download: the base name, without
    control and direction-override characters, at most 255 characters with the extension kept."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(char for char in base if not unicodedata.category(char).startswith("C")).strip()
    if cleaned in ("", ".", ".."):
        raise InvalidFileError("a file needs a name", params={"field": "name"})
    if len(cleaned) <= NAME_MAX_LENGTH:
        return cleaned
    stem, dot, extension = cleaned.rpartition(".")
    # A longer "extension" is a sentence with a dot in it, not worth keeping at the name's expense.
    if not dot or len(extension) > EXTENSION_MAX_LENGTH:
        return cleaned[:NAME_MAX_LENGTH]
    return f"{stem[: NAME_MAX_LENGTH - len(extension) - 1]}.{extension}"


def stored_type(uploaded: str) -> str:
    """What an upload is kept as: HEIC, which browsers cannot show, becomes JPEG."""
    return JPEG if uploaded == HEIC else uploaded


def name_as_jpeg(name: str) -> str:
    """The name of a HEIC file converted to JPEG."""
    stem, dot, extension = name.rpartition(".")
    return f"{stem}.jpg" if dot and extension.lower() in ("heic", "heif") else name
