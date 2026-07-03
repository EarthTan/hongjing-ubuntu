"""Resource loop: harvesters, ore mining, refinery unloading.

Pure logic, no pygame. MVP-3 covers:
  - Harvester unit (state machine: IDLE → MOVING_TO_ORE → MINING → MOVING_TO_REFINERY → UNLOADING → ...)
  - Auto-find nearest ore patch to mine
  - Auto-find nearest friendly refinery to deliver to
  - Each delivered load converts ore → player credits at the refinery
  - Refinery spawns new harvesters on construction (or via build menu stub)

The harvester moves on the tile grid one tile per ``move_tiles_per_sec`` per second
(simplified — no collision checks beyond walkability; full A* lands in MVP-6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional, Tuple

from .buildings import (
    BUILDING_FOOTPRINT_H,
    BUILDING_FOOTPRINT_W,
    Building,
    BuildingKind,
    PlayerState,
    footprint_tiles,
)
from .pathfinding import Path, compute_path, nearest_walkable
from .tilemap import TileMap


Coord = Tuple[int, int]


# Centroid offset inside a 2x2 footprint (for "next to refinery" placement).
# Top-left of a 2x2 → centroid is (col + 0.5, row + 0.5) tiles. We use the
# top-left as our anchor and rely on the adjacency scan to find a nearby walkable.
BUILDING_CX = BUILDING_FOOTPRINT_W // 2
BUILDING_CY = BUILDING_FOOTPRINT_H // 2


# -----------------------------------------------------------------------------
# Tuning constants
# -----------------------------------------------------------------------------
HARVESTER_COST = 1400          # cost to "produce" a harvester from a refinery (or instant-grant for MVP-3)
HARVESTER_CAPACITY = 700       # ore units per load
HARVESTER_MINE_RATE = 100.0    # ore units per second while MINING
HARVESTER_UNLOAD_RATE = 700.0  # ore units per second while UNLOADING (one full load per second)
HARVESTER_SPEED = 4.0          # tiles per second (movement on the tile grid)
HARVESTER_MINE_TIME = 2.0      # seconds spent at an ore patch before fully loaded (cap bounded by capacity)
ORE_VALUE_PER_UNIT = 1.0       # 1 ore → 1 credit on delivery


class HarvesterState(str, Enum):
    IDLE = "idle"
    MOVING_TO_ORE = "moving_to_ore"
    MINING = "mining"
    MOVING_TO_REFINERY = "moving_to_refinery"
    UNLOADING = "unloading"


@dataclass
class Harvester:
    """One harvester unit, owned by a player."""
    owner_id: int
    col: int          # current tile (col)
    row: int          # current tile (row)
    cargo: float = 0.0
    capacity: float = HARVESTER_CAPACITY
    state: HarvesterState = HarvesterState.IDLE
    target_col: int = 0
    target_row: int = 0
    state_timer: float = 0.0   # accumulates time spent in MINING / UNLOADING
    path: Optional[Path] = field(default=None)  # MVP-6 A* path to target


# -----------------------------------------------------------------------------
# Ore finding helpers
# -----------------------------------------------------------------------------
def nearest_ore(tilemap: TileMap, col: int, row: int, max_search: int = 999) -> Optional[Coord]:
    """Return (col, row) of nearest walkable ore tile, scanning in a square spiral.

    We bias toward the nearest ore by Manhattan distance. If none in range, return None.
    """
    # Spiral outward up to min(max_search, map size)
    limit = min(max_search, max(tilemap.width, tilemap.height))
    for radius in range(0, limit + 1):
        # At radius 0 just check the source tile
        if radius == 0:
            if tilemap.in_bounds(col, row) and tilemap.is_ore(col, row):
                return (col, row)
            continue
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if abs(dr) != radius and abs(dc) != radius:
                    continue  # only the outer ring
                c, r = col + dc, row + dr
                if tilemap.in_bounds(c, r) and tilemap.is_ore(c, r):
                    return (c, r)
    return None


def nearest_refinery(player: PlayerState, col: int, row: int) -> Optional[Building]:
    """Pick the closest REFINERY owned by ``player`` to (col, row)."""
    best: Optional[Building] = None
    best_d = 10**9
    for b in player.buildings:
        if b.kind != BuildingKind.REFINERY:
            continue
        # Distance to building centre tile (1-tile offset for a 2x2)
        bc = b.col + BUILDING_CX
        br = b.row + BUILDING_CY
        d = abs(bc - col) + abs(br - row)
        if d < best_d:
            best_d = d
            best = b
    return best


# -----------------------------------------------------------------------------
# PlayerState extension: harvesters list
# -----------------------------------------------------------------------------
def ensure_harvesters(player: PlayerState) -> List[Harvester]:
    """Return player's harvester list, attaching the field if missing."""
    if not hasattr(player, "harvesters"):
        player.harvesters = []  # type: ignore[attr-defined]
    return player.harvesters  # type: ignore[attr-defined]


def spawn_harvester(
    player: PlayerState,
    tilemap: TileMap,
    refinery: Building,
) -> Optional[Harvester]:
    """Spawn a new harvester adjacent to ``refinery`` (or at the refinery's tiles
    if no walkable adjacent spot is free). Returns None if the player has no refinery
    or no spot to spawn at.
    """
    harvesters = ensure_harvesters(player)
    spawn_tile = _find_spawn_spot(tilemap, refinery)
    if spawn_tile is None:
        return None
    h = Harvester(owner_id=player.id, col=spawn_tile[0], row=spawn_tile[1])
    harvesters.append(h)
    return h


def _find_spawn_spot(tilemap: TileMap, refinery: Building) -> Optional[Coord]:
    """Walk outward from the refinery's centre looking for a walkable tile that
    is NOT part of the refinery's footprint (so it doesn't overlap the building).
    """
    rc, rr = refinery.col, refinery.row
    # Centroid of a 2x2
    centre_c = rc + 0  # we use the top-left as the anchor; adjacency scanning below works
    centre_r = rr + 0
    # Adjacent tiles (8 neighbours + straight 4)
    for radius in (1, 2, 3):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if radius > 1 and abs(dr) != radius and abs(dc) != radius:
                    continue  # outer ring
                c, r = centre_c + dc, centre_r + dr
                if not tilemap.in_bounds(c, r):
                    continue
                if not tilemap.is_walkable(c, r):
                    continue
                # Must not overlap the refinery footprint
                if (c, r) in set(footprint_tiles(rc, rr)):
                    continue
                return (c, r)
    return None


# -----------------------------------------------------------------------------
# Tick
# -----------------------------------------------------------------------------
def tick_harvesters(
    tilemap: TileMap,
    players: List[PlayerState],
    dt: float,
) -> None:
    """Advance every player's harvesters by ``dt`` seconds.

    Each harvester runs its own state machine:
      IDLE:                            → find nearest ore, set target, go MOVING_TO_ORE
      MOVING_TO_ORE:                   step toward (target_col,target_row); on arrival → MINING
      MINING:                          accumulate cargo; when cargo==capacity → find refinery, MOVING_TO_REFINERY
      MOVING_TO_REFINERY:              step toward refinery; on arrival → UNLOADING
      UNLOADING:                       convert remaining cargo to credits at ORE_VALUE_PER_UNIT → IDLE
    """
    for player in players:
        harvesters = ensure_harvesters(player)
        for h in harvesters:
            _tick_one(tilemap, player, h, dt)


def _tick_one(tilemap: TileMap, player: PlayerState, h: Harvester, dt: float) -> None:
    if h.state == HarvesterState.IDLE:
        # Look for work — first try to deliver cargo if we have any, then go find ore.
        if h.cargo > 0.0:
            ref = nearest_refinery(player, h.col, h.row)
            if ref is not None:
                _head_to(h, ref.col + BUILDING_CX, ref.row + BUILDING_CY, HarvesterState.MOVING_TO_REFINERY)
                return
        ore = nearest_ore(tilemap, h.col, h.row)
        if ore is None:
            # Nothing to mine — stay idle
            return
        _head_to(h, ore[0], ore[1], HarvesterState.MOVING_TO_ORE)
        return

    if h.state == HarvesterState.MOVING_TO_ORE:
        if _step_toward(tilemap, h, h.target_col, h.target_row, dt):
            # Arrived at the ore tile
            if tilemap.is_ore(h.col, h.row):
                h.state = HarvesterState.MINING
                h.state_timer = 0.0
            else:
                # Ore tile moved/changed (e.g. mined out). Reset to IDLE and try again.
                h.state = HarvesterState.IDLE
        return

    if h.state == HarvesterState.MINING:
        h.state_timer += dt
        delta = HARVESTER_MINE_RATE * dt
        h.cargo = min(h.capacity, h.cargo + delta)
        if h.cargo >= h.capacity or h.state_timer >= HARVESTER_MINE_TIME and h.cargo >= h.capacity:
            # Full — head back
            ref = nearest_refinery(player, h.col, h.row)
            if ref is None:
                # No refinery — drop back to IDLE and try to find one later
                h.state = HarvesterState.IDLE
                h.state_timer = 0.0
                return
            _head_to(h, ref.col, ref.row, HarvesterState.MOVING_TO_REFINERY)
            h.state_timer = 0.0
        return

    if h.state == HarvesterState.MOVING_TO_REFINERY:
        if _step_toward(tilemap, h, h.target_col, h.target_row, dt):
            # Adjacent enough to start unloading
            h.state = HarvesterState.UNLOADING
            h.state_timer = 0.0
        return

    if h.state == HarvesterState.UNLOADING:
        h.state_timer += dt
        delta = HARVESTER_UNLOAD_RATE * dt
        converted = min(h.cargo, delta)
        h.cargo -= converted
        player.credits += int(converted * ORE_VALUE_PER_UNIT)
        if h.cargo <= 1e-6:
            h.cargo = 0.0
            h.state = HarvesterState.IDLE
            h.state_timer = 0.0
        return


# -----------------------------------------------------------------------------
# Movement (A* path-driven; MVP-6)
# -----------------------------------------------------------------------------
def _head_to(h: Harvester, col: int, row: int, next_state: HarvesterState) -> None:
    """Set a new destination and reset the A* path so the next tick recomputes.

    If the destination hasn't changed and the harvester is already in a moving
    state, we keep the existing path to avoid wasted replans.
    """
    moved_goal = (h.target_col, h.target_row) != (col, row)
    h.target_col = col
    h.target_row = row
    h.state = next_state
    if moved_goal:
        h.path = None


def _recompute_harvester_path(
    tilemap: TileMap,
    h: Harvester,
) -> bool:
    """Recompute the A* path for ``h`` toward its current target.

    If the target is unwalkable (e.g. inside a refinery footprint), fall back
    to the nearest walkable neighbour so the harvester stops beside the
    refinery rather than on top of it.
    """
    goal = (h.target_col, h.target_row)
    if not tilemap.in_bounds(*goal) or not tilemap.is_walkable(*goal):
        near = nearest_walkable(tilemap, goal, max_radius=3)
        if near is None or near == (h.col, h.row):
            return False
        h.target_col, h.target_row = near
        goal = near
    path = compute_path(tilemap, (h.col, h.row), goal)
    if path is None:
        # Try a nearest-walkable fallback for the start tile.
        near_goal = nearest_walkable(tilemap, goal, max_radius=3)
        if near_goal is None or near_goal == (h.col, h.row):
            return False
        h.target_col, h.target_row = near_goal
        path = compute_path(tilemap, (h.col, h.row), near_goal)
        if path is None:
            return False
    h.path = path
    return True


def _step_toward(tilemap: TileMap, h: Harvester, target_c: int, target_r: int, dt: float) -> bool:
    """Step toward the target by HARVESTER_SPEED * dt tiles along an A* path.

    Returns True on arrival. If no path is set, we compute one; if A* fails
    we return True to short-circuit the harvester out of the moving state
    (the state machine will re-route via nearest_ore/refinery on the next tick).
    """
    if h.col == target_c and h.row == target_r:
        return True

    if h.path is None:
        if not _recompute_harvester_path(tilemap, h):
            # Couldn't find a path; give up on this move (state machine
            # will re-pick a target on the next tick).
            return True

    max_step = max(1, int(HARVESTER_SPEED * dt))
    moved = False
    for _ in range(max_step):
        if h.path is None or h.path.finished:
            break
        if h.col == target_c and h.row == target_r:
            break
        nxt = h.path.peek_next()
        if nxt == (h.col, h.row):
            h.path.advance()
            if h.path.finished:
                break
            nxt = h.path.peek_next()
        h.col, h.row = nxt
        h.path.advance()
        moved = True
    if h.col == target_c and h.row == target_r:
        h.path = None
        return True
    if not moved:
        # Path dead-ended; clear it so the next tick can replan.
        h.path = None
    return False


# -----------------------------------------------------------------------------
# Refinery → harvester auto-production
# -----------------------------------------------------------------------------
def tick_refineries_spawn_harvesters(
    players: List[PlayerState],
    tilemap: TileMap,
    harvester_cost: int = HARVESTER_COST,
) -> None:
    """If a player has a refinery, ensure at least one harvester exists.

    MVP-3 simplification: the refinery grants a free harvester on first build,
    then auto-replaces it whenever the player can afford it and the player has
    fewer than ``MAX_HARVESTERS_PER_REFINERY`` harvesters. This keeps the resource
    loop alive without a build menu.
    """
    MAX_PER_REFINERY = 2  # MVP-3 keeps this small; raised later
    for player in players:
        refineries = [b for b in player.buildings if b.kind == BuildingKind.REFINERY]
        if not refineries:
            continue
        harvesters = ensure_harvesters(player)
        per_player_cap = MAX_PER_REFINERY * len(refineries)
        if len(harvesters) >= per_player_cap:
            continue
        if player.credits < harvester_cost:
            continue
        # Spawn at the first refinery that has a free spawn tile.
        for ref in refineries:
            h = spawn_harvester(player, tilemap, ref)
            if h is not None:
                player.credits -= harvester_cost
                break