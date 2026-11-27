"""Uploading, cleaning and reading files, through the HTTP API, the worker and the storage."""

import io
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from PIL import Image

from penaria.integrations.s3.storage import S3Storage
from tests import images
from tests.integration.apps.api.test_people import make_home, ok
from tests.integration.files.conftest import Run
from tests.integration.files.helpers import detail, listed, upload
from tests.integration.helpers import NewClient
from tests.integration.storage import keys, read

pytestmark = pytest.mark.integration


async def test_a_photo_is_stored_without_its_metadata_and_previewed(
    api: httpx.AsyncClient, worker: Run, storage: S3Storage
) -> None:
    ids = await make_home(api)

    added = await upload(api, ids["towels"], "IMG_0001.jpg", images.jpeg(6))
    early = await api.get(f"/files/{added['id']}/content")
    waiting = await read(storage, f"incoming/{added['id']}")
    await worker()
    ready = await detail(api, added["id"])

    assert (added["status"], added["media_type"], added["visibility"], added["has_preview"]) == (
        "processing",
        "image/jpeg",
        "guests",
        False,
    )
    # Nothing is readable before it is cleaned, though the upload is in storage.
    assert (early.status_code, early.json()["code"]) == (409, "file_processing")
    assert images.SECRET in waiting
    assert (ready["status"], ready["width"], ready["height"], ready["taken_at"]) == (
        "ready",
        32,
        48,
        "2026-11-20T07:11:12Z",
    )
    stored = await keys(storage, f"files/{added['id']}/")
    assert [key.rsplit("/", 1)[1] for key in stored] == ["original", "preview-1600.webp", "preview-320.webp"]
    for key in stored:
        assert images.SECRET not in await read(storage, key)
    assert await keys(storage, f"incoming/{added['id']}") == []
    content = await api.get(f"/files/{added['id']}/content")
    assert content.content == await read(storage, f"files/{added['id']}/original")
    assert len(content.content) == ready["size"]


async def test_a_photo_without_an_offset_was_taken_in_the_homes_time(api: httpx.AsyncClient, worker: Run) -> None:
    ids = await make_home(api)  # in Europe/Moscow

    added = await upload(api, ids["towels"], "scan.jpg", images.jpeg(offset=None))
    await worker()

    assert (await detail(api, added["id"]))["taken_at"] == "2026-11-20T07:11:12Z"


@pytest.mark.parametrize(
    ("name", "data", "uploaded_as", "stored_name", "stored_type"),
    [
        ("IMG_2.HEIC", images.heic(), "image/heic", "IMG_2.jpg", "image/jpeg"),
        ("shot.png", images.png(), "image/png", "shot.png", "image/png"),
        ("shot.webp", images.webp(), "image/webp", "shot.webp", "image/webp"),
    ],
    ids=["heic", "png", "webp"],
)
async def test_every_image_format_ends_up_clean(
    api: httpx.AsyncClient,
    worker: Run,
    storage: S3Storage,
    name: str,
    data: bytes,
    uploaded_as: str,
    stored_name: str,
    stored_type: str,
) -> None:
    ids = await make_home(api)

    added = await upload(api, ids["towels"], name, data)
    await worker()
    ready = await detail(api, added["id"])

    assert added["media_type"] == uploaded_as
    assert (ready["status"], ready["name"], ready["media_type"], ready["has_preview"]) == (
        "ready",
        stored_name,
        stored_type,
        True,
    )
    original = await read(storage, f"files/{added['id']}/original")
    assert images.SECRET not in original
    with Image.open(io.BytesIO(original)) as image:
        assert dict(image.getexif()) == {}
    content = await api.get(f"/files/{added['id']}/content")
    assert content.headers["content-type"] == stored_type
    assert content.headers["content-disposition"].startswith(f'inline; filename="{stored_name}"')
    assert content.headers["content-security-policy"] == (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox"
    )
    assert content.headers["x-content-type-options"] == "nosniff"
    preview = await api.get(f"/files/{added['id']}/preview/320")
    assert (preview.status_code, preview.headers["content-type"]) == (200, "image/webp")
    stem = stored_name.rsplit(".", 1)[0]
    assert preview.headers["content-disposition"].startswith(f'inline; filename="{stem}.webp"')
    assert "accept-ranges" not in preview.headers
    assert images.SECRET not in preview.content


async def test_a_pdf_is_kept_byte_for_byte_and_shown_with_a_preview(
    api: httpx.AsyncClient, worker: Run, storage: S3Storage
) -> None:
    ids = await make_home(api)
    data = images.pdf()

    added = await upload(api, ids["towels"], "Инструкция «чайник».pdf", data, kind="manual")
    await worker()
    content = await api.get(f"/files/{added['id']}/content")

    assert await read(storage, f"files/{added['id']}/original") == data
    assert (await api.get(f"/files/{added['id']}/preview/1600")).status_code == 200
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["content-disposition"] == (
        'inline; filename="__________ ________.pdf"; '
        "filename*=UTF-8''%D0%98%D0%BD%D1%81%D1%82%D1%80%D1%83%D0%BA%D1%86%D0%B8%D1%8F%20"
        "%C2%AB%D1%87%D0%B0%D0%B9%D0%BD%D0%B8%D0%BA%C2%BB.pdf"
    )
    assert content.headers["content-security-policy"] == (
        "default-src 'none'; object-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
    )
    # Not compressed, so ranges and the length stay those of the file.
    assert content.headers.get("content-encoding") is None
    assert content.headers["content-length"] == str(len(data))


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("notes.txt", b"the filter is changed every spring\n" * 200),
        ("page.html", b"<html><script>alert(1)</script></html>"),
        ("drawing.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ],
    ids=["text", "html", "svg"],
)
async def test_any_other_file_is_only_ever_downloaded(
    api: httpx.AsyncClient, worker: Run, name: str, data: bytes
) -> None:
    ids = await make_home(api)

    added = await upload(api, ids["towels"], name, data, kind="other")
    await worker()
    content = await api.get(f"/files/{added['id']}/content")
    preview = await api.get(f"/files/{added['id']}/preview/320")

    assert content.content == data
    assert content.headers["content-type"] == "application/octet-stream"
    assert content.headers["content-disposition"].startswith(f'attachment; filename="{name}"')
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'self'; sandbox"
    assert content.headers.get("content-encoding") is None
    assert (preview.status_code, preview.json()["code"]) == (404, "preview_not_found")


async def test_content_is_cached_privately_revalidated_and_served_in_ranges(
    api: httpx.AsyncClient, worker: Run
) -> None:
    ids = await make_home(api)
    data = bytes(range(256)) * 40
    added = await upload(api, ids["towels"], "blob.bin", data, kind="other")
    await worker()
    url = f"/files/{added['id']}/content"

    whole = await api.get(url)
    etag = whole.headers["etag"]
    unchanged = await api.get(url, headers={"If-None-Match": etag})
    middle = await api.get(url, headers={"Range": "bytes=10-19"})
    tail = await api.get(url, headers={"Range": "bytes=-5"})
    past = await api.get(url, headers={"Range": f"bytes={len(data)}-"})
    stale = await api.get(url, headers={"Range": "bytes=10-19", "If-Range": '"another"'})

    assert (whole.headers["cache-control"], whole.headers["accept-ranges"]) == ("private, no-cache", "bytes")
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (middle.status_code, middle.content) == (206, data[10:20])
    assert middle.headers["content-range"] == f"bytes 10-19/{len(data)}"
    assert (tail.status_code, tail.content) == (206, data[-5:])
    assert (past.status_code, past.headers["content-range"]) == (416, f"bytes */{len(data)}")
    assert (stale.status_code, stale.content) == (200, data)


async def test_a_large_upload_goes_to_storage_in_parts(api: httpx.AsyncClient, worker: Run, storage: S3Storage) -> None:
    ids = await make_home(api)
    data = bytes(range(251)) * 50_000  # 12 MB: three parts of at least 5 MB, the last smaller

    added = await upload(api, ids["towels"], "scan.raw", data, kind="other")
    await worker()

    assert added["size"] == len(data)
    assert await read(storage, f"files/{added['id']}/original") == data
    assert (await api.get(f"/files/{added['id']}/content")).content == data


@pytest.mark.parametrize("data", [images.jpeg()[:300], b"\xff\xd8\xff and nothing more"], ids=["cut", "nonsense"])
async def test_a_file_that_cannot_be_cleaned_fails_and_nothing_of_it_stays(
    api: httpx.AsyncClient, worker: Run, storage: S3Storage, data: bytes
) -> None:
    ids = await make_home(api)

    added = await upload(api, ids["towels"], "broken.jpg", data)
    await worker()
    failed = await detail(api, added["id"])
    content = await api.get(f"/files/{added['id']}/content")

    assert (failed["status"], failed["failure"]) == ("failed", "broken")
    assert (content.status_code, content.json()["code"]) == (409, "file_failed")
    assert await keys(storage, f"incoming/{added['id']}") == []
    assert await keys(storage, f"files/{added['id']}/") == []
    # It is listed, so it can be removed.
    assert await listed(api, ids["towels"]) == ["broken.jpg"]
    assert (await api.delete(f"/files/{added['id']}")).status_code == 204


async def test_the_config_says_that_files_are_on_and_how_large_one_may_be(api: httpx.AsyncClient) -> None:
    assert await ok(await api.get("/config/files")) == {"enabled": True, "max_size": 52428800}


@pytest.mark.parametrize("files_max_size", [1000])
async def test_a_file_over_the_limit_is_refused(api: httpx.AsyncClient, storage: S3Storage) -> None:
    ids = await make_home(api)
    before = await keys(storage)

    at_limit = await upload(api, ids["towels"], "fits.bin", b"x" * 1000, kind="other")
    over = await upload(api, ids["towels"], "big.bin", b"x" * 1001, kind="other", status=413)

    assert over["code"] == "file_too_large"
    assert over["params"] == {"max_size": 1000}
    assert await keys(storage) == sorted([*before, f"incoming/{at_limit['id']}"])
    assert await listed(api, ids["towels"]) == ["fits.bin"]


def multipart(name: str, data: bytes, *, end: bool = True) -> bytes:
    head = f'--edge\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n\r\n'.encode()
    return head + data + (b"\r\n--edge--\r\n" if end else b"")


async def send(client: httpx.AsyncClient, entity_id: str, body: Any, **headers: str) -> httpx.Response:
    return await client.post(
        f"/entities/{entity_id}/files",
        params={"kind": "other"},
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=edge", **headers},
    )


@pytest.mark.parametrize("files_max_size", [10 * 1024 * 1024])
async def test_the_limit_holds_while_an_upload_of_unknown_length_streams(
    api: httpx.AsyncClient, storage: S3Storage
) -> None:
    ids = await make_home(api)
    before = await keys(storage)
    sent = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal sent
        yield multipart("big.bin", b"", end=False)
        while sent < 40:
            sent += 1
            yield b"x" * 1024 * 1024

    response = await send(api, ids["towels"], endless())

    assert (response.status_code, response.json()["code"]) == (413, "file_too_large")
    # Refused as soon as it was over, long before it ended, and the parts stored by then are dropped.
    assert sent == 11
    assert await keys(storage) == before


async def test_a_request_that_says_it_is_too_long_is_refused_before_it_is_read(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)

    async def never_read() -> AsyncIterator[bytes]:
        raise AssertionError("the body was read")
        yield b""

    response = await send(api, ids["towels"], never_read(), **{"Content-Length": str(60 * 1024 * 1024)})

    assert (response.status_code, response.json()["code"]) == (413, "file_too_large")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (multipart("a.bin", b"data", end=False), "invalid_upload"),
        (multipart("a.bin", b"data", end=False) + b"\r\n" + multipart("b.bin", b"data"), "invalid_upload"),
        (b'--edge\r\nContent-Disposition: form-data; name="other"\r\n\r\nx\r\n--edge--\r\n', "invalid_upload"),
        (multipart("empty.bin", b""), "empty_file"),
        (multipart("", b"data"), "invalid_file"),
        (b'--edge\r\nContent-Disposition: form-data; name="file"\r\n\r\nx\r\n--edge--\r\n', "invalid_upload"),
    ],
    ids=["cut-short", "two-files", "no-file", "empty", "no-name", "no-filename"],
)
async def test_an_upload_that_is_not_one_whole_file_is_refused(
    api: httpx.AsyncClient, storage: S3Storage, body: bytes, code: str
) -> None:
    ids = await make_home(api)
    before = await keys(storage)

    response = await send(api, ids["towels"], body)

    assert (response.status_code, response.json()["code"]) == (400, code)
    assert await keys(storage) == before
    assert await listed(api, ids["towels"]) == []


@pytest.mark.parametrize(
    "data", [b"plain text", images.pdf(), b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"x" * 100]
)
async def test_a_photo_is_only_an_image_that_can_be_cleaned(api: httpx.AsyncClient, data: bytes) -> None:
    ids = await make_home(api)

    refused = await upload(api, ids["towels"], "not-a-photo.jpg", data, status=400)

    assert refused["code"] == "not_a_photo"


async def test_a_page_of_another_site_cannot_upload(api: httpx.AsyncClient) -> None:
    ids = await make_home(api)

    response = await api.post(
        f"/entities/{ids['towels']}/files",
        params={"kind": "photo"},
        files={"file": ("a.jpg", images.jpeg())},
        headers={"Origin": "https://evil.example.org"},
    )

    assert (response.status_code, response.json()["code"]) == (403, "cross_origin_request")
    assert await listed(api, ids["towels"]) == []


async def test_without_a_session_nothing_is_read_or_added(
    api: httpx.AsyncClient, anonymous: httpx.AsyncClient, worker: Run
) -> None:
    ids = await make_home(api)
    added = await upload(api, ids["towels"], "a.jpg", images.jpeg())
    await worker()

    answers = [
        await anonymous.get(f"/files/{added['id']}/content"),
        await anonymous.get(f"/files/{added['id']}/preview/320"),
        await anonymous.get("/config/files"),
        await anonymous.post(f"/entities/{ids['towels']}/files", params={"kind": "photo"}, files={"file": ("a", b"")}),
    ]

    assert [answer.status_code for answer in answers] == [401, 401, 401, 401]


async def test_an_upload_the_thing_no_longer_takes_when_it_ends_is_dropped(
    api: httpx.AsyncClient, new_client: NewClient, storage: S3Storage
) -> None:
    ids = await make_home(api)
    before = await keys(storage)
    # A second browser of the owner's: the first one is busy uploading.
    other = new_client(cookies=api.cookies)

    async def slow() -> AsyncIterator[bytes]:
        yield multipart("late.bin", b"", end=False)
        await ok(await other.post(f"/entities/{ids['towels']}:archive", json={"reason": "sold", "version": 1}))
        yield b"x" * 100 + b"\r\n--edge--\r\n"

    response = await send(api, ids["towels"], slow())

    assert (response.status_code, response.json()["code"]) == (409, "entity_archived")
    assert await keys(storage) == before
    assert await listed(api, ids["towels"]) == []


async def test_a_file_the_storage_has_lost_says_so(api: httpx.AsyncClient, worker: Run, storage: S3Storage) -> None:
    ids = await make_home(api)
    added = await upload(api, ids["towels"], "a.jpg", images.jpeg())
    await worker()
    await storage.delete([f"files/{added['id']}/original"])

    response = await api.get(f"/files/{added['id']}/content")

    assert (response.status_code, response.json()["code"]) == (404, "content_missing")


class TestWithoutStorage:
    @pytest.fixture
    def operator_s3(self) -> None:
        return None

    async def test_files_are_off_and_uploads_say_so(self, api: httpx.AsyncClient) -> None:
        ids = await make_home(api)

        config = await ok(await api.get("/config/files"))
        refused = await upload(api, ids["towels"], "a.jpg", images.jpeg(), status=409)

        assert config == {"enabled": False, "max_size": 52428800}
        assert refused["code"] == "files_off"
        assert await listed(api, ids["towels"]) == []
