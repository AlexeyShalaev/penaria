from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from penaria.features.core.registry.domain.entity import (
    ArchivedEntityError,
    Entity,
    InvalidEntityError,
    MisplacedEntityError,
)
from penaria.features.core.registry.domain.kinds import (
    MAX_DEPTH,
    ArchiveReason,
    Freshness,
    Kind,
    Status,
)
from penaria.features.shared.errors import StaleVersionError
from penaria.features.shared.ids import new_id

pytestmark = pytest.mark.unit

HOME = new_id()
NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


def make(kind: Kind, parent: Entity | None = None, name: str = "thing") -> Entity:
    return Entity.create(home_id=HOME, kind=kind, parent=parent, name=name)


def house() -> tuple[Entity, Entity, Entity]:
    plot = make(Kind.PROPERTY, name="Country house")
    building = make(Kind.BUILDING, plot, "House")
    room = make(Kind.SPACE, building, "Storage room")
    return plot, building, room


def test_the_path_runs_from_the_root_to_the_entity_itself() -> None:
    plot, building, room = house()

    assert room.path == (plot.id, building.id, room.id)
    assert room.parent_id == building.id


@pytest.mark.parametrize(
    ("kind", "parent_kind"),
    [
        (Kind.ITEM, Kind.BUILDING),
        (Kind.ITEM, None),
        (Kind.BUILDING, None),
        (Kind.FLOOR, Kind.PROPERTY),
        (Kind.DEVICE, Kind.SYSTEM),
        (Kind.PROPERTY, Kind.SPACE),
    ],
)
def test_kinds_sit_only_where_the_design_allows(kind: Kind, parent_kind: Kind | None) -> None:
    plot, building, room = house()
    parents = {None: None, Kind.PROPERTY: plot, Kind.BUILDING: building, Kind.SPACE: room}
    parent = parents.get(parent_kind) if parent_kind is not Kind.SYSTEM else make(Kind.SYSTEM, plot)

    with pytest.raises(MisplacedEntityError):
        make(kind, parent)


def test_a_system_holds_no_physical_things_but_may_hold_a_subsystem() -> None:
    plot, _, _ = house()
    heating = make(Kind.SYSTEM, plot, "Heating")

    assert make(Kind.SYSTEM, heating, "Underfloor heating").parent_id == heating.id
    with pytest.raises(MisplacedEntityError):
        make(Kind.ITEM, heating)


def test_names_and_aliases_are_tidied() -> None:
    _, _, room = house()
    item = Entity.create(
        home_id=HOME, kind=Kind.ITEM, parent=room, name="  Vacuum   cleaner ", aliases=("hoover", " hoover ", "")
    )

    assert item.name == "Vacuum cleaner"
    assert item.aliases == ("hoover",)


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_a_name_is_required_and_bounded(name: str) -> None:
    _, _, room = house()

    with pytest.raises(InvalidEntityError):
        make(Kind.ITEM, room, name)


def test_a_quantity_is_positive() -> None:
    _, _, room = house()

    with pytest.raises(InvalidEntityError):
        Entity.create(home_id=HOME, kind=Kind.ITEM, parent=room, name="plates", quantity=Decimal(0))


def test_update_reports_what_changed_and_bumps_the_version_once() -> None:
    _, _, room = house()
    item = make(Kind.ITEM, room, "Plates")

    changes = item.update(name="Plates", quantity=Decimal(12), status=Status.LENT)

    assert changes == {"quantity": {"from": None, "to": "12"}, "status": {"from": "present", "to": "lent"}}
    assert item.version == 2
    assert item.update(name="Plates") == {}
    assert item.version == 2


def test_a_stale_version_is_refused() -> None:
    _, _, room = house()

    with pytest.raises(StaleVersionError):
        make(Kind.ITEM, room).expect_version(7)


def test_moving_rewrites_the_path_and_verifies_the_place() -> None:
    plot, building, room = house()
    kitchen = make(Kind.SPACE, building, "Kitchen")
    item = make(Kind.ITEM, room)

    old = item.move_to(kitchen, subtree_height=0, by=new_id(), now=NOW)

    assert old == (plot.id, building.id, room.id, item.id)
    assert item.path == (plot.id, building.id, kitchen.id, item.id)
    assert item.verified_at == NOW


def test_an_entity_cannot_move_into_its_own_subtree() -> None:
    _, building, room = house()
    box = make(Kind.CONTAINER, room, "Box")
    inner = make(Kind.CONTAINER, box, "Inner box")

    with pytest.raises(MisplacedEntityError):
        box.move_to(inner, subtree_height=1, by=new_id(), now=NOW)
    with pytest.raises(MisplacedEntityError):
        room.move_to(building, subtree_height=MAX_DEPTH, by=new_id(), now=NOW)


def test_an_archived_entity_is_read_only_until_restored() -> None:
    _, _, room = house()
    item = make(Kind.ITEM, room)
    item.archive(ArchiveReason.DISCARDED, NOW)

    with pytest.raises(ArchivedEntityError):
        item.update(name="new name")
    with pytest.raises(ArchivedEntityError):
        make(Kind.ITEM, item)

    item.restore()
    assert item.update(name="new name")


@pytest.mark.parametrize(
    ("kind", "verified_ago", "status", "expected"),
    [
        (Kind.ITEM, timedelta(days=10), Status.PRESENT, Freshness.FRESH),
        (Kind.ITEM, timedelta(days=91), Status.PRESENT, Freshness.STALE),
        (Kind.ITEM, None, Status.PRESENT, Freshness.DOUBTFUL),
        (Kind.ITEM, timedelta(days=1), Status.MISSING, Freshness.DOUBTFUL),
        (Kind.SPACE, timedelta(days=300), Status.PRESENT, Freshness.FRESH),
        (Kind.BUILDING, None, Status.PRESENT, Freshness.FRESH),
    ],
)
def test_freshness_follows_the_thresholds(
    kind: Kind, verified_ago: timedelta | None, status: Status, expected: Freshness
) -> None:
    plot, building, room = house()
    parent = {Kind.ITEM: room, Kind.SPACE: building, Kind.BUILDING: plot}[kind]
    entity = make(kind, parent)
    entity.status = status
    entity.verified_at = NOW - verified_ago if verified_ago else None

    assert entity.freshness(NOW) is expected


def test_verifying_finds_a_missing_thing() -> None:
    _, _, room = house()
    item = make(Kind.ITEM, room)
    item.status = Status.MISSING
    by = new_id()

    item.verify(by, NOW)

    assert (item.status, item.verified_at, item.verified_by) == (Status.PRESENT, NOW, by)
