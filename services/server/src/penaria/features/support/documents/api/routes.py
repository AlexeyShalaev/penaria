"""HTTP: the files of things and places (docs/design/documents.md)."""

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Query, Request, Response, status
from pydantic import BaseModel, Field
from servicewright import ErrorKind
from servicewright.adapters.fastapi import UnitScopeDep
from servicewright.core.errors import ErrorInfo, ProblemDetailsRenderer
from starlette.responses import JSONResponse

from penaria.features.shared.actor import Actor
from penaria.features.shared.http import SIGNED_IN
from penaria.features.support.documents.api.multipart import MultipartFile
from penaria.features.support.documents.api.serving import serve
from penaria.features.support.documents.domain.files import FileFailure, FileKind, FileStatus, Visibility
from penaria.features.support.documents.domain.storage import LARGE_PREVIEW, SMALL_PREVIEW
from penaria.features.support.documents.use_cases.commands import (
    AttachFile,
    ChangeFile,
    DetachFile,
    RemoveFile,
    RestoreFile,
    SetCover,
)
from penaria.features.support.documents.use_cases.queries import (
    FindCovers,
    GetFile,
    ListEntityFiles,
    ListTrash,
    ReadContent,
)
from penaria.features.support.documents.use_cases.upload import FilesConfig, FileTooLargeError, UploadFile
from penaria.features.support.documents.use_cases.views import EntityFile, FileDetail, FilePlace, FileView

# One call covers a screen: a place with hundreds of things, not a whole home's inventory at once.
COVERS_MAX = 500


class PreviewSize(IntEnum):
    SMALL = SMALL_PREVIEW
    LARGE = LARGE_PREVIEW


router = APIRouter(prefix="/api/v1", tags=["files"], dependencies=[SIGNED_IN])


class FilesConfigOut(BaseModel):
    enabled: bool = Field(description="Whether this Penaria keeps files; without storage, uploads answer files_off")
    max_size: int = Field(description="The largest file, in bytes")


class FileOut(BaseModel):
    id: UUID
    home_id: UUID
    kind: FileKind
    visibility: Visibility
    status: FileStatus = Field(description="Content and previews are served only when ready")
    failure: FileFailure | None = Field(description="Why a failed file could not be processed")
    name: str
    media_type: str = Field(description="Told from the content; a HEIC photo becomes image/jpeg")
    size: int = Field(description="Bytes of the stored file; of the upload while it is processing")
    width: int | None = Field(description="Of an image, as it is shown")
    height: int | None
    taken_at: datetime | None = Field(description="When the photo was taken, as its camera wrote")
    created_at: datetime
    has_preview: bool = Field(description="Whether /preview/320 and /preview/1600 answer")
    removed_at: datetime | None = Field(description="In the trash since")
    purge_at: datetime | None = Field(description="When a removed file is deleted for good")
    can_edit: bool = Field(
        description="Change its kind, name and visibility, remove it, restore it: needs editing every "
        "entity it is attached to"
    )

    @classmethod
    def of(cls, view: FileView) -> FileOut:
        file = view.file
        return cls(
            id=file.id,
            home_id=file.home_id,
            kind=file.kind,
            visibility=file.visibility,
            status=file.status,
            failure=file.failure,
            name=file.name,
            media_type=file.media_type,
            size=file.size,
            width=file.width,
            height=file.height,
            taken_at=file.taken_at,
            created_at=file.created_at,
            has_preview=file.previews,
            removed_at=file.removed_at,
            purge_at=file.purge_at,
            can_edit=view.can_edit,
        )


class EntityFileOut(FileOut):
    is_cover: bool = Field(description="The file that stands for the entity: the chosen one, or the first photo")
    can_detach: bool
    can_set_cover: bool

    @classmethod
    def of_entry(cls, entry: EntityFile) -> EntityFileOut:
        return cls(
            **FileOut.of(entry.view).model_dump(),
            is_cover=entry.is_cover,
            can_detach=entry.can_detach,
            can_set_cover=entry.can_set_cover,
        )


class EntityFilesOut(BaseModel):
    files: list[EntityFileOut]
    add_kinds: list[FileKind] = Field(description="The kinds the actor may upload here; empty when none")


class FilePlaceOut(BaseModel):
    entity_id: UUID
    names: list[str] = Field(description="The names from the top of the home down to the entity itself")
    is_cover: bool = Field(description="Chosen as the entity's cover")
    can_detach: bool

    @classmethod
    def of(cls, place: FilePlace) -> FilePlaceOut:
        return cls(
            entity_id=place.entity_id, names=list(place.names), is_cover=place.is_cover, can_detach=place.can_detach
        )


class FileDetailOut(FileOut):
    entities: list[FilePlaceOut] = Field(description="Where it is attached, as far as the actor may see")

    @classmethod
    def of_detail(cls, detail: FileDetail) -> FileDetailOut:
        return cls(**FileOut.of(detail.view).model_dump(), entities=[FilePlaceOut.of(p) for p in detail.places])


class CoverOut(BaseModel):
    entity_id: UUID
    file: FileOut


class CoversIn(BaseModel):
    entity_ids: list[UUID] = Field(max_length=COVERS_MAX)


class CoverIn(BaseModel):
    file_id: UUID


class FilePatch(BaseModel):
    kind: FileKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: Visibility | None = None


@router.get("/config/files")
async def files_config(scope: UnitScopeDep) -> FilesConfigOut:
    config = await scope.get(FilesConfig)
    return FilesConfigOut(enabled=config.enabled, max_size=config.max_size)


@router.get("/entities/{entity_id}/files")
async def list_entity_files(entity_id: UUID, scope: UnitScopeDep) -> EntityFilesOut:
    found = await (await scope.get(ListEntityFiles)).execute(await scope.get(Actor), entity_id)
    return EntityFilesOut(
        files=[EntityFileOut.of_entry(entry) for entry in found.files],
        add_kinds=found.add_kinds,
    )


@router.post(
    "/entities/{entity_id}/files",
    status_code=status.HTTP_201_CREATED,
    # Read by hand, as it arrives; this is what the route takes.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_file(
    entity_id: UUID, request: Request, scope: UnitScopeDep, kind: Annotated[FileKind, Query()]
) -> FileDetailOut:
    """Add one file to a thing or place. It is stored as `processing`, and becomes `ready` or `failed`
    once the worker has cleaned it. A file over the limit answers 413 `file_too_large`."""
    declared = request.headers.get("content-length")
    detail = await (await scope.get(UploadFile)).execute(
        await scope.get(Actor),
        entity_id,
        kind=kind,
        incoming=MultipartFile(request),
        declared_size=int(declared) if declared is not None and declared.isdigit() else None,
    )
    return FileDetailOut.of_detail(detail)


@router.put("/entities/{entity_id}/files/{file_id}")
async def attach_file(entity_id: UUID, file_id: UUID, scope: UnitScopeDep) -> FileDetailOut:
    """Attach an existing file to one more thing or place; attaching it twice changes nothing."""
    detail = await (await scope.get(AttachFile)).execute(await scope.get(Actor), entity_id, file_id)
    return FileDetailOut.of_detail(detail)


@router.delete("/entities/{entity_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_file(entity_id: UUID, file_id: UUID, scope: UnitScopeDep) -> None:
    """Detach a file; detached from its last entity, it goes to the trash."""
    await (await scope.get(DetachFile)).execute(await scope.get(Actor), entity_id, file_id)


@router.put("/entities/{entity_id}/cover", status_code=status.HTTP_204_NO_CONTENT)
async def set_cover(entity_id: UUID, body: Annotated[CoverIn, Body()], scope: UnitScopeDep) -> None:
    await (await scope.get(SetCover)).execute(await scope.get(Actor), entity_id, body.file_id)


@router.post("/covers:find")
async def find_covers(body: Annotated[CoversIn, Body()], scope: UnitScopeDep) -> list[CoverOut]:
    """The covers of the entities a screen shows; those without one the actor may see are left out."""
    covers = await (await scope.get(FindCovers)).execute(await scope.get(Actor), body.entity_ids)
    return [CoverOut(entity_id=entity_id, file=FileOut.of(view)) for entity_id, view in covers.items()]


@router.get("/homes/{home_id}/files/trash")
async def list_trash(home_id: UUID, scope: UnitScopeDep) -> list[FileDetailOut]:
    """The home's removed files the actor may restore, the latest first."""
    details = await (await scope.get(ListTrash)).execute(await scope.get(Actor), home_id)
    return [FileDetailOut.of_detail(detail) for detail in details]


@router.get("/files/{file_id}")
async def get_file(file_id: UUID, scope: UnitScopeDep) -> FileDetailOut:
    return FileDetailOut.of_detail(await (await scope.get(GetFile)).execute(await scope.get(Actor), file_id))


@router.patch("/files/{file_id}")
async def change_file(file_id: UUID, body: Annotated[FilePatch, Body()], scope: UnitScopeDep) -> FileDetailOut:
    detail = await (await scope.get(ChangeFile)).execute(
        await scope.get(Actor), file_id, kind=body.kind, name=body.name, visibility=body.visibility
    )
    return FileDetailOut.of_detail(detail)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_file(file_id: UUID, scope: UnitScopeDep) -> None:
    """Move a file to the trash, from every entity it is attached to."""
    await (await scope.get(RemoveFile)).execute(await scope.get(Actor), file_id)


@router.post("/files/{file_id}:restore")
async def restore_file(file_id: UUID, scope: UnitScopeDep) -> FileDetailOut:
    detail = await (await scope.get(RestoreFile)).execute(await scope.get(Actor), file_id)
    return FileDetailOut.of_detail(detail)


_BINARY: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
}


@router.get("/files/{file_id}/content", response_class=Response, responses=_BINARY)
async def file_content(file_id: UUID, request: Request, scope: UnitScopeDep) -> Response:
    """The file itself: an image or a PDF is shown, anything else is downloaded. Ranges are supported."""
    content = await (await scope.get(ReadContent)).original(await scope.get(Actor), file_id)
    return await serve(request, content, content.file.name)


@router.get("/files/{file_id}/preview/{size}", response_class=Response, responses=_BINARY)
async def file_preview(file_id: UUID, size: PreviewSize, request: Request, scope: UnitScopeDep) -> Response:
    """A WebP of an image, or of a PDF's first page, whose longest side is at most `size` pixels."""
    content = await (await scope.get(ReadContent)).preview(await scope.get(Actor), file_id, size.value)
    stem = content.file.name.rpartition(".")[0] or content.file.name
    return await serve(request, content, f"{stem}.webp")


async def _too_large(request: Request, error: FileTooLargeError) -> JSONResponse:
    """413, which no kind of ``ServiceError`` maps to."""
    rendered = ProblemDetailsRenderer().render(
        ErrorInfo(
            kind=ErrorKind.INVALID,
            code=FileTooLargeError.code,
            detail=error.detail,
            params=error.params,
            status_override=413,
        )
    )
    return JSONResponse(rendered.body, status_code=rendered.status_code, media_type=rendered.media_type)


EXCEPTION_HANDLERS: dict[type[Exception], Any] = {FileTooLargeError: _too_large}
