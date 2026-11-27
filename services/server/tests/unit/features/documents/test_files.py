"""The domain's rules of files: what their content is, what they are called and who sees them."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from penaria.features.shared.access import Access
from penaria.features.support.documents.domain.content import sniff
from penaria.features.support.documents.domain.files import (
    Attachment,
    File,
    FileKind,
    FileStatus,
    InvalidFileError,
    Visibility,
    clean_name,
    cover_of,
    name_as_jpeg,
    shows_to,
)
from tests import images

pytestmark = pytest.mark.unit


def ftyp(major: bytes, *compatible: bytes) -> bytes:
    box = b"ftyp" + major + b"\0\0\0\0" + b"".join(compatible)
    return (len(box) + 4).to_bytes(4, "big") + box + b"\0" * 32


@pytest.mark.parametrize(
    ("head", "media_type"),
    [
        (images.jpeg(), "image/jpeg"),
        (images.png(), "image/png"),
        (images.webp(), "image/webp"),
        (images.heic(), "image/heic"),
        (images.pdf(), "application/pdf"),
        (ftyp(b"heic"), "image/heic"),
        (ftyp(b"mif1", b"miaf", b"heic"), "image/heic"),
        # AVIF is not cleaned here, so it is a file like any other.
        (ftyp(b"avif", b"mif1"), "application/octet-stream"),
        (ftyp(b"mif1", b"avif"), "application/octet-stream"),
        (ftyp(b"isom", b"mp42"), "application/octet-stream"),
        (b"RIFF\x10\0\0\0WAVEfmt ", "application/octet-stream"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "application/octet-stream"),
        (b"GIF89a", "application/octet-stream"),
        (b"", "application/octet-stream"),
    ],
)
def test_the_type_is_told_from_the_content(head: bytes, media_type: str) -> None:
    assert sniff(head[:256]) == media_type


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("receipt.pdf", "receipt.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\photo.jpg", "photo.jpg"),
        ("  spaced name .txt  ", "spaced name .txt"),
        ("bad\r\nname\x00.txt", "badname.txt"),
        # A direction override would show "txt.exe" as "exe.txt".
        ("invoice\u202efdp.exe", "invoicefdp.exe"),
        ("a" * 300 + ".jpg", "a" * 251 + ".jpg"),
        ("b" * 300, "b" * 255),
    ],
)
def test_a_name_is_the_base_name_without_control_characters(given: str, kept: str) -> None:
    assert clean_name(given) == kept


@pytest.mark.parametrize("name", ["", "   ", "..", "dir/", "\x00\x01"])
def test_a_file_needs_a_name(name: str) -> None:
    with pytest.raises(InvalidFileError):
        clean_name(name)


@pytest.mark.parametrize(
    ("name", "renamed"), [("IMG.HEIC", "IMG.jpg"), ("a.b.heif", "a.b.jpg"), ("noext", "noext"), ("x.jpg", "x.jpg")]
)
def test_a_converted_photo_is_named_as_a_jpeg(name: str, renamed: str) -> None:
    assert name_as_jpeg(name) == renamed


def access(*permissions: str, guest_view: bool = False) -> Access:
    return Access(permissions=frozenset({"entities.view", *permissions}), guest_view=guest_view)


MEMBER = access()
GUEST = access(guest_view=True)
PRIVATE_VIEWER = access("entities.view_private")
FINANCE = access("documents.view_financial")


@pytest.mark.parametrize(
    ("kind", "visibility", "who", "shown"),
    [
        (FileKind.MANUAL, Visibility.NORMAL, MEMBER, True),
        (FileKind.MANUAL, Visibility.NORMAL, GUEST, False),
        (FileKind.MANUAL, Visibility.GUESTS, MEMBER, True),
        (FileKind.MANUAL, Visibility.GUESTS, GUEST, True),
        (FileKind.PHOTO, Visibility.PRIVATE, MEMBER, False),
        (FileKind.PHOTO, Visibility.PRIVATE, PRIVATE_VIEWER, True),
        (FileKind.RECEIPT, Visibility.NORMAL, MEMBER, False),
        (FileKind.WARRANTY, Visibility.NORMAL, MEMBER, False),
        (FileKind.RECEIPT, Visibility.NORMAL, FINANCE, True),
        (FileKind.RECEIPT, Visibility.GUESTS, GUEST, False),
        (FileKind.RECEIPT, Visibility.PRIVATE, FINANCE, False),
    ],
)
def test_who_sees_a_file(kind: FileKind, visibility: Visibility, who: Access, shown: bool) -> None:
    assert shows_to(kind, visibility, who) is shown


def image(number: int, kind: FileKind = FileKind.PHOTO, status: FileStatus = FileStatus.READY) -> File:
    return File(
        id=UUID(int=number),
        home_id=UUID(int=1),
        kind=kind,
        visibility=Visibility.NORMAL,
        status=status,
        name=f"{number}.jpg",
        media_type="image/jpeg",
        size=1,
        added_by={},
        created_at=datetime(2026, 11, 27, tzinfo=UTC),
    )


def at(file: File, position: int, cover: bool = False) -> tuple[Attachment, File]:
    return Attachment(file_id=file.id, entity_id=UUID(int=9), position=position, is_cover=cover), file


def test_the_chosen_cover_stands_for_the_entity() -> None:
    assert cover_of([at(image(1), 0), at(image(2, FileKind.RECEIPT), 1, cover=True)]) == UUID(int=2)


def test_without_a_chosen_cover_the_first_ready_photo_stands_for_it() -> None:
    attached = [
        at(image(3), 3),
        at(image(1, FileKind.RECEIPT), 0),
        at(image(2, status=FileStatus.PROCESSING), 1),
        at(image(4), 2),
    ]

    assert cover_of(attached) == UUID(int=4)


def test_documents_alone_make_no_cover() -> None:
    assert cover_of([at(image(1, FileKind.MANUAL), 0)]) is None
