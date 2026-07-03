"""Tests for MVP-2: construction system (buildings / power / queue)."""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from engine.buildings import (
    BUILDING_FOOTPRINT_H,
    BUILDING_FOOTPRINT_W,
    BUILDING_STATS,
    Building,
    BuildingKind,
    PowerState,
    QueueErrorReason,
    can_place,
    enqueue,
    footprint_tiles,
    is_area_buildable,
    overlaps_any,
    place_building,
    recompute_power,
    tick_construction,
)
from engine.tilemap import TileMap, generate_default_map
from engine.world import World


# ---------------------------------------------------------------------------
# Stats table
# ---------------------------------------------------------------------------
def test_stats_table_has_all_five_kinds():
    assert set(BUILDING_STATS.keys()) == set(BuildingKind)


def test_yard_costs_nothing_to_build_initially():
    """Construction Yard is initial-only in MVP-2 (no build menu entry).

    We still document its cost, but it's already placed on the map at startup.
    """
    s = BUILDING_STATS[BuildingKind.CONSTRUCTION_YARD]
    assert s.build_time == 0.0


def test_war_factory_requires_refinery_prereq():
    s = BUILDING_STATS[BuildingKind.WAR_FACTORY]
    assert BuildingKind.REFINERY in s.prerequisites


def test_power_plant_is_net_producer():
    s = BUILDING_STATS[BuildingKind.POWER_PLANT]
    assert s.power_produced > s.power_consumed


# ---------------------------------------------------------------------------
# Footprint / area checks
# ---------------------------------------------------------------------------
def test_footprint_is_2x2():
    tiles = footprint_tiles(3, 4)
    assert tiles == [(3, 4), (4, 4), (3, 5), (4, 5)]


def test_area_unbuildable_on_water():
    tm = TileMap(4, 4, tiles=[[1] * 4 for _ in range(4)])  # all water
    assert not is_area_buildable(tm, footprint_tiles(0, 0))


def test_area_unbuildable_when_oob():
    tm = TileMap(4, 4)
    assert not is_area_buildable(tm, footprint_tiles(3, 3))  # (5,5) tile is OOB
    assert is_area_buildable(tm, footprint_tiles(0, 0))


def test_overlap_blocks_second_building():
    tiles = footprint_tiles(5, 5)
    b = Building(kind=BuildingKind.POWER_PLANT, col=5, row=5, owner_id=0)
    assert overlaps_any(tiles, [b], [])
    assert not overlaps_any(footprint_tiles(8, 8), [b], [])


# ---------------------------------------------------------------------------
# Power grid
# ---------------------------------------------------------------------------
def test_power_grid_no_buildings_is_zero():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    grids = recompute_power(world.players)
    # Player has the yard (consume=20), so produced=0, consumed=20, state=LOW.
    g = grids[0]
    assert g.produced == 0
    assert g.consumed >= 20
    assert g.is_low()


def test_power_grid_low_state_flag():
    from engine.buildings import PowerGrid
    g = PowerGrid(produced=50, consumed=100)
    assert g.state() == PowerState.LOW
    g2 = PowerGrid(produced=100, consumed=100)
    assert g2.state() == PowerState.OK


def test_adding_power_plant_flips_to_ok():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    # Clear some space next to the yard (yard occupies 5,5..6,6)
    p.credits = 10_000
    # place at (8,5) — should be grass on default map
    b = place_building(tm, world.players, 0, BuildingKind.POWER_PLANT, 8, 5)
    assert b is not None
    grids = recompute_power(world.players)
    g = grids[0]
    # yard consume 20 + plant consume 20 = 40; plant produce 100 → OK
    assert g.produced >= 100
    assert g.consumed == 40
    assert g.state() == PowerState.OK


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
def test_cannot_afford_building():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 100
    assert not can_place(tm, BuildingKind.REFINERY, 8, 8, p)


def test_cannot_build_war_factory_without_refinery():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    assert not can_place(tm, BuildingKind.WAR_FACTORY, 10, 10, p)


def test_place_building_deducts_cost():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    cost = BUILDING_STATS[BuildingKind.POWER_PLANT].cost
    before = p.credits
    b = place_building(tm, world.players, 0, BuildingKind.POWER_PLANT, 8, 5)
    assert b is not None
    assert p.credits == before - cost


def test_place_returns_none_on_failure():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    # (5,5) already has yard — overlapping placement should fail.
    assert place_building(tm, world.players, 0, BuildingKind.POWER_PLANT, 5, 5) is None


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
def test_enqueue_charges_upfront_and_stores_order():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    cost = BUILDING_STATS[BuildingKind.POWER_PLANT].cost
    before = p.credits
    r = enqueue(p, BuildingKind.POWER_PLANT)
    assert r == QueueErrorReason.OK
    assert p.credits == before - cost
    assert len(p.queue) == 1
    assert p.queue.head() == BuildingKind.POWER_PLANT


def test_enqueue_rejects_when_no_money():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 50
    assert enqueue(p, BuildingKind.POWER_PLANT) == QueueErrorReason.NO_MONEY


def test_enqueue_respects_prereq():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    assert enqueue(p, BuildingKind.WAR_FACTORY) == QueueErrorReason.MISSING_PREREQ


def test_enqueue_queue_full():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    for _ in range(5):
        enqueue(p, BuildingKind.POWER_PLANT)
    # 6th should fail
    assert enqueue(p, BuildingKind.POWER_PLANT) == QueueErrorReason.QUEUE_FULL


# ---------------------------------------------------------------------------
# Tick / construction
# ---------------------------------------------------------------------------
def test_tick_low_power_pauses_construction():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    enqueue(p, BuildingKind.POWER_PLANT)
    # Yard is the only structure → power is LOW → construction paused.
    for _ in range(60):
        tick_construction(tm, world.players, 0, dt=1.0)
    assert len(p.constructing) == 0, "power-low should prevent any construction site from being placed"
    assert len(p.queue) == 1, "queue should be preserved while power is low"


def test_tick_completes_building_after_build_time():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    # Add a SECOND power plant to keep net positive, so construction proceeds.
    place_building(tm, world.players, 0, BuildingKind.POWER_PLANT, 8, 5)
    enqueue(p, BuildingKind.POWER_PLANT)
    target = BUILDING_STATS[BuildingKind.POWER_PLANT]
    # Tick one frame at a time so we observe the scaffold → completion transitions
    completed = False
    for _ in range(int(target.build_time) + 5):
        result = tick_construction(tm, world.players, 0, dt=1.0)
        if result is not None:
            completed = True
            break
    assert completed
    # queue drained
    assert len(p.queue) == 0
    # power plant now exists alongside the one we placed directly
    pp_count = sum(1 for b in p.buildings if b.kind == BuildingKind.POWER_PLANT)
    assert pp_count == 2


def test_tick_no_op_when_queue_empty():
    tm = generate_default_map(64, 64, seed=1)
    world = World.new_default(64, 64, 1024, 768, seed=1)
    # Add a power plant so power is OK; no orders queued.
    place_building(tm, world.players, 0, BuildingKind.POWER_PLANT, 8, 5)
    before = len(world.get_player(0).buildings)
    for _ in range(5):
        tick_construction(tm, world.players, 0, dt=1.0)
    assert len(world.get_player(0).buildings) == before


# ---------------------------------------------------------------------------
# World default state
# ---------------------------------------------------------------------------
def test_world_default_has_player_yard():
    w = World.new_default(64, 64, 1024, 768, seed=1)
    p = w.get_player(0)
    yards = [b for b in p.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD]
    assert len(yards) == 1
    assert (yards[0].col, yards[0].row) == (5, 5)


def test_world_credits_after_yard_construction():
    w = World.new_default(64, 64, 1024, 768, seed=1)
    p = w.get_player(0)
    # 5000 starting - 2000 yard cost = 3000
    assert p.credits == 3000
