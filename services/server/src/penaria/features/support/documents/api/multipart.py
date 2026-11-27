"""The one file of a ``multipart/form-data`` request, read as it arrives: nothing is held but the chunk
at hand. FastAPI's ``UploadFile`` would take the whole body to disk before the first check."""

from collections.abc import AsyncIterator

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect, Request

from penaria.features.shared.errors import InvalidError

FIELD = b"file"


class InvalidUploadError(InvalidError):
    """Not a multipart form with exactly one file, in the field ``file``, or one cut short."""

    code = "invalid_upload"

    def __init__(self, detail: str = "send one file as multipart/form-data, in the field `file`") -> None:
        super().__init__(detail)


class MultipartFile:
    def __init__(self, request: Request) -> None:
        self._request = request
        self._stream: AsyncIterator[bytes] | None = None
        self._parser: MultipartParser | None = None
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._disposition = b""
        self._parts = 0
        self._headers_read = False
        self._data: list[bytes] = []
        self._part_ended = False
        self._ended = False

    async def name(self) -> str:
        content_type, options = parse_options_header(self._request.headers.get("content-type"))
        if content_type != b"multipart/form-data" or not options.get(b"boundary"):
            raise InvalidUploadError
        self._parser = MultipartParser(
            options[b"boundary"],
            {
                "on_part_begin": self._on_part_begin,
                "on_header_field": lambda data, start, end: self._header_name.extend(data[start:end]),
                "on_header_value": lambda data, start, end: self._header_value.extend(data[start:end]),
                "on_header_end": self._on_header_end,
                "on_headers_finished": self._on_headers_finished,
                "on_part_data": lambda data, start, end: self._data.append(data[start:end]),
                "on_part_end": self._on_part_end,
                "on_end": self._on_end,
            },
        )
        self._stream = self._request.stream()
        while not self._headers_read:
            await self._read()
        _, disposition = parse_options_header(self._disposition)
        if disposition.get(b"name") != FIELD or b"filename" not in disposition:
            raise InvalidUploadError
        return disposition[b"filename"].decode(errors="replace")

    async def chunks(self) -> AsyncIterator[bytes]:
        """The file's content; ends only after the whole request proved to hold nothing else."""
        while True:
            data, self._data = self._data, []
            for chunk in data:
                yield chunk
            if self._ended:
                return
            await self._read()

    async def _read(self) -> None:
        if self._stream is None or self._parser is None:
            raise RuntimeError("name() comes first")
        try:
            chunk = await anext(self._stream)
        except (StopAsyncIteration, ClientDisconnect) as exc:
            raise InvalidUploadError("the upload was cut short") from exc
        if not chunk:
            raise InvalidUploadError("the upload was cut short")
        try:
            self._parser.write(chunk)
        except MultipartParseError as exc:
            raise InvalidUploadError from exc
        if self._parts > 1:
            raise InvalidUploadError

    def _on_part_begin(self) -> None:
        self._parts += 1

    def _on_header_end(self) -> None:
        if bytes(self._header_name).lower() == b"content-disposition":
            self._disposition = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def _on_headers_finished(self) -> None:
        self._headers_read = True

    def _on_part_end(self) -> None:
        self._part_ended = True

    def _on_end(self) -> None:
        if not self._part_ended:
            raise MultipartParseError("the form ended inside its file")
        self._ended = True
