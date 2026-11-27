# Photos and documents

- **Status:** proposed, waiting for the author's review.
- **Date:** 2026-11-27.
- **Scope:** files attached to things and places: photos, receipts, warranties, manuals and other documents. How they are uploaded, cleaned, previewed, stored, shown and removed, and who sees them.

The tree, access and privacy are [core-model.md](core-model.md). This document adds files to them.

The decisions follow v0.3 where they can. Each decision that changes v0.3 or goes beyond it is marked **Proposed** and listed in [Open questions](#13-open-questions).

Not covered, each with a design of its own later:
- text recognition, recognising things on photos and reading receipts (the assistant);
- floor plans and plan sheets, 3D models, project files of integrations (KNX);
- searching inside documents;
- video.

## 1. Threats

Photos and receipts say more than the registry's text: where the home is, what it holds and what it cost.

| Threat | Defence |
|---|---|
| A photo gives away where it was taken | Location and other metadata are removed before anyone can open the file (section 5) |
| A link to a file leaks | No public links: every request checks the session and the access (section 7) |
| An uploaded file runs script on Penaria's own address | The type is decided from the content; only images and PDF open in the browser; responses forbid script and type sniffing |
| A crafted image or PDF crashes or exhausts the server | Files are parsed only in the worker, with limits on size and pixels |
| Someone sees prices or documents they should not | Receipts and warranties need a permission of their own (section 6) |

## 2. What a person gets

- On the page of a thing or place: its photos, one of them the cover, and its documents with their kind, name, size and date.
- The cover shows in the tree and in lists.
- On a phone, "Take a photo" opens the camera; "Choose files" takes several at once.
- One receipt or manual attaches to several things.
- **Add things by photos** inside a place: each photo becomes a new thing, named right away. This is the fast inventory without any AI.

## 3. Model

A **file** is the stored content with its facts. An **attachment** ties a file to an entity.

**Proposed: one file, many attachments.** v0.3 gives an attachment one entity. A shop receipt often covers several things, and identical things share a manual.

A file has: a kind (`photo`, `receipt`, `warranty`, `manual`, `other`), the original name, the media type, size and SHA-256, for images the width, height and the time taken, who added it and when, a visibility (section 6) and a status (`processing`, `ready`, `failed`).

An attachment has: the file, the entity, its place in the entity's list, and whether it is the entity's cover. An entity has at most one cover. Only an image can be a cover.

## 4. Upload

**Proposed: files go through the server, not straight to storage.** v0.3 has the browser upload to S3 by a signed link. That needs the storage reachable from every browser: a second address with its own certificate, CORS rules and an exposed storage service. For a home install this is most of the work of running the system, and the files are small. Through the server:

- there is one address, and the storage stays inside the install;
- access is checked in one place;
- nothing is readable before it has been cleaned.

The server streams an upload to storage without holding it in memory. Signed direct uploads can be added later behind the same interface, if large files ever need them.

- `POST /api/v1/entities/{id}/files` takes one file and its kind.
- **Proposed: any file type is accepted, up to 50 MB** (`PENARIA_FILES__MAX_SIZE`). Only images (JPEG, PNG, WebP, HEIC) and PDF are previewed and opened in the browser; everything else is only downloaded.
- The type is read from the content, never taken from the name or from what the browser claims.

## 5. Processing

An upload lands in storage as an incoming object that nobody can read. A worker takes it from a queue and:

1. checks the type and the limits (an image of at most 100 megapixels);
2. **removes metadata** from images;
3. makes previews: two WebP sizes (about 320 and 1600 pixels), and the first page of a PDF;
4. stores the final original, deletes the incoming object and marks the file `ready`.

**Proposed: all metadata of a photo is removed, not only the location** (v0.3 names the location). Cameras also write device serial numbers and owner names. The time a photo was taken is kept in the database, and the orientation is respected. JPEG, PNG and WebP are cleaned without recompression, so the pixels stay as they were. **HEIC is converted to JPEG** (browsers cannot show HEIC, and it cannot be cleaned in place). PDF and other documents are stored byte for byte.

**Proposed: a new `worker` process with a queue in PostgreSQL.** It is the same image started with another command. v0.3 gives background work to Temporal. Requiring Temporal now, to make previews, would add a heavy service to every home. Temporal arrives with the first long workflow that needs it (imports, recognition). The worker is a separate process because decoding images takes CPU, and a broken file must not take the API down.

A file that cannot be processed is marked `failed` with a reason, and can be removed.

## 6. Who sees a file

A file is reached through its attachments: a person sees it when they see at least one entity it is attached to, with the privacy rules of [core-model.md](core-model.md), section 11.3. On top of that:

| Visibility of the file | Who sees it |
|---|---|
| `normal` | members who see the entity |
| `private` | members with `entities.view_private` |
| `guests` | members, and guests who see the entity |

- **Proposed: new files are `guests` for photos and `normal` for everything else.** A guest sees a thing only if it is marked for guests, and then its photo is the useful part: "the towels are here". Documents are shown to guests only when someone says so.
- **Proposed: a new permission, `documents.view_financial`, "See receipts and warranties".** Roles are checkboxes, so this is one more. Owner, admin and family have it; guest and contractor do not. Without it, files of the kinds `receipt` and `warranty` are not listed or served. Existing homes get it in their preset roles by migration.
- Adding, changing or removing a file needs `entities.edit` on every entity it is attached to. Attaching an existing file to another thing needs seeing the file and editing that thing.
- Device tokens read files as their role allows.

## 7. Serving

- `GET /api/v1/files/{id}/content` and `/preview/{size}`, on the app's own address, checked on every request. There are no public or signed links.
- Responses set `X-Content-Type-Options: nosniff` and a Content-Security-Policy that forbids script. Only images and PDF are `inline`; the rest download.
- Caching is private, with an `ETag`; ranges are supported, so a long manual opens quickly.

## 8. Removing

- Detaching a file from its last entity removes the file.
- A removed file stays in the trash for 30 days, can be restored, and is then deleted from storage.
- Archiving an entity keeps its files: "the old kettle's receipt" stays findable.
- Every addition, change, removal and restore is journalled.

## 9. Storage

S3-compatible storage, as decided. Configuration: `PENARIA_S3__ENDPOINT`, `..._BUCKET`, `..._ACCESS_KEY_ID`, `..._SECRET_ACCESS_KEY`, `..._REGION`. The migrate step creates the bucket when it is missing.

- Objects are named by ids, never by the original names.
- **Proposed: storage is optional for the server.** Without `PENARIA_S3__*`, files are off and the interface says so, as with email. The Compose install adds a storage service (SILO), so a home gets files by default.
- **Proposed: no encryption of files by Penaria in version one.** With its own encryption, a lost `PENARIA_SECRET_KEY` would lose every photo. Operators who need encryption at rest use the disk's or the storage's.

## 10. Tables

The `documents` context (`features/support/documents`) owns them; foreign keys reach only homes and entities.

```sql
CREATE TABLE documents_files (
  id uuid PRIMARY KEY,
  home_id uuid NOT NULL REFERENCES identity_homes ON DELETE CASCADE,
  kind text NOT NULL, visibility text NOT NULL, status text NOT NULL, failure text,
  name text NOT NULL, media_type text, size bigint NOT NULL, sha256 text,
  width int, height int, taken_at timestamptz,
  added_by jsonb NOT NULL, created_at timestamptz NOT NULL,
  removed_at timestamptz,                -- in the trash since
  leased_until timestamptz, attempts int NOT NULL DEFAULT 0   -- the worker's queue
);
CREATE TABLE documents_attachments (
  file_id uuid NOT NULL REFERENCES documents_files ON DELETE CASCADE,
  entity_id uuid NOT NULL REFERENCES registry_entities ON DELETE CASCADE,
  position int NOT NULL, is_cover bool NOT NULL DEFAULT false,
  PRIMARY KEY (file_id, entity_id)
);
CREATE UNIQUE INDEX documents_attachments_cover_key ON documents_attachments (entity_id) WHERE is_cover;
```

The registry never reads these tables: the web app asks the documents API for the covers of the entities it shows.

## 11. The install and backups

- Compose gains `penaria-worker` and `s3` with a volume. `.env` gains one value, the storage's password; upgrading from 0.1.0 means adding it, which the release notes say.
- A backup is now three things: the database, the files and `PENARIA_SECRET_KEY`. The install guide gives the commands.

## 12. Order of work

1. Server: storage, upload, the worker (cleaning and previews), access, serving, the trash, and the Compose install.
2. Web: photos and the cover, documents, the camera, attaching to several things.
3. Web: add things by photos.

Then release 0.2.0.

## 13. Open questions

| # | Question | Recommendation |
|---|---|---|
| 1 | Upload through the server instead of signed links to storage (section 4) | Yes: one address, nothing exposed |
| 2 | A `worker` process with a PostgreSQL queue; Temporal later (5) | Yes |
| 3 | Remove all photo metadata; convert HEIC to JPEG (5) | Yes |
| 4 | One file, many attachments (3) | Yes |
| 5 | A permission for receipts and warranties (6) | Yes |
| 6 | Photos of guest things are shown to guests; documents only when marked (6) | Yes |
| 7 | Any file type up to 50 MB; only images and PDF open in the browser (4) | Yes |
| 8 | Storage optional for the server; Compose includes it (9) | Yes: upgrading stays easy |
| 9 | No encryption of files by Penaria in version one (9) | Yes |
| 10 | Add things by photos is part of this work (2, 12) | Yes: the fastest way to fill a home before AI |
