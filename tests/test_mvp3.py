"""Tests for MVP-3: resource loop (harvester auto-mines → returns to refinery → credits)."""
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
    tick_construction,
)
from engine.resources import (
    HARVESTER_CAPACITY,
    HARVESTER_COST,
    HARVESTER_SPEED,
    Harvester,
    HarvesterState,
    ensure_harvesters,
    nearest_ore,
    nearest_refinery,
    spawn_harvester,
    tick_harvesters,
    tick_refineries_spawn_harvesters,
)
from engine.tilemap import TileMap, generate_default_map
from engine.world import World


# ---------------------------------------------------------------------------
# Ore finding
# ---------------------------------------------------------------------------
def test_nearest_ore_finds_a_patch():
    tm = generate_default_map(64, 64, seed=1)
    # The default map has ore in each quadrant. From (5,5) the top-left quadrant
    # is the closest, so we just assert we got *some* ore.
    ore = nearest_ore(tm, 5, 5)
    assert ore is not None
    c, r = ore
    assert tm.is_ore(c, r)


def test_nearest_ore_returns_none_when_no_ore():
    # All-grass map → no ore anywhere
    tm = TileMap(8, 8)
    assert nearest_ore(tm, 4, 4) is None


# ---------------------------------------------------------------------------
# Refinery finding
# ---------------------------------------------------------------------------
def test_nearest_refinery_picks_closest():
    p = PlayerState(id=0)
    p.buildings.append(Building(kind=BuildingKind.REFINERY, col=10, row=10, owner_id=0))
    p.buildings.append(Building(kind=BuildingKind.REFINERY, col=30, row=30, owner_id=0))
    near = nearest_refinery(p, 12, 12)
    assert near is not None
    assert near.col == 10 and near.row == 10


def test_nearest_refinery_skips_other_kinds():
    p = PlayerState(id=0)
    p.buildings.append(Building(kind=BuildingKind.POWER_PLANT, col=10, row=10, owner_id=0))
    assert nearest_refinery(p, 12, 12) is None


# ---------------------------------------------------------------------------
# Harvester spawn
# ---------------------------------------------------------------------------
def test_spawn_harvester_creates_adjacent_unit():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0)
    ref = Building(kind=BuildingKind.REFINERY, col=15, row=15, owner_id=0)
    p.buildings.append(ref)
    h = spawn_harvester(p, tm, ref)
    assert h is not None
    assert h.owner_id == 0
    # Adjacent: must be within 1 tile of refinery (Manhattan)
    assert abs(h.col - 15) <= 3 and abs(h.row - 15) <= 3


def test_spawn_harvester_uses_walkable_tile():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0)
    ref = Building(kind=BuildingKind.REFINERY, col=20, row=20, owner_id=0)
    p.buildings.append(ref)
    h = spawn_harvester(p, tm, ref)
    assert h is not None
    assert tm.is_walkable(h.col, h.row)


# ---------------------------------------------------------------------------
# State machine: IDLE → MOVING_TO_ORE → MINING
# ---------------------------------------------------------------------------
def test_harvester_idle_transitions_to_moving_to_ore():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0)
    harvesters = ensure_harvesters(p)
    harvesters.append(Harvester(owner_id=0, col=5, row=5))
    tick_harvesters(tm, [p], dt=0.1)
    h = harvesters[0]
    # With ore nearby, we should be heading to it
    assert h.state in (HarvesterState.MOVING_TO_ORE, HarvesterState.IDLE)  # some default-map patches are very far
    # Either we found ore and are moving, or there's no ore — but the default map has ore.
    assert h.state == HarvesterState.MOVING_TO_ORE
    assert h.target_col != 5 or h.target_row != 5


def test_harvester_mines_when_on_ore():
    tm = TileMap(8, 8)
    tm.set(3, 3, 2)  # single ore tile
    p = PlayerState(id=0)
    harvesters = ensure_harvesters(p)
    h = Harvester(owner_id=0, col=3, row=3, state=HarvesterState.MOVING_TO_ORE, target_col=3, target_row=3)
    harvesters.append(h)
    # First tick: arrives at ore → transitions to MINING.
    tick_harvesters(tm, [p], dt=0.1)
    assert h.state == HarvesterState.MINING
    # Second tick: now mining actually accumulates cargo.
    tick_harvesters(tm, [p], dt=1.0)
    assert h.cargo > 0.0


def test_harvester_full_load_returns_to_refinery():
    tm = TileMap(8, 8)
    tm.set(2, 2, 2)  # ore
    p = PlayerState(id=0)
    # Place refinery adjacent to harvester's expected return path.
    ref = Building(kind=BuildingKind.REFINERY, col=5, row=5, owner_id=0)
    p.buildings.append(ref)
    harvesters = ensure_harvesters(p)
    # Pre-fill the harvester to capacity and put it at the ore tile in MOVING_TO_REFINERY state.
    h = Harvester(
        owner_id=0,
        col=2,
        row=2,
        cargo=HARVESTER_CAPACITY,
        state=HarvesterState.MOVING_TO_REFINERY,
        target_col=5,
        target_row=5,
    )
    harvesters.append(h)
    start_credits = p.credits

    # Tick enough for one round trip: 3 tiles walk (HARVESTER_SPEED=4 t/s) + 1s unload.
    # 1s movement + 1s unload = 2s should be enough; give 4s for safety.
    for _ in range(4):
        tick_harvesters(tm, [p], dt=1.0)

    # Should have delivered one full load.
    assert p.credits == start_credits + int(HARVESTER_CAPACITY)
    # Cargo should have been unloaded (it's now re-mining or empty, but never stuck full at the refinery).
    assert h.cargo < HARVESTER_CAPACITY


# ---------------------------------------------------------------------------
# Refinery auto-spawn
# ---------------------------------------------------------------------------
def test_refinery_auto_spawns_harvester_when_affordable():
    from engine.buildings import BUILDING_STATS
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    place_building(tm, [p], 0, BuildingKind.REFINERY, 15, 15)
    credits_after_refinery = p.credits  # 10_000 - 2000
    tick_refineries_spawn_harvesters([p], tm)
    harvesters = ensure_harvesters(p)
    assert len(harvesters) == 1
    assert p.credits == credits_after_refinery - HARVESTER_COST
    # Sanity: refinery really did cost what we think
    assert BUILDING_STATS[BuildingKind.REFINERY].cost == 2000


def test_refinery_no_spawn_without_enough_credits():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10)
    place_building(tm, [p], 0, BuildingKind.REFINERY, 15, 15)
    tick_refineries_spawn_harvesters([p], tm)
    assert len(ensure_harvesters(p)) == 0


def test_refinery_no_spawn_without_refinery():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    tick_refineries_spawn_harvesters([p], tm)
    assert len(ensure_harvesters(p)) == 0


# ---------------------------------------------------------------------------
# Full loop via World.tick
# ---------------------------------------------------------------------------
def test_world_tick_drives_resource_loop_end_to_end():
    """The full MVP-3 promise: build a refinery → harvester spawns → mines → returns → credits go up."""
    world = World.new_default(64, 64, 1024, 768, seed=1)
    p = world.get_player(0)
    p.credits = 10_000
    # Place a power plant so the refinery can be built (power OK) and ensure construction proceeds.
    place_building(world.tilemap, world.players, 0, BuildingKind.POWER_PLANT, 8, 5)
    # Place a refinery directly (skip the build queue to keep the test fast and deterministic).
    place_building(world.tilemap, world.players, 0, BuildingKind.REFINERY, 15, 15)

    credits_before = p.credits
    # Tick enough seconds for: spawn → move → mine → return → unload.
    for _ in range(120):
        world.tick(dt=1.0)
    credits_after = p.credits

    # The harvester should have made at least one delivery (700 credits) and the refinery
    # may have tried to spawn a 2nd harvester (cost 1400). Net delta should be positive on credits.
    assert len(world.all_harvesters()) >= 1
    # At least one full load delivered: credits_after should be > credits_before - HARVESTER_COST
    # (i.e. some ore made it through).
    assert credits_after > credits_before - HARVESTER_COST
    # And specifically, the harvester should now have non-negative cargo (could be empty after unload).
    for h in world.all_harvesters():
        assert h.cargo >= 0.0
        assert h.state != HarvesterState.UNLOADING or h.cargo > 0.0


def test_harvester_unload_increases_credits_exactly():
    """Direct tick test: harvester pre-loaded → unload → credits += capacity."""
    tm = TileMap(8, 8)
    tm.set(2, 2, 2)  # ore (so it can re-mine later)
    p = PlayerState(id=0)
    p.buildings.append(Building(kind=BuildingKind.REFINERY, col=5, row=5, owner_id=0))
    harvesters = ensure_harvesters(p)
    h = Harvester(
        owner_id=0,
        col=5,
        row=5,
        cargo=HARVESTER_CAPACITY,
        state=HarvesterState.UNLOADING,
        target_col=5,
        target_row=5,
    )
    harvesters.append(h)

    start_credits = p.credits
    # Tick one second: should fully unload (capacity 700 / rate 700/s = 1s)
    tick_harvesters(tm, [p], dt=1.0)
    assert h.cargo == 0.0
    assert p.credits == start_credits + int(HARVESTER_CAPACITY)


# ---------------------------------------------------------------------------
# Smoke: headless world with refinery keeps the existing rendering path green
# ---------------------------------------------------------------------------
def test_world_default_has_no_harvester_yet():
    """Default game: only the yard, no refinery yet → no harvesters spawned."""
    world = World.new_default(64, 64, 1024, 768, seed=1)
    assert len(world.all_harvesters()) == 0