"""Construction: building kinds, stats, building instances, power grid, build queue.

Pure logic — no pygame. MVP-2 covers:
  - 5 buildings (ConstructionYard / PowerPlant / Refinery / Barracks / WarFactory)
  - Power model (produced - consumed, low-power halts production)
  - Per-player build queue (FIFO of BuildingKind orders)
  - Construction yard blocked by base spot + existing buildings

New file landed in MVP-2.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Tuple

from .tilemap import TileMap


Coord = Tuple[int, int]  # tile (col, row)


class BuildingKind(str, Enum):
    CONSTRUCTION_YARD = "construction_yard"
    POWER_PLANT = "power_plant"
    REFINERY = "refinery"
    BARRACKS = "barracks"
    WAR_FACTORY = "war_factory"


# Stats table: every building is 2x2 tiles for simplicity.
# cost: starting credits to begin construction (refunded if cancelled mid-build? we don't refund — simpler).
# power: produced/consumed delta.
# build_time: seconds to construct.
# produces: list of unit kinds the building can spit out (filled later in MVP-4).
@dataclass(frozen=True)
class BuildingStats:
    cost: int
    power_produced: int       # + into grid
    power_consumed: int       # - from grid
    build_time: float         # seconds
    produces: Tuple[str, ...] = ()  # unit kinds, used in MVP-4+
    prerequisites: Tuple[BuildingKind, ...] = ()
    hp: int = 1000  # MVP-5+ combat HP (1000 default; can be tuned per kind)


# Buildable kinds (Construction Yard cannot be built by a yard; we treat it as initial-only — MVP-3 will let harvesters etc. fly it out, but for MVP-2 we hard-place the yard).
BUILDING_STATS: Dict[BuildingKind, BuildingStats] = {
    BuildingKind.CONSTRUCTION_YARD: BuildingStats(
        cost=2000, power_produced=0, power_consumed=20, build_time=0.0,
        hp=2000,
    ),
    BuildingKind.POWER_PLANT: BuildingStats(
        cost=300, power_produced=100, power_consumed=20, build_time=5.0,
        hp=800,
    ),
    BuildingKind.REFINERY: BuildingStats(
        cost=2000, power_produced=0, power_consumed=30, build_time=10.0,
        hp=900,
    ),
    BuildingKind.BARRACKS: BuildingStats(
        cost=300, power_produced=0, power_consumed=20, build_time=5.0,
        produces=("infantry", "rocket"),
        hp=800,
    ),
    BuildingKind.WAR_FACTORY: BuildingStats(
        cost=2000, power_produced=0, power_consumed=30, build_time=10.0,
        prerequisites=(BuildingKind.REFINERY,),
        produces=("light_tank", "heavy_tank"),
        hp=1000,
    ),
}

# Tile footprint (always 2x2 in MVP-2).
BUILDING_FOOTPRINT_W = 2
BUILDING_FOOTPRINT_H = 2


@dataclass
class Building:
    """A real (already constructed) building on the map."""
    kind: BuildingKind
    col: int
    row: int          # top-left tile
    owner_id: int     # 0 = player, 1 = enemy (post-MVP-8)
    hp: int = 0       # initialized in __post_init__ to stats.hp

    def __post_init__(self) -> None:
        # Default HP comes from stats; tests can override by passing hp= explicitly.
        if self.hp <= 0:
            self.hp = BUILDING_STATS[self.kind].hp

    def footprint(self) -> Tuple[int, int, int, int]:
        """Return (col, row, w, h) tile rect."""
        w, h = BUILDING_FOOTPRINT_W, BUILDING_FOOTPRINT_H
        return (self.col, self.row, w, h)

    def tiles(self) -> List[Coord]:
        cs, rs, w, h = self.footprint()
        return [(cs + dc, rs + dr) for dr in range(h) for dc in range(w)]

    @property
    def is_dead(self) -> bool:
        return self.hp <= 0


@dataclass
class ConstructionSite:
    """A building under construction; promotes to Building when progress >= build_time."""
    kind: BuildingKind
    col: int
    row: int
    owner_id: int
    progress: float = 0.0

    def is_done(self, stats: BuildingStats) -> bool:
        return self.progress >= stats.build_time


class PowerState(str, Enum):
    OK = "ok"
    LOW = "low"   # produced < consumed: production paused


@dataclass
class PowerGrid:
    """Just produced/consumed tally + state — no per-edge grid."""
    produced: int = 0
    consumed: int = 0

    def state(self) -> PowerState:
        return PowerState.OK if self.produced >= self.consumed else PowerState.LOW

    def is_low(self) -> bool:
        return self.produced < self.consumed


@dataclass
class BuildQueue:
    """FIFO queue of building orders for one player.

    `current_cost_paid` ensures we deduct the cost upfront (the simple model):
    if we cancel before completion, we just lose it (consistent with classic RTS "no refund").
    """
    pending: Deque[BuildingKind] = field(default_factory=deque)
    # Tracks whether the head item's cost has already been deducted (always True: we charge on enqueue).
    progress: float = 0.0  # 0..head_item's build_time

    def __len__(self) -> int:
        return len(self.pending)

    def head(self) -> BuildingKind | None:
        return self.pending[0] if self.pending else None


@dataclass
class PlayerState:
    """One player's economy + buildings + queue."""
    id: int
    credits: int = 5000           # starting cash so tests are deterministic
    buildings: List[Building] = field(default_factory=list)
    constructing: List[ConstructionSite] = field(default_factory=list)
    queue: BuildQueue = field(default_factory=BuildQueue)


# -----------------------------------------------------------------------------
# Power & economy math
# -----------------------------------------------------------------------------
def recompute_power(players: List[PlayerState], ids_filter: List[int] | None = None) -> Dict[int, PowerGrid]:
    """Sum produced/consumed per player across constructed (not under-construction) buildings."""
    out: Dict[int, PowerGrid] = {}
    for p in players:
        if ids_filter is not None and p.id not in ids_filter:
            continue
        g = PowerGrid()
        for b in p.buildings:
            s = BUILDING_STATS[b.kind]
            g.produced += s.power_produced
            g.consumed += s.power_consumed
        out[p.id] = g
    return out


# -----------------------------------------------------------------------------
# Placement & foot-printing
# -----------------------------------------------------------------------------
def footprint_tiles(col: int, row: int, w: int = BUILDING_FOOTPRINT_W, h: int = BUILDING_FOOTPRINT_H) -> List[Coord]:
    return [(col + dc, row + dr) for dr in range(h) for dc in range(w)]


def is_area_buildable(tilemap: TileMap, tiles: List[Coord]) -> bool:
    """All tiles must be in bounds and walkable (grass or ore). Water blocks construction.

    NOTE: building on ore is allowed — the refinery just sits on it. The harvesters extract ore anyway.
    """
    for c, r in tiles:
        if not tilemap.in_bounds(c, r):
            return False
        if not tilemap.is_walkable(c, r):
            return False
    return True


def overlaps_any(tiles: List[Coord], buildings: List[Building], sites: List[ConstructionSite]) -> bool:
    claimed = set()
    for b in buildings:
        for tc in b.tiles():
            claimed.add(tc)
    for s in sites:
        bw, bh = BUILDING_FOOTPRINT_W, BUILDING_FOOTPRINT_H
        for dr in range(bh):
            for dc in range(bw):
                claimed.add((s.col + dc, s.row + dr))
    return any(t in claimed for t in tiles)


def can_place(
    tilemap: TileMap,
    kind: BuildingKind,
    col: int,
    row: int,
    player: PlayerState,
) -> bool:
    """Check terrain + overlap + affordability + prerequisites."""
    s = BUILDING_STATS[kind]
    if player.credits < s.cost:
        return False
    # prerequisites: all of these must already be constructed for this player
    have = {b.kind for b in player.buildings}
    for prereq in s.prerequisites:
        if prereq not in have:
            return False
    tiles = footprint_tiles(col, row)
    if not is_area_buildable(tilemap, tiles):
        return False
    if overlaps_any(tiles, player.buildings, player.constructing):
        return False
    return True


def place_building(
    tilemap: TileMap,
    players: List[PlayerState],
    player_id: int,
    kind: BuildingKind,
    col: int,
    row: int,
) -> Building | None:
    """Atomic placement: deduct cost, push Building. Returns None if any check fails."""
    player = next(p for p in players if p.id == player_id)
    if not can_place(tilemap, kind, col, row, player):
        return None
    s = BUILDING_STATS[kind]
    player.credits -= s.cost
    b = Building(kind=kind, col=col, row=row, owner_id=player_id)
    player.buildings.append(b)
    return b


# -----------------------------------------------------------------------------
# Construction queue
# -----------------------------------------------------------------------------
class QueueErrorReason(str, Enum):
    OK = "ok"
    NO_MONEY = "no_money"
    MISSING_PREREQ = "missing_prereq"
    QUEUE_FULL = "queue_full"


QUEUE_MAX = 5  # soft cap per player


def enqueue(player: PlayerState, kind: BuildingKind) -> QueueErrorReason:
    if len(player.queue) >= QUEUE_MAX:
        return QueueErrorReason.QUEUE_FULL
    s = BUILDING_STATS[kind]
    if player.credits < s.cost:
        return QueueErrorReason.NO_MONEY
    for prereq in s.prerequisites:
        if prereq not in {b.kind for b in player.buildings}:
            return QueueErrorReason.MISSING_PREREQ
    # Refundable model: charge on enqueue.
    player.credits -= s.cost
    player.queue.pending.append(kind)
    return QueueErrorReason.OK


def tick_construction(
    tilemap: TileMap,
    players: List[PlayerState],
    player_id: int,
    requested_pos: Dict[BuildingKind, Coord] | None = None,
    dt: float = 1.0,
) -> ConstructionSite | None:
    """Advance construction for one player by dt seconds.

    Returns the just-completed site, if any, so callers can promote it to a Building.

    The yard needs a placement coord per item in the queue; if not given we lazy-pick
    the nearest walkable grass patch to existing buildings (MVP-3 will use harvesters
    to deploy, MVP-2 uses a simple "scaffold" placement).
    """
    player = next(p for p in players if p.id == player_id)
    grids = recompute_power(players, ids_filter=[player_id])
    grid = grids.get(player_id, PowerGrid())
    # Power low pauses production — except the head item is a power plant,
    # which is the AI/human's way to escape the low-power trap. Without this
    # carve-out, a brand-new yard can never finish its first power plant and
    # the base is stuck forever.
    if grid.is_low() and player.queue.pending:
        head = player.queue.head()
        if head != BuildingKind.POWER_PLANT:
            return None

    head_kind = player.queue.head()
    if head_kind is None:
        return None

    # Are we mid-site for the head already?
    site = next((s for s in player.constructing if s.kind == head_kind and s.owner_id == player_id), None)
    if site is None:
        # Place a scaffold site
        pos = (requested_pos or {}).get(head_kind)
        if pos is None:
            pos = _find_nearest_free_spot(tilemap, player, head_kind)
        if pos is None:
            return None  # no room — stall
        col, row = pos
        s = BUILDING_STATS[head_kind]
        site = ConstructionSite(kind=head_kind, col=col, row=row, owner_id=player_id)
        player.constructing.append(site)

    # Advance
    s = BUILDING_STATS[head_kind]
    site.progress += dt
    if site.is_done(s):
        # Promote
        player.constructing.remove(site)
        b = Building(kind=site.kind, col=site.col, row=site.row, owner_id=site.owner_id)
        player.buildings.append(b)
        player.queue.pending.popleft()
        player.queue.progress = 0.0
        return site
    return None


def _find_nearest_free_spot(tilemap: TileMap, player: PlayerState, kind: BuildingKind) -> Coord | None:
    """Greedy nearest-scanned free footprint, anchored on player buildings & sites."""
    # Anchor: centroid of existing + constructing
    anchors: List[Coord] = []
    for b in player.buildings:
        anchors.append((b.col, b.row))
    for s in player.constructing:
        anchors.append((s.col, s.row))
    if not anchors:
        cx, cy = tilemap.width // 2, tilemap.height // 2
    else:
        cx = sum(a[0] for a in anchors) // len(anchors)
        cy = sum(a[1] for a in anchors) // len(anchors)

    # Spiral scan for a 2x2 footprint that is grass+free.
    for radius in range(0, max(tilemap.width, tilemap.height)):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if abs(dr) != radius and abs(dc) != radius:
                    continue  # only outer ring of this radius
                col, row = cx + dc, cy + dr
                tiles = footprint_tiles(col, row)
                if not is_area_buildable(tilemap, tiles):
                    continue
                if overlaps_any(tiles, player.buildings, player.constructing):
                    continue
                return (col, row)
    return None
