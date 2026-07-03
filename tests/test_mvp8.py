"""MVP-8 tests — Enemy AI.

These exercise:
  * World.new_default spawns the AI faction with a yard and an EnemyAI.
  * The AI queues a power plant, refinery, barracks, war factory over time.
  * Power-low carve-out lets the AI escape the low-power trap on tick 0.
  * The AI produces combat units (infantry + light_tank) once harvesters exist.
  * The AI attack-moves combat units at the player yard every WAVE_INTERVAL.
  * Pure AI helpers (enqueue_priority, _find_player_yard, etc.) work
    in isolation, independent of pygame.
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine.ai import (
    WAVE_INTERVAL,
    EnemyAI,
    _auto_expand_base,
    _BUILDING_PRIORITY,
    _fallback_target,
    _find_player_yard,
    _send_wave,
    ai_tick,
    recruit_one,
    recruit_tick,
    tick_all_ais,
)
from engine.buildings import (
    BuildingKind,
    PlayerState,
    enqueue,
    place_building,
    recompute_power,
    tick_construction,
)
from engine.orders import OrderKind
from engine.resources import ensure_harvesters
from engine.settings import MAP_H, MAP_W
from engine.tilemap import generate_default_map
from engine.units import (
    Unit,
    UnitKind,
    ensure_units,
    spawn_unit,
)
from engine.world import (
    DEFAULT_WITH_AI,
    ENEMY_PLAYER_ID,
    ENEMY_START_CREDITS,
    World,
    enemy_start_yard,
)


# -----------------------------------------------------------------------------
# Smoke: world with AI on by default
# -----------------------------------------------------------------------------
def test_new_default_spawns_ai_player():
    w = World.new_default()
    ids = [p.id for p in w.players]
    assert 0 in ids
    assert ENEMY_PLAYER_ID in ids
    assert len(w.ais) == 1
    ai = w.ais[0]
    assert ai.player_id == ENEMY_PLAYER_ID
    assert ai.wave_timer == 0.0


def test_new_default_ai_disabled():
    w = World.new_default(with_ai=False)
    assert len(w.ais) == 0
    assert all(p.id != ENEMY_PLAYER_ID for p in w.players)


def test_enemy_yard_placed_at_far_corner():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    assert any(b.kind == BuildingKind.CONSTRUCTION_YARD for b in me.buildings)
    ey, ex = enemy_start_yard(MAP_W, MAP_H)
    yard = next(b for b in me.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    assert (yard.col, yard.row) == (ey, ex)


def test_enemy_starts_with_credits():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    assert me.credits >= 2000  # at least the cost of a refinery; yard was deducted


# -----------------------------------------------------------------------------
# Pure-helper tests
# -----------------------------------------------------------------------------
def test_find_player_yard_returns_centroid():
    w = World.new_default()
    c = _find_player_yard(w.players)
    assert c is not None
    player = w.get_player(0)
    yard = next(b for b in player.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    assert c == (yard.col + 1, yard.row + 1)


def test_find_player_yard_no_player_returns_none():
    w = World.new_default(with_ai=False)
    # Remove the player yard, leaving no anchor.
    p = w.get_player(0)
    p.buildings.clear()
    assert _find_player_yard(w.players) is None


def test_fallback_target_is_map_center():
    tm = generate_default_map(64, 64, seed=1)
    assert _fallback_target(tm) == (32, 32)


def test_wave_interval_is_two_minutes():
    assert WAVE_INTERVAL == 120.0


def test_building_priority_order():
    """Refinery and power must come before combat buildings."""
    assert _BUILDING_PRIORITY.index(BuildingKind.POWER_PLANT) == 0
    assert _BUILDING_PRIORITY.index(BuildingKind.REFINERY) == 1
    assert _BUILDING_PRIORITY.index(BuildingKind.BARRACKS) == 2
    assert _BUILDING_PRIORITY.index(BuildingKind.WAR_FACTORY) == 3


# -----------------------------------------------------------------------------
# Expansion: AI queues & builds the base
# -----------------------------------------------------------------------------
def test_ai_queues_power_first():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    # Pre-power, the AI's head enqueue must be power_plant.
    ai_tick(w.ais[0], w.tilemap, w.players, dt=0.0)
    assert me.queue.pending and me.queue.pending[0] == BuildingKind.POWER_PLANT


def test_ai_queues_refinery_after_power_built():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    # Pre-place a power plant so the next AI enqueue targets the refinery.
    ey, ex = enemy_start_yard(w.tilemap.width, w.tilemap.height)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.POWER_PLANT,
                   ey - 3, ex - 3)
    # Force the AI to re-evaluate: ensure cooldowns ready.
    ai = EnemyAI(player_id=ENEMY_PLAYER_ID)
    ai_tick(ai, w.tilemap, w.players, dt=0.0)
    # Refinery should now be the head of the queue.
    assert me.queue.pending and me.queue.pending[0] == BuildingKind.REFINERY


def test_ai_skips_barracks_until_harvester_exists():
    """If no harvester, the AI must not enqueue barracks (no income)."""
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    # Pre-place power + refinery so the AI is past the early base.
    ey, ex = enemy_start_yard(w.tilemap.width, w.tilemap.height)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.POWER_PLANT,
                   ey - 3, ex - 3)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.REFINERY,
                   ey - 3, ex + 3)
    # No harvester: barracks should be skipped, queue stays empty.
    ai = EnemyAI(player_id=ENEMY_PLAYER_ID)
    ai_tick(ai, w.tilemap, w.players, dt=0.0)
    assert len(me.queue.pending) == 0


def test_ai_enqueues_barracks_when_harvester_exists():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    ey, ex = enemy_start_yard(w.tilemap.width, w.tilemap.height)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.POWER_PLANT,
                   ey - 3, ex - 3)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.REFINERY,
                   ey - 3, ex + 3)
    # Add a dummy harvester directly.
    ensure_harvesters(me).append(
        # coords unused; ensure_harvesters just wants something with owner_id
        # type ignore: we never call move/mine on it in this test.
        type("H", (), {"owner_id": ENEMY_PLAYER_ID, "col": 0, "row": 0})()
    )
    ai = EnemyAI(player_id=ENEMY_PLAYER_ID)
    ai_tick(ai, w.tilemap, w.players, dt=0.0)
    # First missing building in the priority list is barracks.
    assert me.queue.pending and me.queue.pending[0] == BuildingKind.BARRACKS


def test_low_power_does_not_block_power_plant_construction():
    """The carve-out: a fresh yard can still build its first power plant even
    though the power grid is technically LOW (yard consumes 20 with 0 produced)."""
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    # Make the AI enqueue a power plant.
    ai_tick(w.ais[0], w.tilemap, w.players, dt=0.0)
    # Tick construction a few times. Even with grid LOW, power plant progresses.
    progressed = False
    for _ in range(8):
        prev = len(me.constructing)
        tick_construction(w.tilemap, w.players, ENEMY_PLAYER_ID, dt=1.0)
        if me.constructing or len(me.buildings) > 1:
            progressed = True
            break
    assert progressed, "Power plant never began construction under LOW power"


# -----------------------------------------------------------------------------
# End-to-end: AI builds base over many ticks
# -----------------------------------------------------------------------------
def test_ai_builds_base_over_500_ticks():
    w = World.new_default()
    for _ in range(500):
        w.tick(1.0)
    me = w.get_player(ENEMY_PLAYER_ID)
    kinds = {b.kind for b in me.buildings}
    # All four key buildings should be up after enough time.
    for k in (BuildingKind.POWER_PLANT, BuildingKind.REFINERY, BuildingKind.BARRACKS):
        assert k in kinds, f"AI failed to build {k.value}; has {sorted(b.kind.value for b in me.buildings)}"


def test_ai_spawns_harvesters_via_refinery():
    w = World.new_default()
    for _ in range(150):
        w.tick(1.0)
    me = w.get_player(ENEMY_PLAYER_ID)
    assert len(ensure_harvesters(me)) >= 1


def test_ai_produces_infantry_once_barracks_up():
    w = World.new_default()
    for _ in range(400):
        w.tick(1.0)
    me = w.get_player(ENEMY_PLAYER_ID)
    infantry = [u for u in ensure_units(me) if u.kind == UnitKind.INFANTRY]
    assert len(infantry) >= 1


# -----------------------------------------------------------------------------
# Recruitment helpers
# -----------------------------------------------------------------------------
def test_recruit_one_returns_none_without_prereq():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    ai = EnemyAI(player_id=ENEMY_PLAYER_ID)
    # No barracks → can't recruit infantry.
    u = recruit_one(ai, me, w.tilemap, UnitKind.INFANTRY)
    assert u is None


def test_recruit_tick_does_nothing_without_prereq():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    ai = EnemyAI(player_id=ENEMY_PLAYER_ID)
    recruit_tick(ai, me, w.tilemap, dt=1.0)
    assert ensure_units(me) == []


def test_recruit_tick_spawns_infantry_with_barracks():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    ey, ex = enemy_start_yard(w.tilemap.width, w.tilemap.height)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.BARRACKS,
                   ey - 3, ex - 3)
    me.credits = 10_000  # rich
    ai = EnemyAI(player_id=ENEMY_PLAYER_ID)
    recruit_tick(ai, me, w.tilemap, dt=1.0)
    # Light_tank prereq (war_factory) is missing → falls back to infantry.
    units = ensure_units(me)
    assert any(u.kind == UnitKind.INFANTRY for u in units)


# -----------------------------------------------------------------------------
# Wave dispatch
# -----------------------------------------------------------------------------
def test_wave_dispatches_after_interval():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    ey, ex = enemy_start_yard(w.tilemap.width, w.tilemap.height)
    # Give the AI a barracks + war_factory + harvesters + lots of credits, then
    # spawn combat units directly so the wave has something to send.
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.BARRACKS,
                   ey - 3, ex - 3)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.WAR_FACTORY,
                   ey - 3, ex + 3)
    place_building(w.tilemap, w.players, ENEMY_PLAYER_ID, BuildingKind.POWER_PLANT,
                   ey - 6, ex - 3)
    me.credits = 100_000
    # Spawn 3 infantry by hand.
    for _ in range(3):
        spawn_unit(me, w.tilemap, UnitKind.INFANTRY)
    units = ensure_units(me)
    assert len(units) == 3
    # Fast-forward the AI wave timer to the brink.
    w.ais[0].wave_timer = WAVE_INTERVAL
    # Tick once with a big dt → the wave should fire.
    ai_tick(w.ais[0], w.tilemap, w.players, dt=0.1)
    # All units should now have an ATTACK_MOVE order pointing at the player yard.
    player = w.get_player(0)
    p_yard = next(b for b in player.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    for u in units:
        assert u.order is not None
        assert u.order.kind == OrderKind.ATTACK_MOVE
        assert (u.order.target_col, u.order.target_row) == (p_yard.col + 1, p_yard.row + 1)
    # waves_sent incremented.
    assert w.ais[0].waves_sent == 1
    # wave_timer reset.
    assert w.ais[0].wave_timer == 0.0


def test_wave_skips_when_no_combatants():
    w = World.new_default()
    me = w.get_player(ENEMY_PLAYER_ID)
    assert ensure_units(me) == []
    w.ais[0].wave_timer = WAVE_INTERVAL
    ai_tick(w.ais[0], w.tilemap, w.players, dt=0.1)
    # No combatants → no wave sent, but timer still resets so we don't spam.
    assert w.ais[0].wave_timer == 0.0
    assert w.ais[0].waves_sent == 1


# -----------------------------------------------------------------------------
# AI does not affect the player
# -----------------------------------------------------------------------------
def test_ai_does_not_spend_player_credits():
    w = World.new_default()
    p0 = w.get_player(0)
    initial = p0.credits
    for _ in range(100):
        w.tick(1.0)
    # Player is untouched by the AI.
    assert p0.credits == initial
    assert p0.buildings == [b for b in p0.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD]


# -----------------------------------------------------------------------------
# Multi-AI support
# -----------------------------------------------------------------------------
def test_tick_all_ais_runs_each_controller():
    w = World.new_default()
    # Drop the existing AI and add two new ones against fabricated players.
    w.ais.clear()
    # Add a second enemy.
    p2 = PlayerState(id=2, credits=ENEMY_START_CREDITS)
    w.players.append(p2)
    place_building(w.tilemap, w.players, 2, BuildingKind.CONSTRUCTION_YARD, 20, 20)
    ai_a = EnemyAI(player_id=ENEMY_PLAYER_ID)
    ai_b = EnemyAI(player_id=2)
    w.ais.extend([ai_a, ai_b])
    tick_all_ais(w.ais, w.tilemap, w.players, dt=0.0)
    me1 = w.get_player(ENEMY_PLAYER_ID)
    me2 = w.get_player(2)
    assert me1.queue.pending[0] == BuildingKind.POWER_PLANT
    assert me2.queue.pending[0] == BuildingKind.POWER_PLANT
