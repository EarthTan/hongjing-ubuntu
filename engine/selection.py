"""Selection state and box-select helpers for MVP-5.

Pure logic — no pygame. Selection is owned by a ``SelectionState`` instance
held by the controller; the UI layer translates mouse drags into it and the
controller reads it to issue orders.

The box-select uses tile coords (col/row) — both the start anchor and the
current corner are stored in tile space. ``set_corner`` is called every
mouse-move while the left button is held; ``commit`` finalizes the box and
returns the selected unit indices.

We always operate on the *local* player (owner_id == 0). Other players' units
are visible but never selectable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from .buildings import Building, PlayerState
from .units import Unit, UnitState, ensure_units


Coord = Tuple[int, int]


# ---------------------------------------------------------------------------
# Selection box helpers
# ---------------------------------------------------------------------------
def normalize_box(a: Coord, b: Coord) -> Tuple[int, int, int, int]:
    """Return (c0, r0, c1, r1) so c0<=c1, r0<=r1."""
    c0, c1 = sorted((a[0], b[0]))
    r0, r1 = sorted((a[1], b[1]))
    return (c0, r0, c1, r1)


def point_in_box(p: Coord, box: Tuple[int, int, int, int]) -> bool:
    c, r = p
    c0, r0, c1, r1 = box
    return c0 <= c <= c1 and r0 <= r <= r1


def building_tiles(b: Building) -> List[Coord]:
    return b.tiles()


# ---------------------------------------------------------------------------
# Selection state
# ---------------------------------------------------------------------------
@dataclass
class SelectionState:
    """Mutable selection state for one player.

    - selected_unit_ids: indices into PlayerState.units of currently selected units
      (MVP-5 keeps a snapshot; for our purposes index-based is fine because we
      only mutate via the controller).
    - selected_building_index: index into PlayerState.buildings, or None.
    - box_start / box_current: tile coords while a box-drag is in progress.
    """
    selected_unit_ids: List[int] = field(default_factory=list)
    selected_building_index: Optional[int] = None
    box_start: Optional[Coord] = None
    box_current: Optional[Coord] = None
    # Whether the box-drag is currently active (left-mouse held)
    dragging: bool = False

    # ----- box drag -----
    def begin_box(self, tile: Coord) -> None:
        self.box_start = tile
        self.box_current = tile
        self.dragging = True

    def update_box(self, tile: Coord) -> None:
        if self.dragging:
            self.box_current = tile

    def end_box(self) -> Optional[Tuple[int, int, int, int]]:
        """Finalize the drag and return the normalized tile rect, or None."""
        self.dragging = False
        if self.box_start is None or self.box_current is None:
            self.box_start = None
            self.box_current = None
            return None
        box = normalize_box(self.box_start, self.box_current)
        self.box_start = None
        self.box_current = None
        return box

    def cancel_box(self) -> None:
        self.dragging = False
        self.box_start = None
        self.box_current = None

    def current_box_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Box rect while dragging, or None."""
        if not self.dragging or self.box_start is None or self.box_current is None:
            return None
        return normalize_box(self.box_start, self.box_current)

    # ----- units -----
    def clear_units(self) -> None:
        self.selected_unit_ids.clear()

    def select_units(self, indices: Iterable[int]) -> None:
        # Dedupe + sort for deterministic order.
        self.selected_unit_ids = sorted(set(indices))

    def add_units(self, indices: Iterable[int]) -> None:
        merged = set(self.selected_unit_ids) | set(indices)
        self.selected_unit_ids = sorted(merged)

    def toggle_unit(self, index: int) -> None:
        if index in self.selected_unit_ids:
            self.selected_unit_ids.remove(index)
        else:
            self.selected_unit_ids.append(index)
            self.selected_unit_ids.sort()

    def selected_units(self, player: PlayerState) -> List[Unit]:
        out: List[Unit] = []
        units = ensure_units(player)
        for i in self.selected_unit_ids:
            if 0 <= i < len(units):
                out.append(units[i])
        return out

    # ----- buildings -----
    def clear_building(self) -> None:
        self.selected_building_index = None

    def select_building(self, index: Optional[int]) -> None:
        self.selected_building_index = index

    def selected_building(self, player: PlayerState) -> Optional[Building]:
        if self.selected_building_index is None:
            return None
        buildings = player.buildings
        if 0 <= self.selected_building_index < len(buildings):
            return buildings[self.selected_building_index]
        return None

    def clear_all(self) -> None:
        self.clear_units()
        self.clear_building()


# ---------------------------------------------------------------------------
# Pickers: world -> "what's there?"
# ---------------------------------------------------------------------------
def unit_at_tile(player: PlayerState, col: int, row: int) -> Optional[int]:
    """Return the index of the first unit at (col, row) for the given player, or None."""
    units = ensure_units(player)
    for i, u in enumerate(units):
        if u.col == col and u.row == row:
            return i
    return None


def building_at_tile(player: PlayerState, col: int, row: int) -> Optional[int]:
    """Return the index of a building the player owns whose footprint contains (col, row)."""
    for i, b in enumerate(player.buildings):
        if (col, row) in building_tiles(b):
            return i
    return None


def enemy_units_at_tile(players: List[PlayerState], col: int, row: int, owner_id: int) -> Optional[Tuple[int, int]]:
    """Return (player_id, unit_index) for the first enemy unit at (col, row), or None."""
    for p in players:
        if p.id == owner_id:
            continue
        idx = unit_at_tile(p, col, row)
        if idx is not None:
            return (p.id, idx)
    return None


def enemy_buildings_at_tile(players: List[PlayerState], col: int, row: int, owner_id: int) -> Optional[Tuple[int, int]]:
    """Return (player_id, building_index) for an enemy building at (col, row), or None.

    MVP-5 looks at buildings only (since buildings don't have per-tile units).
    """
    for p in players:
        if p.id == owner_id:
            continue
        idx = building_at_tile(p, col, row)
        if idx is not None:
            return (p.id, idx)
    return None


def units_in_box(player: PlayerState, box: Tuple[int, int, int, int]) -> List[int]:
    """Indices of player's units inside the (c0, r0, c1, r1) tile box."""
    units = ensure_units(player)
    return [i for i, u in enumerate(units) if point_in_box((u.col, u.row), box)]


def enemy_units_in_box(players: List[PlayerState], box: Tuple[int, int, int, int], owner_id: int) -> List[Tuple[int, int]]:
    """Return (player_id, unit_index) for enemy units inside the box."""
    c0, r0, c1, r1 = box
    out: List[Tuple[int, int]] = []
    for p in players:
        if p.id == owner_id:
            continue
        for i, u in enumerate(ensure_units(p)):
            if point_in_box((u.col, u.row), box):
                out.append((p.id, i))
    return out


# ---------------------------------------------------------------------------
# Click resolution: single-click on a tile → what's there?
# ---------------------------------------------------------------------------
@dataclass
class ClickTarget:
    """What was under the cursor when the player right-clicked."""
    is_enemy_unit: bool = False
    is_enemy_building: bool = False
    is_own_unit: bool = False
    is_own_building: bool = False
    tile: Coord = (0, 0)
    # For convenience, pointers to the resolved entities (None when not applicable).
    own_unit_index: Optional[int] = None
    own_building_index: Optional[int] = None
    enemy_unit: Optional[Unit] = None
    enemy_building: Optional[Building] = None
    enemy_player_id: Optional[int] = None


def resolve_click(
    players: List[PlayerState],
    owner_id: int,
    tile: Coord,
) -> ClickTarget:
    """Classify what's at ``tile`` for the local player."""
    owner = next(p for p in players if p.id == owner_id)
    target = ClickTarget(tile=tile)
    target.own_unit_index = unit_at_tile(owner, tile[0], tile[1])
    if target.own_unit_index is not None:
        target.is_own_unit = True
    target.own_building_index = building_at_tile(owner, tile[0], tile[1])
    if target.own_building_index is not None:
        target.is_own_building = True
    eu = enemy_units_at_tile(players, tile[0], tile[1], owner_id)
    if eu is not None:
        pid, idx = eu
        target.is_enemy_unit = True
        target.enemy_player_id = pid
        target.enemy_unit = next(p for p in players if p.id == pid).units[idx]
    eb = enemy_buildings_at_tile(players, tile[0], tile[1], owner_id)
    if eb is not None:
        pid, idx = eb
        target.is_enemy_building = True
        target.enemy_player_id = pid
        target.enemy_building = next(p for p in players if p.id == pid).buildings[idx]
    return target
