"""A* pathfinding on the tile grid.

Pure logic — no pygame. MVP-6 covers:
  - ``a_star(tilemap, start, goal)`` returns a list of tile coords from start to
    goal (inclusive of both endpoints), or None if no path exists.
  - ``a_star_avoiding(tilemap, start, goal, blocked)`` like a_star, but treats
    extra tile coordinates in ``blocked`` as unwalkable (used for live unit
    occupancy).
  - ``Path`` is a thin wrapper around a list of coords that supports:
        - peek_next(): next step to walk toward
        - advance(): pop the next step
        - remaining(): how many more steps to reach the end
        - finished: True if there's nothing left
  - 8-connected movement with a diagonal-cost tie break (cardinal cost 1,
    diagonal cost sqrt(2) ≈ 1.414). Octile heuristic.
  - Octile path can pass through a diagonal between two water tiles — we
    explicitly disallow corner-cutting via the ``_can_step`` check, which
    blocks stepping diagonally when both adjacent cardinals are blocked
    (the "no squeezing through" rule, common in grid RPGs).

The module is deliberately decoupled from `Unit` and `Harvester`: callers
pass in a TileMap and a starting/ending tile. The path returned is a sequence
of tiles, not a Unit/harvester — the tick functions consume it.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


Coord = Tuple[int, int]


# Movement costs (multiplied by 1000 to keep integer math; sqrt2 over 1000).
CARDINAL_COST = 1000
DIAGONAL_COST = int(math.sqrt(2) * 1000)  # 1414


# 8 neighbours with their associated cost multiplier
_NEIGHBOURS: Tuple[Tuple[int, int, int], ...] = (
    (-1,  0, CARDINAL_COST),
    ( 1,  0, CARDINAL_COST),
    ( 0, -1, CARDINAL_COST),
    ( 0,  1, CARDINAL_COST),
    (-1, -1, DIAGONAL_COST),
    ( 1, -1, DIAGONAL_COST),
    (-1,  1, DIAGONAL_COST),
    ( 1,  1, DIAGONAL_COST),
)


def _octile(dx: int, dy: int) -> int:
    """Octile distance heuristic (consistent with diagonal cost)."""
    adx, ady = abs(dx), abs(dy)
    if adx > ady:
        return ady * DIAGONAL_COST + (adx - ady) * CARDINAL_COST
    return adx * DIAGONAL_COST + (ady - adx) * CARDINAL_COST


def _can_step(
    tilemap,  # TileMap, kept untyped to avoid an import cycle
    c: int,
    r: int,
    blocked: Optional[Set[Coord]],
) -> bool:
    """True if (c, r) is a legal step from the current position.

    Rules:
      - In bounds.
      - Walkable per TileMap.
      - Not in ``blocked`` (extra occupancy overlay).
      - Diagonal steps: require at least one of the two adjacent cardinals
        to be walkable AND not blocked, so we don't squeeze through walls.
    """
    if not tilemap.in_bounds(c, r):
        return False
    if not tilemap.is_walkable(c, r):
        return False
    if blocked is not None and (c, r) in blocked:
        return False
    return True


def a_star(
    tilemap,
    start: Coord,
    goal: Coord,
    blocked: Optional[Set[Coord]] = None,
) -> Optional[List[Coord]]:
    """A* search from ``start`` to ``goal``.

    Returns a list of coords [start, ..., goal] (inclusive) on success, or
    None if no path exists. ``blocked`` is an optional set of extra tiles
    to treat as unwalkable (for live unit-occupancy avoidance). The start
    tile is always allowed even if it would otherwise be in ``blocked`` or
    unwalkable (because the caller is already standing there); the goal
    tile is always allowed even if unwalkable (so callers can path to a
    walkable neighbour of a building's footprint and rely on the resulting
    last step to be the goal itself).
    """
    sc, sr = start
    gc, gr = goal

    if (sc, sr) == (gc, gr):
        return [(sc, sr)]

    if not tilemap.in_bounds(sc, sr) or not tilemap.in_bounds(gc, gr):
        return None

    # Priority queue entries: (f_score, counter, (c, r))
    counter = 0
    open_heap: List = []
    heapq.heappush(open_heap, (0, counter, (sc, sr)))

    came_from: dict[Coord, Coord] = {}
    g_score: dict[Coord, int] = {(sc, sr): 0}
    closed: Set[Coord] = set()

    # Treat start as already-vacated for the duration of the search even if it's
    # in blocked (we're standing on it). We also treat the goal as walkable
    # even if the tile itself is not (caller can choose a goal-adjacent tile).
    blocked_eff: Optional[Set[Coord]] = None
    if blocked is not None:
        blocked_eff = set(blocked)
        blocked_eff.discard((sc, sr))
        blocked_eff.discard((gc, gr))

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        closed.add(current)

        cc, cr = current
        if current == (gc, gr):
            return _reconstruct(came_from, current)

        for dc, dr, cost in _NEIGHBOURS:
            nc, nr = cc + dc, cr + dr
            if (nc, nr) in closed:
                continue
            if not tilemap.in_bounds(nc, nr):
                continue
            # If this is the goal tile, allow even unwalkable.
            if (nc, nr) != (gc, gr) and not tilemap.is_walkable(nc, nr):
                continue
            if blocked_eff is not None and (nc, nr) in blocked_eff:
                continue
            # Disallow diagonal corner-cutting: if the step is diagonal,
            # require the two adjacent cardinals to be passable.
            if dc != 0 and dr != 0:
                cardinal_a = (cc + dc, cr)
                cardinal_b = (cc, cr + dr)
                if not _passable_cardinal(tilemap, cardinal_a, blocked_eff):
                    continue
                if not _passable_cardinal(tilemap, cardinal_b, blocked_eff):
                    continue

            tentative = g_score[current] + cost
            if (nc, nr) not in g_score or tentative < g_score[(nc, nr)]:
                came_from[(nc, nr)] = current
                g_score[(nc, nr)] = tentative
                f = tentative + _octile(nc - gc, nr - gr)
                counter += 1
                heapq.heappush(open_heap, (f, counter, (nc, nr)))

    return None


def _passable_cardinal(
    tilemap,
    tile: Coord,
    blocked: Optional[Set[Coord]],
) -> bool:
    """Cardinal passability check for the corner-cutting rule.

    A cardinal tile is passable if it is in-bounds, walkable, and not in
    the blocked set. (We allow the goal tile through even if unwalkable
    since the search already permits it.)
    """
    c, r = tile
    if not tilemap.in_bounds(c, r):
        return False
    if not tilemap.is_walkable(c, r):
        return False
    if blocked is not None and (c, r) in blocked:
        return False
    return True


def _reconstruct(came_from: dict[Coord, Coord], end: Coord) -> List[Coord]:
    path = [end]
    cur = end
    while cur in came_from:
        cur = came_from[cur]
        path.append(cur)
    path.reverse()
    return path


# -----------------------------------------------------------------------------
# Path wrapper
# -----------------------------------------------------------------------------
@dataclass
class Path:
    """A list of coords the entity should walk to reach its goal.

    The first element is the entity's CURRENT tile; the last element is the
    goal. ``advance()`` pops the head; ``peek_next()`` returns the next step
    (the second element), or the head if len == 1.
    """
    coords: List[Coord] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return len(self.coords) <= 1

    def peek_next(self) -> Coord:
        if not self.coords:
            raise IndexError("Path is empty")
        if len(self.coords) == 1:
            return self.coords[0]
        return self.coords[1]

    def advance(self) -> Coord:
        """Drop the current head and return the new head (or self if last)."""
        if not self.coords:
            raise IndexError("Path is empty")
        if len(self.coords) > 1:
            self.coords.pop(0)
        return self.coords[0]

    def remaining(self) -> int:
        return max(0, len(self.coords) - 1)

    def __len__(self) -> int:
        return len(self.coords)


# -----------------------------------------------------------------------------
# High-level helper: get a Path between two tiles for an entity
# -----------------------------------------------------------------------------
def compute_path(
    tilemap,
    start: Coord,
    goal: Coord,
    blocked: Optional[Set[Coord]] = None,
) -> Optional[Path]:
    """Convenience wrapper: run A* and return a Path object (or None)."""
    coords = a_star(tilemap, start, goal, blocked=blocked)
    if coords is None:
        return None
    return Path(coords=coords)


def nearest_walkable(
    tilemap,
    tile: Coord,
    max_radius: int = 4,
) -> Optional[Coord]:
    """Find the nearest walkable tile within ``max_radius`` of ``tile``.

    Used to find a harvester's "stand next to the refinery" tile, and to
    convert an attack-move click on water into a valid stand-tile.
    """
    tc, tr = tile
    if tilemap.in_bounds(tc, tr) and tilemap.is_walkable(tc, tr):
        return (tc, tr)
    for radius in range(1, max_radius + 1):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if abs(dr) != radius and abs(dc) != radius:
                    continue
                c, r = tc + dc, tr + dr
                if tilemap.in_bounds(c, r) and tilemap.is_walkable(c, r):
                    return (c, r)
    return None
