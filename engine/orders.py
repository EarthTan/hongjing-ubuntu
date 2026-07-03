"""Order dispatch for MVP-5 (move / attack / attack-move).

Pure logic — no pygame. Lives separately from ``engine.units`` so the unit
module stays focused on per-unit physics. Order kinds are:

    - MOVE:        walk to a tile
    - ATTACK_UNIT: pursue and fire at a specific enemy unit
    - ATTACK_BUILDING: pursue and fire at a specific enemy building
    - ATTACK_MOVE: walk to a tile, but auto-acquire any enemy unit/building
                   along the way (the "A" keybind in classic RTS).

Each unit carries the order on its dataclass (see ``Order`` below). The tick
loop calls ``tick_orders`` *after* ``tick_units`` — or, more simply, the
existing unit tick reads ``u.order`` and does the right thing. To keep MVP-4
behavior intact, we add the new fields only as optional; missing values fall
back to the original MOVE state machine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from .buildings import Building, PlayerState
from .tilemap import TileMap
from .units import (
    UNIT_STATS,
    Unit,
    UnitState,
    ensure_units,
    order_move,
)


Coord = Tuple[int, int]


class OrderKind(str, Enum):
    MOVE = "move"
    ATTACK_UNIT = "attack_unit"
    ATTACK_BUILDING = "attack_building"
    ATTACK_MOVE = "attack_move"  # walk + auto-acquire


@dataclass
class Order:
    """One order attached to a unit. ``target_*`` are looked up each tick by id
    so the references stay live even when target lists mutate."""
    kind: OrderKind
    target_col: int
    target_row: int
    # For ATTACK_UNIT / ATTACK_BUILDING: remember (owner_id, index) so we can
    # resolve to the live Unit/Building each tick.
    target_owner_id: Optional[int] = None
    target_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Issuing orders
# ---------------------------------------------------------------------------
def issue_move(units: List[Unit], tile: Coord) -> int:
    """Set MOVE order on every unit in ``units``. Returns count ordered."""
    n = 0
    col, row = tile
    for u in units:
        order_move(u, col, row)
        # Strip any prior attack info so this is a pure move.
        u.order = Order(kind=OrderKind.MOVE, target_col=col, target_row=row)
        n += 1
    return n


def issue_attack_unit(units: List[Unit], enemy_unit: Unit, enemy_player_id: int) -> int:
    """Order every unit in ``units`` to attack a specific enemy unit."""
    n = 0
    for u in units:
        # Move to the enemy's current tile and chase.
        order_move(u, enemy_unit.col, enemy_unit.row)
        u.order = Order(
            kind=OrderKind.ATTACK_UNIT,
            target_col=enemy_unit.col,
            target_row=enemy_unit.row,
            target_owner_id=enemy_player_id,
            # We can't easily keep the index without coupling to PlayerState here,
            # but resolve_target() does a coordinate lookup each tick.
        )
        n += 1
    return n


def issue_attack_building(units: List[Unit], enemy_building: Building, enemy_player_id: int) -> int:
    """Order every unit in ``units`` to attack a specific enemy building."""
    n = 0
    for u in units:
        # Aim at the building's centroid tile (top-left).
        order_move(u, enemy_building.col, enemy_building.row)
        u.order = Order(
            kind=OrderKind.ATTACK_BUILDING,
            target_col=enemy_building.col,
            target_row=enemy_building.row,
            target_owner_id=enemy_player_id,
        )
        n += 1
    return n


def issue_attack_move(units: List[Unit], tile: Coord) -> int:
    """Order every unit in ``units`` to attack-move to a tile."""
    n = 0
    col, row = tile
    for u in units:
        order_move(u, col, row)
        u.order = Order(kind=OrderKind.ATTACK_MOVE, target_col=col, target_row=row)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Target lookup helpers
# ---------------------------------------------------------------------------
def find_unit_by_coord(players: List[PlayerState], owner_id: int, col: int, row: int) -> Optional[Unit]:
    for p in players:
        if p.id != owner_id:
            continue
        for u in ensure_units(p):
            if u.col == col and u.row == row:
                return u
    return None


def find_building_by_coord(players: List[PlayerState], owner_id: int, col: int, row: int) -> Optional[Building]:
    for p in players:
        if p.id != owner_id:
            continue
        for b in p.buildings:
            if (col, row) in b.tiles():
                return b
    return None


def find_enemy_unit_in_range(
    players: List[PlayerState],
    owner_id: int,
    col: int,
    row: int,
    rng: int,
) -> Optional[Tuple[PlayerState, Unit]]:
    """Return the closest enemy unit within ``rng`` tiles of (col, row)."""
    best: Optional[Tuple[PlayerState, Unit, int]] = None
    for p in players:
        if p.id == owner_id:
            continue
        for u in ensure_units(p):
            if u.is_dead:
                continue
            d = max(abs(u.col - col), abs(u.row - row))  # Chebyshev — matches attack_range semantics
            if d <= rng and (best is None or d < best[2]):
                best = (p, u, d)
    if best is None:
        return None
    return (best[0], best[1])


def find_enemy_building_in_range(
    players: List[PlayerState],
    owner_id: int,
    col: int,
    row: int,
    rng: int,
) -> Optional[Tuple[PlayerState, Building]]:
    """Return the closest enemy building within ``rng`` tiles (uses centroid
    of the building footprint)."""
    best: Optional[Tuple[PlayerState, Building, int]] = None
    for p in players:
        if p.id == owner_id:
            continue
        for b in p.buildings:
            bc = b.col + 1  # footprint is 2x2, centroid at +1,+1
            br = b.row + 1
            d = max(abs(bc - col), abs(br - row))
            if d <= rng and (best is None or d < best[2]):
                best = (p, b, d)
    if best is None:
        return None
    return (best[0], best[1])


# ---------------------------------------------------------------------------
# Tick: drive every unit's order.
# ---------------------------------------------------------------------------
def tick_orders(
    tilemap: TileMap,
    players: List[PlayerState],
    dt: float,
) -> None:
    """Advance every unit's order.

    Behaviour per OrderKind:
      - MOVE:        just rely on the existing per-tile movement (no auto-acquire).
      - ATTACK_UNIT: if in range, fire (MVP-7 adds visuals). If target dies, IDLE.
                     If out of range, move toward the target.
      - ATTACK_BUILDING: same, but against buildings.
      - ATTACK_MOVE: walk toward the destination; if an enemy enters range, switch
                     to attacking it (until it dies, then resume moving).

    MVP-5 only handles target-tracking and damage application — visuals (health
    bars, hit flashes, explosions) land in MVP-7.
    """
    for player in players:
        owner_id = player.id
        for u in ensure_units(player):
            if u.is_dead:
                continue
            order = getattr(u, "order", None)
            if order is None:
                continue  # legacy: no order attached — leave the unit alone.
            _drive_one(tilemap, players, owner_id, u, order, dt)


def _drive_one(
    tilemap: TileMap,
    players: List[PlayerState],
    owner_id: int,
    u: Unit,
    order: Order,
    dt: float,
) -> None:
    rng = UNIT_STATS[u.kind].attack_range
    attack = UNIT_STATS[u.kind].attack

    # ----- ATTACK_UNIT ----------------------------------------------------
    if order.kind == OrderKind.ATTACK_UNIT:
        # Resolve target by coord (live lookup so dead units vanish).
        tgt = find_unit_by_coord(players, order.target_owner_id or -1, order.target_col, order.target_row)
        if tgt is None or tgt.is_dead:
            u.order = None
            u.state = UnitState.IDLE
            return
        # Chase.
        order_move(u, tgt.col, tgt.row)
        # In range? Fire.
        d = max(abs(u.col - tgt.col), abs(u.row - tgt.row))
        if d <= rng:
            # We're in range; stop chasing and fire.
            u.state = UnitState.IDLE
            from .units import take_damage
            take_damage(tgt, attack)
            # Stay put until target dies.
            return
        return

    # ----- ATTACK_BUILDING -----------------------------------------------
    if order.kind == OrderKind.ATTACK_BUILDING:
        tgt = find_building_by_coord(players, order.target_owner_id or -1, order.target_col, order.target_row)
        if tgt is None:
            u.order = None
            u.state = UnitState.IDLE
            return
        # Chase.
        order_move(u, tgt.col, tgt.row)
        bc = tgt.col + 1
        br = tgt.row + 1
        d = max(abs(u.col - bc), abs(u.row - br))
        if d <= rng:
            u.state = UnitState.IDLE
            tgt.hp -= attack  # buildings take damage too
            if tgt.hp <= 0:
                tgt.hp = 0
                # Remove from owner when killed.
                owner = next(p for p in players if p.id == tgt.owner_id)
                if tgt in owner.buildings:
                    owner.buildings.remove(tgt)
                u.order = None
            return
        return

    # ----- ATTACK_MOVE ----------------------------------------------------
    if order.kind == OrderKind.ATTACK_MOVE:
        # Check for an enemy in range first.
        eu = find_enemy_unit_in_range(players, owner_id, u.col, u.row, rng)
        if eu is not None:
            ep, eu_obj = eu
            # Convert to ATTACK_UNIT.
            u.order = Order(
                kind=OrderKind.ATTACK_UNIT,
                target_col=eu_obj.col,
                target_row=eu_obj.row,
                target_owner_id=ep.id,
            )
            return
        eb = find_enemy_building_in_range(players, owner_id, u.col, u.row, rng)
        if eb is not None:
            ep, eb_obj = eb
            u.order = Order(
                kind=OrderKind.ATTACK_BUILDING,
                target_col=eb_obj.col,
                target_row=eb_obj.row,
                target_owner_id=ep.id,
            )
            return
        # Otherwise keep moving to the destination. Re-issue move to the
        # original tile in case axis-stepping got us stuck somewhere odd.
        order_move(u, order.target_col, order.target_row)
        # Arrived?
        if u.col == order.target_col and u.row == order.target_row:
            u.order = None
            u.state = UnitState.IDLE
        return

    # ----- MOVE -----------------------------------------------------------
    if order.kind == OrderKind.MOVE:
        if u.col == order.target_col and u.row == order.target_row:
            u.order = None
        return
