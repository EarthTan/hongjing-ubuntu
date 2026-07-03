"""Tests for MVP-4: unit roster (infantry / rocket / light tank / heavy tank).

Covers:
  - Stats table: 4 kinds, distinct HP/attack/range/speed/cost
  - spawn_unit: deducts cost, places near producing building
  - take_damage + remove_dead
  - tick_units: IDLE -> MOVING -> arrival
  - PlayerState.war_factory prerequisite gates unit production
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from engine.buildings import (
    Building,
    BuildingKind,
    PlayerState,
    place_building,
)
from engine.tilemap import TileMap, generate_default_map
from engine.units import (
    BARRACKS_PRODUCES,
    BUILDING_PRODUCES,
    UNIT_STATS,
    WAR_FACTORY_PRODUCES,
    Unit,
    UnitKind,
    UnitState,
    can_produce,
    ensure_units,
    order_move,
    remove_dead,
    spawn_unit,
    take_damage,
    tick_units,
)
from engine.world import World


# ---------------------------------------------------------------------------
# Stats table
# ---------------------------------------------------------------------------
def test_all_four_unit_kinds_exist():
    assert set(UNIT_STATS.keys()) == set(UnitKind)


def test_stats_have_required_attributes():
    for kind, s in UNIT_STATS.items():
        assert s.cost > 0, f"{kind} must cost credits"
        assert s.hp > 0, f"{kind} must have HP"
        assert s.attack > 0, f"{kind} must have an attack value"
        assert s.attack_range > 0, f"{kind} must have a range"
        assert s.speed > 0, f"{kind} must move"


def test_infantry_is_cheapest_and_weakest():
    inf = UNIT_STATS[UnitKind.INFANTRY]
    heavy = UNIT_STATS[UnitKind.HEAVY_TANK]
    assert inf.cost < heavy.cost
    assert inf.hp < heavy.hp
    assert inf.attack < heavy.attack


def test_heavy_tank_is_slowest_of_tanks():
    light = UNIT_STATS[UnitKind.LIGHT_TANK]
    heavy = UNIT_STATS[UnitKind.HEAVY_TANK]
    assert light.speed > heavy.speed
    assert heavy.hp > light.hp
    assert heavy.attack > light.attack


def test_rocket_outranges_infantry():
    inf = UNIT_STATS[UnitKind.INFANTRY]
    rocket = UNIT_STATS[UnitKind.ROCKET]
    assert rocket.attack_range > inf.attack_range


def test_barracks_produces_infantry_and_rocket():
    assert set(BARRACKS_PRODUCES) == {UnitKind.INFANTRY, UnitKind.ROCKET}


def test_war_factory_produces_tanks():
    assert set(WAR_FACTORY_PRODUCES) == {UnitKind.LIGHT_TANK, UnitKind.HEAVY_TANK}


def test_building_produces_map_covers_both_factories():
    assert BuildingKind.BARRACKS in BUILDING_PRODUCES
    assert BuildingKind.WAR_FACTORY in BUILDING_PRODUCES


# ---------------------------------------------------------------------------
# Prereq / affordability
# ---------------------------------------------------------------------------
def test_can_produce_false_without_barracks():
    p = PlayerState(id=0, credits=10_000)
    assert not can_produce(p, UnitKind.INFANTRY)


def test_can_produce_true_with_barracks():
    p = PlayerState(id=0, credits=10_000)
    p.buildings.append(Building(kind=BuildingKind.BARRACKS, col=5, row=5, owner_id=0))
    assert can_produce(p, UnitKind.INFANTRY)


def test_can_produce_false_for_tank_without_war_factory():
    p = PlayerState(id=0, credits=10_000)
    p.buildings.append(Building(kind=BuildingKind.BARRACKS, col=5, row=5, owner_id=0))
    assert not can_produce(p, UnitKind.LIGHT_TANK)


def test_can_produce_false_when_broke():
    p = PlayerState(id=0, credits=10)
    p.buildings.append(Building(kind=BuildingKind.BARRACKS, col=5, row=5, owner_id=0))
    assert not can_produce(p, UnitKind.INFANTRY)


# ---------------------------------------------------------------------------
# Spawning
# ---------------------------------------------------------------------------
def test_spawn_unit_deducts_cost_and_appends():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    barracks = Building(kind=BuildingKind.BARRACKS, col=10, row=10, owner_id=0)
    p.buildings.append(barracks)
    cost = UNIT_STATS[UnitKind.INFANTRY].cost
    before = p.credits
    u = spawn_unit(p, tm, UnitKind.INFANTRY, near=barracks)
    assert u is not None
    assert u.kind == UnitKind.INFANTRY
    assert u.owner_id == 0
    assert u.hp == UNIT_STATS[UnitKind.INFANTRY].hp
    assert p.credits == before - cost
    assert len(ensure_units(p)) == 1


def test_spawn_unit_finds_free_adjacent_tile():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    barracks = Building(kind=BuildingKind.BARRACKS, col=20, row=20, owner_id=0)
    p.buildings.append(barracks)
    u = spawn_unit(p, tm, UnitKind.INFANTRY, near=barracks)
    assert u is not None
    # Adjacent within a small spiral radius
    assert abs(u.col - 20) <= 3 and abs(u.row - 20) <= 3
    # Walkable
    assert tm.is_walkable(u.col, u.row)


def test_spawn_unit_returns_none_when_cannot_afford():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10)
    p.buildings.append(Building(kind=BuildingKind.BARRACKS, col=10, row=10, owner_id=0))
    assert spawn_unit(p, tm, UnitKind.INFANTRY) is None


def test_spawn_unit_returns_none_without_building_prereq():
    """No barracks → can't produce an infantry (cost deducted from a player that
    technically passes the credits check, but the prereq gates the spawn)."""
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    assert spawn_unit(p, tm, UnitKind.INFANTRY) is None


def test_spawn_unit_finds_producing_building_when_no_anchor():
    """If no anchor passed, the helper auto-discovers a building that produces
    the requested kind."""
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    p.buildings.append(Building(kind=BuildingKind.WAR_FACTORY, col=12, row=12, owner_id=0))
    u = spawn_unit(p, tm, UnitKind.LIGHT_TANK)
    assert u is not None
    assert abs(u.col - 12) <= 3 and abs(u.row - 12) <= 3


# ---------------------------------------------------------------------------
# Damage / death
# ---------------------------------------------------------------------------
def test_take_damage_reduces_hp():
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=0, row=0, hp=60)
    died = take_damage(u, 20)
    assert died is False
    assert u.hp == 40


def test_take_damage_signals_death_at_zero_hp():
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=0, row=0, hp=10)
    died = take_damage(u, 25)
    assert died is True
    assert u.hp == 0


def test_take_damage_dead_unit_does_not_double_kill():
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=0, row=0, hp=0)
    died = take_damage(u, 5)
    assert died is False
    assert u.hp == 0


def test_remove_dead_strips_zero_hp_units():
    p = PlayerState(id=0)
    units = ensure_units(p)
    units.append(Unit(kind=UnitKind.INFANTRY, owner_id=0, col=0, row=0, hp=0))
    units.append(Unit(kind=UnitKind.INFANTRY, owner_id=0, col=0, row=0, hp=30))
    n = remove_dead(p)
    assert n == 1
    assert len(units) == 1
    assert units[0].hp == 30


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------
def test_order_move_sets_moving_state_and_target():
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=0, row=0, hp=60)
    order_move(u, 5, 7)
    assert u.state == UnitState.MOVING
    assert u.target_col == 5
    assert u.target_row == 7


def test_tick_units_idle_unit_does_nothing():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0)
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=10, row=10, hp=60)
    ensure_units(p).append(u)
    tick_units(tm, [p], dt=1.0)
    assert u.col == 10 and u.row == 10
    assert u.state == UnitState.IDLE


def test_tick_units_moves_unit_toward_target():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0)
    u = Unit(kind=UnitKind.LIGHT_TANK, owner_id=0, col=10, row=10, hp=120, state=UnitState.MOVING)
    u.target_col, u.target_row = 14, 12
    ensure_units(p).append(u)
    # Light tank speed = 5 tiles/sec, 1s tick. A* (MVP-6) takes the diagonal
    # path so 4 diagonals reach the goal in 4 steps (we have 5 max).
    tick_units(tm, [p], dt=1.0)
    assert u.col == 14 and u.row == 12
    # Arrived — should be IDLE.
    assert u.state == UnitState.IDLE
    # A second tick should remain idle.
    tick_units(tm, [p], dt=1.0)
    assert u.col == 14 and u.row == 12
    assert u.state == UnitState.IDLE


def test_tick_units_blocks_on_water():
    """A unit told to move into water shouldn't be able to (we use the spawner's
    axis-fallback: if the chosen axis is blocked, the unit stalls instead of
    walking onto an unwalkable tile)."""
    tm = TileMap(8, 8)
    # Wall of water at column 5
    for r in range(8):
        tm.set(5, r, 1)  # WATER
    p = PlayerState(id=0)
    u = Unit(kind=UnitKind.LIGHT_TANK, owner_id=0, col=2, row=2, hp=120, state=UnitState.MOVING)
    u.target_col, u.target_row = 7, 2
    ensure_units(p).append(u)
    tick_units(tm, [p], dt=1.0)
    # Must not have walked onto the water column; movement should stall.
    assert u.col < 5


def test_tick_units_moves_multiple_units():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0)
    units = ensure_units(p)
    a = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=10, row=10, hp=60, state=UnitState.MOVING)
    a.target_col, a.target_row = 11, 10
    b = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=20, row=20, hp=60, state=UnitState.MOVING)
    b.target_col, b.target_row = 21, 20
    units.extend([a, b])
    tick_units(tm, [p], dt=1.0)
    assert a.col == 11
    assert b.col == 21


# ---------------------------------------------------------------------------
# World integration
# ---------------------------------------------------------------------------
def test_world_all_units_empty_for_default_world():
    w = World.new_default(64, 64, 1024, 768, seed=1)
    assert w.all_units() == []


def test_world_tick_drives_unit_movement():
    w = World.new_default(64, 64, 1024, 768, seed=1)
    p = w.get_player(0)
    p.credits = 10_000
    place_building(w.tilemap, w.players, 0, BuildingKind.BARRACKS, 10, 10)
    place_building(w.tilemap, w.players, 0, BuildingKind.WAR_FACTORY, 14, 10)
    # Spawn an infantry directly to avoid the build-queue waiting on power.
    from engine.units import spawn_unit
    u = spawn_unit(p, w.tilemap, UnitKind.LIGHT_TANK, near=p.buildings[-1])
    assert u is not None
    start = (u.col, u.row)
    # Issue a short move order (1 tile east). Light tank speed=5 t/s.
    from engine.units import order_move
    order_move(u, u.col + 1, u.row)
    w.tick(dt=1.0)
    # Light tank should have arrived and idled.
    assert (u.col, u.row) != start
    assert u.state == UnitState.IDLE


def test_world_default_player_has_no_units_yet():
    """Default world has only the yard → no units produced automatically."""
    w = World.new_default(64, 64, 1024, 768, seed=1)
    assert len(w.all_units()) == 0
