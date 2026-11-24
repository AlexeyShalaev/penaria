# Core model

- **Status:** proposed, waiting for the author's review.
- **Date:** 2026-11-24.
- **Scope:** the data model of the core and the rules every change follows: homes, the entity tree, aspects, relations, provenance, freshness, the journal, changesets and access.

This document turns the core sections of the v0.3 product design into decisions precise enough to write the schema and the first use cases from. It keeps v0.3's decisions and fills the gaps v0.3 left open. Each new decision is marked **Proposed** and listed again in [Open questions](#16-open-questions). The examples are synthetic.

Not covered here; each gets a document of its own when its code is near:

- files and their processing: upload, OCR, plan sheets;
- the maintenance calendar;
- search and the assistant;
- devices, capabilities and commands;
- the hub and its synchronisation;
- the full module manifest;
- sign-in and sessions.

## 1. Principles

These come from v0.3 and are settled.

1. **Everything is an entity in the home tree.** A property, a room, a cupboard, a vacuum cleaner and a KNX actuator are nodes of one tree. They share search, access, photos and history.
2. **Modules add meaning, not tables.** A module attaches aspects to core entities; it never keeps its own list of devices. When a module is switched off, its actuator stays in the registry as a thing in the distribution board.
3. **One path for every change.** Manual edits, the assistant, importers and the hub all change data through core commands. Every command checks access and writes the journal. Modules never touch the database.
4. **Every fact has a source and an age.** A value knows where it came from (a person, a photo, an import, the bus) and how sure we are of it.
5. **Bulk and automatic changes go through a changeset.** An import of 200 addresses and "the assistant saw 12 things on this photo" look the same: a set of proposed operations that a person accepts as a whole or one by one.
6. **The core knows nothing about protocols.** If a new integration needs a change in the core, the core is missing an extension point.

## 2. Vocabulary

| Term | Meaning |
|---|---|
| Home | The boundary of data and access: one household's space. Everything else belongs to exactly one home. |
| Entity | A node of the home tree: a property, building, floor, space, container, item, system or device. |
| Kind | One of the eight fixed entity types above. Modules cannot add kinds. |
| Aspect | A named set of fields on an entity, validated by a schema: `core.purchase`, `knx.device`. |
| Aspect type | The declaration of an aspect: its schema, version, owner and the kinds it fits. |
| Relation | A typed edge between two entities of one home, outside the tree: `controls`, `part_of`. |
| Provenance | Where a field's value came from, its status and when it was observed. |
| Command | One change requested by an actor, applied in one transaction. |
| Event | An append-only journal record that a command happened. |
| Changeset | A set of proposed operations that a person decides on. |
| Principal | Who is given access: a user, a device (a smart mirror) or a guest link. |
| Actor | Who performs a command: a principal, a module or the system, possibly on behalf of a principal. |
| Grant | Gives a role to a principal over a subtree, possibly until a date. |

## 3. Home

A home is the unit of tenancy. A family may keep a flat and a country house in one home, or in two homes with different people. Every row of every core table carries `home_id`. No query, permission or relation crosses homes.

A home has a name, a time zone (IANA, such as `Europe/Moscow`), and a default locale for content the system writes (notifications, generated task titles). The interface language is each user's own setting.

**Proposed: ownership is a grant, not a column.** v0.3 has both `homes.owner_id` and an `owner` role, which can disagree. This design keeps only the grant. A home has exactly one active `owner` grant, scoped to the whole home and without an expiry. A partial unique index enforces it. Transferring ownership is one command that swaps the two grants.

## 4. The entity tree

The tree answers one question: **where is it physically?** Logical groupings, such as "the heating system" or "what this switch controls", are relations, not tree edges. Keeping the tree physical is what makes "where is the vacuum cleaner?" answerable with a path, and access by subtree meaningful.

### 4.1 Kinds and where they may sit

| Kind | What it is | Allowed parents |
|---|---|---|
| `property` | A flat, a house, a plot | none: a root of the tree; a home may have several |
| `building` | A house, a bathhouse, a garage on the plot | `property` |
| `floor` | A level of a building, basement and attic included | `building` |
| `space` | A room, a corridor, a terrace, a garden bed, a zone inside a room | `property`, `building`, `floor`, `space` |
| `container` | Anything that holds things: a wardrobe, a shelf, a box, a distribution board | `space`, `container`, `item` |
| `item` | Everything else physical: furniture, appliances, tools, food, a kit | `space`, `container`, `item` |
| `device` | A thing a module can talk to: an actuator, a sensor, a mirror | `space`, `container`, `item` |
| `system` | A logical engineering system: heating, water supply, ventilation | `property`, `building`, `system` |

**Proposed: a system has no physical children.** A boiler is a `device` in the boiler room. The heating system is a `system` under the building. The boiler joins the system through a `part_of` relation. v0.3 left this open. With this rule a boiler has one place in the tree, and a system can still list its parts and own maintenance schedules.

**Proposed: containment is checked in the domain.** The database checks only that `kind` is one of the eight values. Moving an entity re-checks the rule for the new parent. The rules can then be relaxed later without a migration.

The tree is at most 32 levels deep. A deeper move is refused. That is far beyond any real home, and it bounds every query on a path.

### 4.2 Entity fields

| Field | Meaning |
|---|---|
| `id` | UUIDv7, so ids sort by creation time and cursors stay simple |
| `home_id` | The owning home |
| `kind` | One of the eight kinds; never changes after creation |
| `parent_id` | The parent entity; `NULL` only for a `property` |
| `path` | The ids from the root to this entity, itself included (section 4.3) |
| `name` | The name people use: "Vacuum cleaner", "Storage room" |
| `aliases` | Other names search should match: "hoover", "vacuum" |
| `quantity`, `unit` | "12 plates" is one entity with a quantity, not 12 entities; `NULL` means one |
| `status` | `present`, `missing`, `lent`, `in_repair` |
| `privacy` | `normal`, `guest_visible`, `private` (section 11.3) |
| `verified_at`, `verified_by` | When and by whom it was last seen where the registry says it is |
| `archived_at`, `archive_reason` | Set when it leaves the home: `discarded`, `sold`, `given_away`, `used_up`, `merged` |
| `version` | Increases on every change to this row or its aspects; used for optimistic locking |
| `created_at`, `updated_at` | Timestamps, UTC |

**Proposed: archiving is not a status.** v0.3 mixed both into one `status` column. An archived drill may also have been lent when it was archived, and restoring it should bring back how it was. So `status` describes where a live entity is, and `archived_at` says whether it is still part of the home. Archived entities are never deleted, because "you threw it out in March" is a useful answer. Archived entities and their subtrees are hidden by default and can be included on request.

Deleting an entity for real is an admin command for mistakes, such as a duplicate created by hand. It is allowed only while nothing references the entity, and it is journalled like any other command.

### 4.3 The path

`path` is a PostgreSQL `ltree`: the entity ids from the root down to the entity itself, as 32 hex digits without hyphens. PostgreSQL 15 labels do not allow hyphens. With `path`:

- "everything inside the kitchen" is `path <@ :kitchen_path`, answered by one GiST index;
- "is this entity inside a granted subtree?" is `:grant_path @> path`;
- the ancestors of an entity are its own path, read without recursion.

`parent_id` stays as the source of truth and keeps referential integrity. `path` is derived from it. A move does three things in one transaction:

1. It refuses a move into the entity's own subtree, which would create a cycle, and any move across homes.
2. It rewrites the paths of the whole subtree in one statement: `UPDATE ... SET path = :new_parent_path || subpath(path, nlevel(:old_path) - 1) WHERE path <@ :old_path`.
3. It bumps the `version` of the moved entity only. Descendants change position but not content, so a concurrent edit of a book inside a moved shelf still succeeds.

## 5. Aspects

### 5.1 Aspect types

An aspect type is declared in code, by the core or by a module's manifest, and registered at migration time. Its declaration has:

- `type`: `<namespace>.<name>`, where the namespace is `core` or a module id (`core.purchase`, `knx.device`);
- `schema`: JSON Schema, draft 2020-12, for the aspect's data;
- `version`: an integer that grows with every change to the schema;
- `kinds`: the kinds the aspect fits (`knx.device` fits only `device`);
- `owner`: `core` or the module id.

An entity has at most one aspect of each type. Several values of one kind, such as two warranties, are an array inside the aspect.

**Proposed: schemas carry i18n keys, not labels.** The web app builds forms from aspect schemas, and the UI has no hard-coded strings. A schema therefore names a key, such as `"x-i18n": "aspect.core.purchase.price"`, and the owning code ships the `en` and `ru` texts. The rule is the same for the core and for modules.

### 5.2 Validation and new versions

Every write is validated against the current version of the schema, in the domain, before the transaction opens. A new version ships with an upgrade function from the previous version. Stored data is upgraded in two ways:

- **when it is read**: an older aspect is upgraded in memory, so the code only ever sees the current shape;
- **in the background**: a batched job rewrites old rows, so the in-memory upgrade code can be deleted a release later.

Writes always store the current version. A schema never goes back a version.

### 5.3 When a module is switched off

Its aspects stay in the database: hidden in the interface, read-only, and back when the module is switched on again. Removing a module's data from a home is an explicit admin command, which goes through a changeset so it can be reviewed and reverted.

### 5.4 The first core aspects

Only what the first screens need. Each feature adds its own aspects when it lands.

| Aspect | Fits | Fields |
|---|---|---|
| `core.product` | item, device | vendor, model, EAN |
| `core.identifiers` | item, device, container | serial number, inventory number |
| `core.purchase` | item, device | date; price (amount as a decimal string, currency as ISO 4217); store; receipt attachment |
| `core.warranty` | item, device | until; terms |
| `core.expiry` | item | best before or use by date |
| `core.designation` | any but property | a code from a drawing or a label ("L.103.1", "D1") and the scheme it comes from |
| `core.area` | property, floor, space | area in square metres |
| `core.address` | property | the postal address; always private (section 11.3) |

`core.placement`, a point on a floor plan, arrives with plan sheets in the documents design.

## 6. Relations

A relation is a typed, directed edge between two entities of the same home: `id`, `from_id`, `to_id`, `type`, optional `data`. A relation type is declared like an aspect type, in code. Its declaration has:

- the kinds allowed at each end;
- a schema for `data`, if the type has data;
- whether the type may form cycles: `part_of` may not;
- the cardinality, where it matters. A device can be `part_of` many systems, but a channel `controls` its loads one by one.

The same pair of entities has at most one relation of each type.

The core relation types:

| Type | From → to | Example |
|---|---|---|
| `part_of` | device, item, container → system | boiler → heating system |
| `powers` | device, item → device, item | power supply → bus line |
| `controls` | device → device, item | dimmer channel → chandelier |
| `serves` | device, item, system → space | chandelier → living room, though it hangs elsewhere in the tree |
| `consumable_for` | item → item, device, system | filter → well pump |

Modules add types under their namespace, such as `knx.group_link`.

**Proposed: relations link entities only.** v0.3 also had `documented_by`, `serviced_by` and `lent_to`, but their targets are not entities:

- a document is an attachment, which already points at its entity;
- people and contacts are not things in the house.

So "lent to a neighbour until Sunday" becomes `status = lent` plus a `core.loan` aspect (to whom, until when). "Serviced by" belongs to the maintenance design, where contacts live.

## 7. Provenance

Every field that holds a value can say where the value came from. A provenance record has:

- `field`: the aspect type and a JSON Pointer into its data, such as `core.product#/model`. A core entity field has no pointer: `name`, `parent`.
- `source`: `user`, `photo_ai`, `receipt`, `design` (from a drawing), `import:<importer>`, `bus`, `module:<id>`.
- `status`: `confirmed`, `observed`, `assumed` or `unknown`. Confirmed means a person said so. Observed means it was seen on a photo or the bus. Assumed means a guess by a person or the assistant. Unknown means the field matters, but nobody knows its value yet.
- `observed_at`, the `actor`, and the `changeset_id` if the value came through a changeset.

A direct edit by a person records `source=user`, `status=confirmed`. A field with no record is treated the same way. Most fields are typed in by hand, and an extra row for each would add nothing.

**Proposed: one value per field, and conflicts live in changesets.** v0.3 says the system shows both values when an import disagrees with a person. It does not say where the second value is kept. This design keeps it as a proposal:

1. The value in the aspect is the accepted one, and its provenance row describes it.
2. A source may overwrite a value directly only if its status is at least as strong as the current one. The order is `confirmed` > `observed` > `assumed` > `unknown`; within the same status, the newer value wins.
3. Otherwise the source creates an operation in a changeset. "The ETS import says model X, you said model Y" is then simply an open operation, shown wherever the field is shown.

So the provenance table holds one row per field, and every disagreement goes through the one review flow.

Device state and telemetry, such as a temperature or "the light is on", are not fields and have no provenance rows. They belong to the devices design.

## 8. Freshness

The registry fails when people stop trusting it, so each entity says how fresh its location is:

| Freshness | When |
|---|---|
| `fresh` | Verified within the threshold for its kind |
| `stale` | Verified longer ago |
| `doubtful` | Never verified, `status = missing`, or an open changeset proposes another place |

Verifying sets `verified_at` and `verified_by`. These verify an entity:

- the explicit "it's here" command;
- "found it there" after an assistant answer;
- confirming the entity in a photo revision;
- moving it, because whoever moves a thing has seen it.

**Proposed thresholds:**

| Kind | Threshold |
|---|---|
| item | 90 days |
| device | 180 days |
| container, space | 365 days |
| property, building, floor, system | never stale |

A home can override the thresholds later. Freshness is computed when read, never stored. The weekly revision queue ("photograph your tool box") picks entities by `verified_at`, which has an index.

## 9. Commands and the journal

### 9.1 One path for every change

Every change is a command, handled by one use case:

1. Authorise the actor for the target (section 11).
2. Validate the input, including aspect schemas.
3. Open a unit of work, load the aggregate and call the domain method.
4. Save the state and append the events to the journal. Both happen in the same transaction, so they cannot disagree.

Commands from HTTP take an `Idempotency-Key`, so a retry from a phone on a bad connection does not create a second vacuum cleaner. Changes to an existing resource take `If-Match` with its version.

### 9.2 State first, journal beside it

**Proposed: the core is not event-sourced.** The tables hold the current state, and that state is the truth. The journal is an append-only record of what happened, used for:

- the history of an entity ("where was the vacuum cleaner in March?");
- the audit trail ("who turned the light on at 3 a.m.?");
- the feed that the search index, notifications and hubs follow.

Rebuilding state by replaying events would make every schema change a replay problem. It would also gain nothing that the journal and changeset reverts do not already give.

### 9.3 The event envelope

| Field | Meaning |
|---|---|
| `seq` | The order of events within one transaction and a tie-breaker; with `tx`, the position readers keep (section 9.4) |
| `tx` | The id of the transaction that wrote the event |
| `id` | UUIDv7 of the event |
| `home_id` | The home the event belongs to |
| `type`, `version` | `entity.moved`, version 1; module events carry their namespace (`knx.bus.offline`) |
| `entity_id` | The main entity, if any |
| `actor` | `{kind: user \| device \| link \| module \| hub \| system, id, on_behalf_of}` |
| `command_id`, `changeset_id` | What caused it |
| `at` | When it happened, UTC |
| `payload` | What changed. Ids, plus the names they had then, so history reads well after a rename |

The core event types: `entity.created`, `entity.updated`, `entity.moved`, `entity.verified`, `entity.archived`, `entity.restored`, `aspect.set`, `aspect.removed`, `relation.added`, `relation.removed`, `changeset.opened`, `changeset.applied`, `changeset.rejected`, `changeset.reverted`, `grant.created`, `grant.revoked`. Other contexts add theirs, such as `task.done`, in their own designs.

### 9.4 Reading the journal safely

`seq` comes from a sequence, and transactions commit in a different order than they take numbers. A reader that asks for "everything after 41" can see 43 while 42 is still uncommitted, move its cursor to 43 and lose 42 for ever. Every reader of the journal, the hub sync included, avoids this the same way.

**Proposed: readers follow transactions, not the sequence.**

- Every event row stores the id of the transaction that wrote it: `tx xid8 DEFAULT pg_current_xact_id()`.
- A reader reads only rows whose transaction is older than the oldest transaction still running: `tx < pg_snapshot_xmin(pg_current_snapshot())`. Such a transaction has finished, so no row of it can appear later.
- A reader orders by `(tx, seq)` and keeps that pair as its cursor. The next read asks for rows after the pair, under the new limit.

A row skipped this way is never lost: it is read on the next pass, once its transaction has finished. The price is a delay: a long transaction anywhere in the database holds every reader back until it ends. Commands are short, and long jobs run in batches (section 10.2), so the delay stays small.

### 9.5 Where the journal lives

**Proposed: in a schema of its own, `journal`, owned by the platform context.** v0.3 put it in `registry`, but identity, changes and maintenance write events too. Every context appends through one port from the shared kernel. The table is partitioned by month on `at` with pg-partsmith, and kept for ever by default: history is a feature, and a home's export includes it.

## 10. Changesets

### 10.1 What is in one

A changeset has an `origin`: `assistant`, `importer:<id>`, `revision`, `hub:<id>` or `module:<id>`. It holds an ordered list of operations:

| Operation | Effect |
|---|---|
| `create_entity` | A new entity. It gets a temporary reference, so later operations in the same changeset can point at it |
| `update_entity` | Name, aliases, quantity, status, privacy |
| `set_aspect`, `remove_aspect` | Set fields of one aspect, or remove it |
| `move` | A new parent |
| `relate`, `unrelate` | Add or remove a relation |
| `archive`, `restore` | Leave the home, or come back |
| `verify` | Confirm the place |

Each operation carries its source, its provenance status, a confidence from 0 to 1 for automatic sources, and the `version` of its target when it was proposed. Each operation also gets its own decision: `pending`, `accepted`, `rejected` or `superseded`.

### 10.2 Life cycle

```
draft --> open --> applied | partially_applied | rejected
                   applied | partially_applied --> reverted
```

- **draft**: the producer is still adding operations; nobody sees the changeset yet.
- **open**: waiting for a person. Duplicate detection has run: it compares names and aliases by trigram, and matches serial numbers, EANs and designations. Likely duplicates are shown as "probably the same as D1 already in the registry".
- **Applying** runs the accepted operations as core commands, so access and the journal follow the one path of section 9. Before an operation runs, its target's version is compared with the proposed one. On a mismatch the operation is not applied: it goes back to the person as "changed since it was proposed".
- **A small changeset**, up to 500 operations, applies in one transaction. **A larger one** applies in batches through the `ApplyChangeset` Temporal workflow. Each batch is atomic, and the revert covers them all.
- **Reverting** applies the stored inverse of each applied operation, recorded when it was applied, as a new set of commands. An inverse whose target changed since is skipped and reported, never forced.

### 10.3 Rules

- Small edits by a person in the interface, such as a rename or a move, apply directly without a changeset.
- Auto-accept is off by default. A home can turn it on for chosen origins above a confidence threshold. Auto-accepted operations are still journalled with their changeset.
- Proposing needs `edit`, or the `entities:propose` permission of a module. Applying needs `edit` on the target of every operation.
- The changes context owns changesets but never writes entities itself. It calls the registry's public application port, so the registry stays the only writer of the tree.

## 11. Access

### 11.1 Roles and permissions

The permissions are those of v0.3:

- `view`;
- `edit`;
- `control`;
- `control_critical`;
- `tasks`;
- `private`;
- `admin`.

**Proposed: a fixed set of roles for v1.** Custom roles come later, if households ask for them.

| Role | Permissions |
|---|---|
| `owner` | all; the only role that can delete the home or transfer ownership |
| `admin` | all |
| `family` | view, edit, control, tasks |
| `guest` | view (guest-visible only, section 11.3), control |
| `contractor` | view, tasks |

### 11.2 Grants

A grant gives a role to a principal (`user`, `device` or `link`) over a scope, which is an entity's subtree or the whole home. It may have an expiry; for a guest the expiry is required and defaults to three days. A grant is revoked by setting `revoked_at`, never by deleting the row, so the journal can explain past access.

What a principal may do with an entity is the union of the permissions of its active grants whose scope contains the entity: the whole home, or `scope.path @> entity.path`. The query for one entity reads that entity's path once. A list query puts the same condition into SQL, so access is filtered in the query, not after it.

### 11.3 Privacy

- **`private`** hides an entity and its whole subtree from anyone without the `private` permission. A safe hides what is inside it. `core.address` and plan sheets are private whatever their entity's flag.
- **`guest_visible`** marks what a guest may see. A guest sees guest-visible entities in their scope, plus only the names of their ancestors, so that "the towels are in the bathroom cabinet" makes sense.
- **`normal`** is everything else.

The assistant and search apply the same rules before the model sees anything.

### 11.4 Acting on behalf of someone

A module or the assistant acts on behalf of a person. What it may do is the intersection of that person's permissions and the permissions the module's manifest declares. A hub automation acts on behalf of the person who created it, and it stops when that person loses access.

**Proposed: no row-level security in PostgreSQL for v1.** Access is checked in the application layer, in one place per query, and tested there. Row-level security as a second line of defence would complicate pooled connections and migrations. It can be added later without changing the model.

## 12. Storage layout

Every bounded context keeps its tables in its own PostgreSQL schema. Foreign keys across schemas point only at `identity.homes` and `registry.entities`, so the contexts could be separated later. Every table has `home_id`, and its indexes start with it. All times are `timestamptz` in UTC. The sketch below shows the tables this document defines; the order of statements is for reading, not for running. `created_at` and `updated_at` exist everywhere and are left out.

```sql
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- identity
CREATE TABLE identity.users (
  id uuid PRIMARY KEY, display_name text NOT NULL, locale text NOT NULL
);
CREATE TABLE identity.homes (
  id uuid PRIMARY KEY, name text NOT NULL, timezone text NOT NULL, locale text NOT NULL,
  settings jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE identity.grants (
  id uuid PRIMARY KEY,
  home_id uuid NOT NULL REFERENCES identity.homes ON DELETE CASCADE,
  principal_type text NOT NULL CHECK (principal_type IN ('user', 'device', 'link')),
  principal_id uuid NOT NULL,
  role text NOT NULL CHECK (role IN ('owner', 'admin', 'family', 'guest', 'contractor')),
  scope_entity_id uuid REFERENCES registry.entities,  -- NULL: the whole home
  expires_at timestamptz, revoked_at timestamptz,
  CHECK (role <> 'owner' OR (scope_entity_id IS NULL AND expires_at IS NULL)),
  CHECK (role <> 'guest' OR expires_at IS NOT NULL)
);
CREATE UNIQUE INDEX grants_one_owner ON identity.grants (home_id)
  WHERE role = 'owner' AND revoked_at IS NULL;
CREATE INDEX ON identity.grants (principal_id) WHERE revoked_at IS NULL;

-- registry
CREATE TABLE registry.entities (
  id uuid PRIMARY KEY,
  home_id uuid NOT NULL REFERENCES identity.homes ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN
    ('property', 'building', 'floor', 'space', 'container', 'item', 'system', 'device')),
  parent_id uuid REFERENCES registry.entities,
  path ltree NOT NULL,
  name text NOT NULL, aliases text[] NOT NULL DEFAULT '{}',
  quantity numeric, unit text,
  status text NOT NULL DEFAULT 'present' CHECK (status IN ('present', 'missing', 'lent', 'in_repair')),
  privacy text NOT NULL DEFAULT 'normal' CHECK (privacy IN ('normal', 'guest_visible', 'private')),
  verified_at timestamptz, verified_by uuid,
  archived_at timestamptz, archive_reason text,
  version int NOT NULL DEFAULT 1,
  CHECK ((parent_id IS NULL) = (kind = 'property')),
  CHECK ((archived_at IS NULL) = (archive_reason IS NULL))
);
CREATE INDEX ON registry.entities USING gist (path);
CREATE INDEX ON registry.entities (home_id, parent_id);
CREATE INDEX ON registry.entities (home_id, verified_at) WHERE archived_at IS NULL;
CREATE INDEX ON registry.entities USING gin (name gin_trgm_ops);

CREATE TABLE registry.aspect_types (
  type text PRIMARY KEY, owner text NOT NULL, version int NOT NULL,
  schema jsonb NOT NULL, kinds text[] NOT NULL
);
CREATE TABLE registry.aspects (
  entity_id uuid NOT NULL REFERENCES registry.entities ON DELETE CASCADE,
  type text NOT NULL REFERENCES registry.aspect_types,
  home_id uuid NOT NULL, data jsonb NOT NULL, version int NOT NULL,
  PRIMARY KEY (entity_id, type)
);
CREATE INDEX ON registry.aspects USING gin (data jsonb_path_ops);

CREATE TABLE registry.field_sources (
  entity_id uuid NOT NULL REFERENCES registry.entities ON DELETE CASCADE,
  field text NOT NULL,                          -- core.product#/model, name, parent
  home_id uuid NOT NULL,
  source text NOT NULL,
  status text NOT NULL CHECK (status IN ('confirmed', 'observed', 'assumed', 'unknown')),
  observed_at timestamptz NOT NULL, actor jsonb NOT NULL, changeset_id uuid,
  PRIMARY KEY (entity_id, field)
);

CREATE TABLE registry.relation_types (
  type text PRIMARY KEY, owner text NOT NULL, version int NOT NULL, declaration jsonb NOT NULL
);
CREATE TABLE registry.relations (
  id uuid PRIMARY KEY, home_id uuid NOT NULL,
  from_id uuid NOT NULL REFERENCES registry.entities ON DELETE CASCADE,
  to_id uuid NOT NULL REFERENCES registry.entities ON DELETE CASCADE,
  type text NOT NULL REFERENCES registry.relation_types,
  data jsonb NOT NULL DEFAULT '{}',
  UNIQUE (from_id, to_id, type)
);
CREATE INDEX ON registry.relations (to_id, type);

-- changes
CREATE TABLE changes.changesets (
  id uuid PRIMARY KEY, home_id uuid NOT NULL,
  origin text NOT NULL,
  status text NOT NULL CHECK (status IN
    ('draft', 'open', 'applied', 'partially_applied', 'rejected', 'reverted')),
  summary text, created_by jsonb NOT NULL, decided_by uuid, decided_at timestamptz
);
CREATE TABLE changes.operations (
  id uuid PRIMARY KEY,
  changeset_id uuid NOT NULL REFERENCES changes.changesets ON DELETE CASCADE,
  seq int NOT NULL, op text NOT NULL, target_entity_id uuid, target_ref text,
  payload jsonb NOT NULL, base_version int,
  source text NOT NULL, status text NOT NULL, confidence real CHECK (confidence BETWEEN 0 AND 1),
  decision text NOT NULL DEFAULT 'pending' CHECK (decision IN
    ('pending', 'accepted', 'rejected', 'superseded')),
  inverse jsonb,                                -- recorded when applied, used by revert
  UNIQUE (changeset_id, seq)
);
CREATE INDEX ON changes.operations (target_entity_id) WHERE decision = 'pending';

-- journal: append-only, monthly partitions (pg-partsmith)
CREATE TABLE journal.events (
  seq bigserial, id uuid NOT NULL, home_id uuid NOT NULL,   -- identity columns need PostgreSQL 17 on partitioned tables
  type text NOT NULL, version int NOT NULL, entity_id uuid,
  actor jsonb NOT NULL, command_id uuid, changeset_id uuid,
  tx xid8 NOT NULL DEFAULT pg_current_xact_id(),
  at timestamptz NOT NULL, payload jsonb NOT NULL,
  PRIMARY KEY (seq, at)
) PARTITION BY RANGE (at);
CREATE INDEX ON journal.events (tx, seq);
CREATE INDEX ON journal.events (home_id, tx, seq);
CREATE INDEX ON journal.events (entity_id, at);
```

How the schema maps onto aggregates:

- **The `Entity` aggregate** is a row of `entities` with its `aspects` and `field_sources`. They are saved together in one unit of work, guarded by `version`. Relations are a separate aggregate: an edge belongs to neither of its ends.
- **`aspect_types` and `relation_types`** are written only by migrations, from the declarations in code. The rows exist so that SQL can check foreign keys and the web app can fetch schemas.
- **Search columns** (`tsvector`, embeddings) belong to the search design.

## 13. In the code

| Context | Package | Holds |
|---|---|---|
| registry | `features/core/registry` | entities, the tree, aspects, relations, provenance, freshness |
| identity | `features/support/identity` | users, homes, grants, the access check |
| changes | `features/support/changes` | changesets, duplicate detection, apply and revert |
| platform | `features/support/platform` | the journal, aspect and relation type registration, modules later |
| shared kernel | `features/shared` | ids, `Actor`, `Kind`, permission names, the journal port, the access port |

Inside each feature the layers are `api -> use_cases -> domain`, with `infra` implementing the domain's interfaces. A context calls another only through that context's application port; it never reads the other's tables.

## 14. Checked against the scenarios

| Scenario | How the model answers |
|---|---|
| "Where is the vacuum cleaner?" | Trigram and full-text match on name and aliases, then `path` gives "House › Ground floor › Storage room", with freshness from `verified_at` |
| Enter a room from a photo in ten minutes | The assistant builds one changeset of `create_entity` and `set_aspect` operations with `photo_ai`/`observed` provenance; the person ticks them |
| Find the washing machine's warranty and receipt | `core.warranty` and `core.purchase` on the item; the receipt is an attachment |
| Give a guest access for the weekend | A `guest` grant on the house, expiring Sunday evening; only guest-visible entities show |
| An ETS import that disagrees with a hand-entered model | The import's value is weaker than `confirmed`, so it becomes an open operation shown on the field |
| A switched-off KNX module | `knx.*` aspects hidden but kept; the actuator is still an item in the distribution board |

## 15. What comes next

1. **The persistence foundation:**
   - PostgreSQL through sqlalchemy-foundation-kit, and Alembic migrations tested with alembic-gauntlet in CI;
   - the `identity`, `registry` and `journal` schemas from section 12;
   - a development stack in `scripts/dev` with PostgreSQL and S3.
2. **The first use cases:** create a home with its owner grant, and create, move, rename, archive and verify entities, with journal events and access checks.
3. **Designs of their own** for documents, the module manifest and access/sign-in, before their code.

## 16. Open questions

Every **Proposed** decision above, in one list, with the recommendation:

| # | Question | Recommendation |
|---|---|---|
| 1 | Ownership as a grant, with no `owner_id` on the home (section 3) | Yes: one source of truth |
| 2 | Containment rules per kind, checked in the domain (4.1) | Yes, with the table as written |
| 3 | A system is logical; parts join it by `part_of` (4.1) | Yes: the tree stays physical |
| 4 | Archiving apart from `status` (4.2) | Yes |
| 5 | Relations link entities only; loans and contacts go elsewhere (6) | Yes |
| 6 | One value per field; disagreements are changeset operations (7) | Yes: one review flow for everything |
| 7 | Freshness thresholds per kind (8) | Start with the table; tune on real use |
| 8 | State-based core with a journal, not event sourcing (9.2) | Yes |
| 9 | The journal's own schema; readers follow `(tx, seq)` below the oldest running transaction (9.4, 9.5) | Yes |
| 10 | Fixed roles for v1 (11.1) | Yes |
| 11 | No row-level security for v1 (11.4) | Yes; revisit before a hosted offering |
| 12 | Schemas carry i18n keys (5.1) | Yes: the interface has no hard-coded strings |
| 13 | Internal event delivery | Let internal handlers read the journal by cursor, like a log. The outbox then only serves external brokers, and Kafka stays optional. This is the open question about events; it gets its own short design |
| 14 | A shared product catalogue (one card for identical items) | Not in v1: `core.product` on each item; a catalogue can come later without changing entities |
| 15 | Custom fields defined by a household | Not in v1: aspect types are declared in code only |
