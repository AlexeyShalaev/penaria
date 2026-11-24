import pytest

from penaria.common.urls import origin_of

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://Home.Example.org/", "https://home.example.org"),
        ("https://home.example.org:443/page?x=1", "https://home.example.org"),
        ("http://localhost:5173/account", "http://localhost:5173"),
        ("http://[::1]:8000/", "http://[::1]:8000"),
    ],
)
def test_an_origin_is_written_as_browsers_write_it(url: str, origin: str) -> None:
    assert origin_of(url) == origin
