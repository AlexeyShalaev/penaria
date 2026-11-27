import pytest

from penaria.features.support.documents.api.serving import disposition, parse_range
from penaria.features.support.documents.domain.storage import ByteRange

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("bytes=0-9", ByteRange(0, 9)),
        ("bytes=90-", ByteRange(90, 99)),
        ("bytes=90-500", ByteRange(90, 99)),
        ("bytes=-10", ByteRange(90, 99)),
        ("bytes=-500", ByteRange(0, 99)),
        ("bytes=100-", "unsatisfiable"),
        ("bytes=-0", "unsatisfiable"),
        # Several ranges, another unit and nonsense are ignored: the whole file is answered.
        ("bytes=0-1,5-6", None),
        ("items=0-9", None),
        ("bytes=9-0", None),
        ("bytes=a-b", None),
        ("bytes=--5", None),
        ("bytes=", None),
        ("bytes=²-", None),
    ],
)
def test_a_range_header_asks_for_one_part_of_the_file(header: str | None, expected: object) -> None:
    assert parse_range(header, 100) == expected


def test_a_filename_cannot_break_out_of_the_header() -> None:
    assert disposition("attachment", 'a"; filename=evil.html\\') == (
        "attachment; filename=\"a_; filename=evil.html_\"; filename*=UTF-8''a%22%3B%20filename%3Devil.html%5C"
    )
