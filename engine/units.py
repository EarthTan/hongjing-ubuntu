"""Unit roster (infantry / rocket / light tank / heavy tank).

Pure logic, no pygame. MVP-4 covers:
  - 4 unit kinds with independent stats (HP / attack / range / speed)
  - Unit instances (col/row on the tile grid, owner, HP, movement state)
  - spawn_unit() placed adjacent to a producing building
  - tick_units() advances movement on the tile grid (axis-stepped; A* lands in MVP-6)
  - take_damage() applies damage and removes the unit on death

Building <-> unit wiring: MVP-4 only needs the bare unit data. Building "produces"
list will gate spawn in MVP-5/UI; the helper ``produces_kind`` here lets tests
assert the table without a building dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .buildings import (
    Building,
    BuildingKind,
    PlayerState,
    footprint_tiles,
)
from .tilemap import TileMap


Coord = Tuple[int, int]


# -----------------------------------------------------------------------------
# Unit kinds
# -----------------------------------------------------------------------------
class UnitKind(str, Enum):
    INFANTRY = "infantry"
    ROCKET = "rocket"
    LIGHT_TANK = "light_tank"
    HEAVY_TANK = "heavy_tank"


@dataclass(frozen=True)
class UnitStats:
    """Per-kind stat block.

    - cost:        credits to produce
    - hp:          max hit points
    - attack:      damage per hit (used by MVP-7)
    - attack_range: tile range (used by MVP-7)
    - speed:        tiles per second (MVP-4 only)
    - footprint:    (w, h) tile footprint; tanks are 1x1 in MVP-4 (simplicity)
    - prerequisites: building kinds that must exist before producing this unit
    """
    cost: int
    hp: int
    attack: int
    attack_range: int
    speed: float
    footprint_w: int = 1
    footprint_h: int = 1
    prerequisites: Tuple[BuildingKind, ...] = ()


# Tuned for the dummy-SDL dummy-AUDIO test rig: small numbers, easy to assert.
UNIT_STATS: Dict[UnitKind, UnitStats] = {
    UnitKind.INFANTRY: UnitStats(
        cost=100, hp=60, attack=8, attack_range=2, speed=3.0,
        prerequisites=(BuildingKind.BARRACKS,),
    ),
    UnitKind.ROCKET: UnitStats(
        cost=300, hp=50, attack=25, attack_range=6, speed=2.5,
        prerequisites=(BuildingKind.BARRACKS,),
    ),
    UnitKind.LIGHT_TANK: UnitStats(
        cost=700, hp=120, attack=20, attack_range=4, speed=5.0,
        prerequisites=(BuildingKind.WAR_FACTORY,),
    ),
    UnitKind.HEAVY_TANK: UnitStats(
        cost=1500, hp=300, attack=40, attack_range=5, speed=3.5,
        prerequisites=(BuildingKind.WAR_FACTORY,),
    ),
}


def produces_kind(building_kind: BuildingKind, unit_kind: UnitKind) -> bool:
    """True if a building of ``building_kind`` is allowed to produce ``unit_kind``."""
    s = UNIT_STATS[unit_kind]
    return building_kind in s.prerequisites


# -----------------------------------------------------------------------------
# Building → unit-kind production map (MVP-4 wiring; UI consumes in MVP-5)
# -----------------------------------------------------------------------------
BARRACKS_PRODUCES: Tuple[UnitKind, ...] = (UnitKind.INFANTRY, UnitKind.ROCKET)
WAR_FACTORY_PRODUCES: Tuple[UnitKind, ...] = (UnitKind.LIGHT_TANK, UnitKind.HEAVY_TANK)

BUILDING_PRODUCES: Dict[BuildingKind, Tuple[UnitKind, ...]] = {
    BuildingKind.BARRACKS: BARRACKS_PRODUCES,
    BuildingKind.WAR_FACTORY: WAR_FACTORY_PRODUCES,
}


# -----------------------------------------------------------------------------
# Unit instance + state
# -----------------------------------------------------------------------------
class UnitState(str, Enum):
    IDLE = "idle"
    MOVING = "moving"


@dataclass
class Unit:
    """A live unit on the map."""
    kind: UnitKind
    owner_id: int
    col: int
    row: int
    hp: int
    state: UnitState = UnitState.IDLE
    target_col: int = 0
    target_row: int = 0

    @property
    def max_hp(self) -> int:
        return UNIT_STATS[self.kind].hp

    @property
    def is_dead(self) -> bool:
        return self.hp <= 0

    def footprint(self) -> Tuple[int, int]:
        s = UNIT_STATS[self.kind]
        return (s.footprint_w, s.footprint_h)


# -----------------------------------------------------------------------------
# PlayerState extension: units list
# -----------------------------------------------------------------------------
def ensure_units(player: PlayerState) -> List[Unit]:
    """Return player's unit list, attaching the field if missing."""
    if not hasattr(player, "units"):
        player.units = []  # type: ignore[attr-defined]
    return player.units  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# Spawning
# -----------------------------------------------------------------------------
def can_produce(
    player: PlayerState,
    unit_kind: UnitKind,
) -> bool:
    """True if the player has at least one of the prerequisite buildings and can pay."""
    s = UNIT_STATS[unit_kind]
    if player.credits < s.cost:
        return False
    have = {b.kind for b in player.buildings}
    for prereq in s.prerequisites:
        if prereq not in have:
            return False
    return True


def spawn_unit(
    player: PlayerState,
    tilemap: TileMap,
    unit_kind: UnitKind,
    near: Building | Coord | None = None,
) -> Optional[Unit]:
    """Spawn a new unit of ``unit_kind`` for ``player``.

    Placement strategy:
      1. If ``near`` is a Building, look for a free walkable tile adjacent to it.
      2. If ``near`` is a Coord, place at that tile if walkable & free.
      3. Otherwise, look for any building the player owns that can produce this
         unit and try to spawn adjacent to the first one found.
      4. Last resort: scan the whole map for a walkable, unoccupied tile.

    The unit's cost is deducted from the player. Returns None if placement fails
    or the player cannot afford it.
    """
    s = UNIT_STATS[unit_kind]
    if player.credits < s.cost:
        return None

    # Resolve anchor
    anchor: Coord | None = None
    if isinstance(near, Building):
        anchor = (near.col, near.row)
    elif isinstance(near, tuple) and len(near) == 2:
        anchor = near

    if anchor is None:
        # find any producing building
        produces = BUILDING_PRODUCES
        for b in player.buildings:
            if b.kind in produces and unit_kind in produces[b.kind]:
                anchor = (b.col, b.row)
                break

    if anchor is None:
        # last-resort: scan all buildings owned by player
        for b in player.buildings:
            anchor = (b.col, b.row)
            break

    if anchor is None:
        return None  # no buildings at all — nothing to anchor spawn to

    spot = _find_free_spot(tilemap, player, anchor, s.footprint_w, s.footprint_h)
    if spot is None:
        return None
    col, row = spot
    player.credits -= s.cost
    u = Unit(
        kind=unit_kind,
        owner_id=player.id,
        col=col,
        row=row,
        hp=s.hp,
    )
    ensure_units(player).append(u)
    return u


def _find_free_spot(
    tilemap: TileMap,
    player: PlayerState,
    anchor: Coord,
    w: int,
    h: int,
) -> Optional[Coord]:
    """Find a free walkable (w×h) tile near ``anchor`` that doesn't overlap
    any of the player's buildings, sites, or units."""
    occupied: set[Coord] = set()
    for b in player.buildings:
        occupied.update(footprint_tiles(b.col, b.row))
    # Construction sites also block (we use the same 2x2 footprint rules)
    for cs in player.constructing:
        occupied.update(footprint_tiles(cs.col, cs.row))
    for u in ensure_units(player):
        uw, uh = u.footprint()
        for dr in range(uh):
            for dc in range(uw):
                occupied.add((u.col + dc, u.row + dr))

    ac, ar = anchor
    # Spiral scan outward, snapping to top-left of the footprint
    limit = max(tilemap.width, tilemap.height)
    for radius in range(0, limit):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if radius > 0 and abs(dr) != radius and abs(dc) != radius:
                    continue  # outer ring only
                c, r = ac + dc, ar + dr
                # footprint of (w,h)
                tiles = [(c + x, r + y) for y in range(h) for x in range(w)]
                if not all(tilemap.in_bounds(tc, tr) for tc, tr in tiles):
                    continue
                if not all(tilemap.is_walkable(tc, tr) for tc, tr in tiles):
                    continue
                if any(t in occupied for t in tiles):
                    continue
                return (c, r)
    return None


# -----------------------------------------------------------------------------
# Damage / death
# -----------------------------------------------------------------------------
def take_damage(unit: Unit, amount: int) -> bool:
    """Apply damage. Returns True if the unit dies from this hit."""
    if unit.is_dead:
        return False
    unit.hp -= amount
    if unit.hp <= 0:
        unit.hp = 0
        return True
    return False


def remove_dead(player: PlayerState) -> int:
    """Strip dead units from the player's roster. Returns count removed."""
    units = ensure_units(player)
    before = len(units)
    units[:] = [u for u in units if not u.is_dead]
    return before - len(units)


# -----------------------------------------------------------------------------
# Movement / tick
# -----------------------------------------------------------------------------
def order_move(unit: Unit, col: int, target_row: int) -> None:
    unit.target_col = col
    unit.target_row = target_row
    unit.state = UnitState.MOVING


def tick_units(
    tilemap: TileMap,
    players: List[PlayerState],
    dt: float,
) -> None:
    """Advance every player's units by ``dt`` seconds.

    Movement is grid-aligned axis stepping (replaced by A* in MVP-6). Units with
    ``state == IDLE`` do nothing. Movement respects walkability; if the chosen
    axis is blocked, the unit tries the other axis; if both are blocked it stalls.
    """
    for player in players:
        for u in ensure_units(player):
            if u.state != UnitState.MOVING:
                continue
            _step_one(tilemap, u, dt)


def _step_one(tilemap: TileMap, u: Unit, dt: float) -> None:
    if u.col == u.target_col and u.row == u.target_row:
        u.state = UnitState.IDLE
        return
    speed = UNIT_STATS[u.kind].speed
    max_step = max(1, int(speed * dt))
    dc = u.target_col - u.col
    dr = u.target_row - u.row

    def _can_stand(c: int, r: int) -> bool:
        fw, fh = u.footprint()
        for dy in range(fh):
            for dx in range(fw):
                if not tilemap.is_walkable(c + dx, r + dy):
                    return False
        return True

    # Step one tile at a time along the axis so we never "teleport" past walls.
    moved = False
    for _ in range(max_step):
        if u.col == u.target_col and u.row == u.target_row:
            break
        advanced = False
        if dc != 0:
            step_x = 1 if dc > 0 else -1
            nx, ny = u.col + step_x, u.row
            if _can_stand(nx, ny):
                u.col, u.row = nx, ny
                dc = u.target_col - u.col
                advanced = True
        if not advanced and dr != 0:
            step_y = 1 if dr > 0 else -1
            nx, ny = u.col, u.row + step_y
            if _can_stand(nx, ny):
                u.col, u.row = nx, ny
                dr = u.target_row - u.row
                advanced = True
        if not advanced:
            # Stuck: cancel the move, idle so the player can re-issue.
            u.state = UnitState.IDLE
            moved = False
            break
        moved = True

    if u.col == u.target_col and u.row == u.target_row:
        u.state = UnitState.IDLE
        return
    if not moved and u.state == UnitState.MOVING:
        u.state = UnitState.IDLE
