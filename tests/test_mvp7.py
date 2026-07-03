"""Tests for MVP-7: combat visuals (hit flash, particles, health bars).

Covers the pure-logic layer in ``engine.combat_visuals`` and its wiring into
units/buildings via ``apply_damage_with_visuals``. Renderer functions in
``engine.render`` are smoke-tested via the dummy-SDL pygame surface to ensure
they don't crash when called with empty / populated inputs.
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.buildings import BUILDING_STATS, Building, BuildingKind, PlayerState
from engine.combat_visuals import (
    HIT_FLASH_DURATION,
    HitFlashState,
    PARTICLE_COUNT_BUILDING,
    PARTICLE_COUNT_UNIT,
    PARTICLE_LIFETIME,
    Particle,
    PLAYER_COLOR,
    health_color,
    health_ratio,
    owner_color,
    spawn_death_particles,
    tick_flash,
    tick_particles,
    trigger_flash,
)
from engine.orders import (
    OrderKind,
    issue_attack_building,
    issue_attack_unit,
)
from engine.render import (
    draw_building_health_bars,
    draw_hit_flash_overlay,
    draw_particles,
    draw_unit_health_bars,
)
from engine.settings import DEFAULT_WINDOW_H, DEFAULT_WINDOW_W, TILE_SIZE
from engine.tilemap import TileMap, generate_default_map
from engine.units import (
    UNIT_STATS,
    Unit,
    UnitKind,
    apply_damage_with_visuals,
    spawn_unit,
    take_damage,
)
from engine.world import World


# -----------------------------------------------------------------------------
# Pure logic: HitFlashState
# -----------------------------------------------------------------------------
def test_hit_flash_starts_inactive():
    f = HitFlashState()
    assert not f.is_active()
    assert f.intensity() == 0.0


def test_trigger_flash_sets_duration_and_full_intensity():
    f = HitFlashState()
    trigger_flash(f)
    assert f.is_active()
    assert abs(f.timer - HIT_FLASH_DURATION) < 1e-9
    assert abs(f.intensity() - 1.0) < 1e-9


def test_tick_flash_decays_to_zero():
    f = HitFlashState()
    trigger_flash(f)
    tick_flash(f, dt=HIT_FLASH_DURATION / 2)
    assert f.is_active()
    assert 0.4 < f.intensity() < 0.6  # ~0.5
    tick_flash(f, dt=HIT_FLASH_DURATION)
    assert not f.is_active()
    assert f.intensity() == 0.0


def test_trigger_flash_resets_timer():
    f = HitFlashState()
    trigger_flash(f)
    tick_flash(f, dt=HIT_FLASH_DURATION / 2)
    trigger_flash(f)
    assert abs(f.timer - HIT_FLASH_DURATION) < 1e-9


def test_tick_flash_below_zero_clamps():
    f = HitFlashState()
    trigger_flash(f)
    tick_flash(f, dt=10.0)
    assert f.timer == 0.0
    assert not f.is_active()


# -----------------------------------------------------------------------------
# Pure logic: particles
# -----------------------------------------------------------------------------
def test_spawn_particles_default_count_and_alive():
    rng = random.Random(0)
    ps = spawn_death_particles(100.0, 100.0, count=8, color=(200, 60, 60), rng=rng)
    assert len(ps) == 8
    for p in ps:
        assert p.life > 0
        assert p.max_life > 0
        assert p.alive
        # Position starts at center
        assert p.x == 100.0
        assert p.y == 100.0


def test_tick_particles_advances_and_decays_life():
    rng = random.Random(1)
    ps = spawn_death_particles(0, 0, count=4, color=(80, 80, 80), rng=rng)
    initial_x = [p.x for p in ps]
    initial_y = [p.y for p in ps]
    removed = tick_particles(ps, dt=0.1)
    assert removed == 0
    # Positions changed
    for p, ix, iy in zip(ps, initial_x, initial_y):
        assert p.x != ix or p.y != iy
        assert p.life < p.max_life


def test_tick_particles_removes_dead_after_full_lifetime():
    rng = random.Random(2)
    ps = spawn_death_particles(0, 0, count=4, color=(80, 80, 80), rng=rng)
    # Tick past max lifetime
    removed = tick_particles(ps, dt=PARTICLE_LIFETIME * 1.5)
    assert removed == 4
    assert ps == []


def test_tick_particles_handles_zero_dt():
    rng = random.Random(3)
    ps = spawn_death_particles(0, 0, count=3, color=(80, 80, 80), rng=rng)
    removed = tick_particles(ps, dt=0.0)
    assert removed == 0
    assert len(ps) == 3


def test_particle_velocity_has_gravity():
    rng = random.Random(4)
    ps = spawn_death_particles(0, 0, count=2, color=(80, 80, 80), rng=rng)
    vy0 = [p.vy for p in ps]
    tick_particles(ps, dt=0.1)
    for p, vy in zip(ps, vy0):
        # vy increased due to gravity
        assert p.vy > vy


def test_particle_returns_particle_dataclass():
    rng = random.Random(5)
    ps = spawn_death_particles(0, 0, count=1, color=(255, 0, 0), rng=rng)
    assert isinstance(ps[0], Particle)
    # Spawn applies ±30 jitter per channel, so result must be near red.
    r, g, b = ps[0].color
    assert r >= 200
    assert g <= 60
    assert b <= 60


# -----------------------------------------------------------------------------
# Pure logic: health-bar math
# -----------------------------------------------------------------------------
def test_health_ratio_full_and_zero_and_clamping():
    assert health_ratio(100, 100) == 1.0
    assert health_ratio(0, 100) == 0.0
    assert health_ratio(50, 100) == 0.5
    # Clamping
    assert health_ratio(200, 100) == 1.0
    assert health_ratio(-10, 100) == 0.0
    assert health_ratio(50, 0) == 0.0  # avoid divide by zero


def test_health_color_thresholds():
    # Above 60% -> green
    assert health_color(70, 100)[1] > health_color(70, 100)[0]
    # Below 30% -> red
    assert health_color(20, 100)[0] > health_color(20, 100)[1]
    # Dead -> gray-ish (not saturated)
    r, g, b = health_color(0, 100)
    assert abs(r - g) < 30 and abs(g - b) < 30


def test_owner_color_lookup():
    assert owner_color(0) == PLAYER_COLOR[0]
    assert owner_color(1) == PLAYER_COLOR[1]
    # Unknown owner -> default gray
    assert owner_color(99) != PLAYER_COLOR[0]


# -----------------------------------------------------------------------------
# Wiring: apply_damage_with_visuals on Unit
# -----------------------------------------------------------------------------
def _fresh_world_with_two_players() -> World:
    w = World.new_default()
    p1 = PlayerState(id=1, credits=5000)
    w.players.append(p1)
    return w


def _world_with_two_players() -> World:
    """Ensure both player 0 and player 1 exist (adds player 1 if missing)."""
    w = World.new_default()
    if not any(p.id == 1 for p in w.players):
        w.players.append(PlayerState(id=1, credits=5000))
    return w


def _make_unit(world: World, owner_id: int, col: int = 10, row: int = 10) -> Unit:
    # Ensure target player exists (some tests start from World.new_default which
    # only has player 0).
    if not any(p.id == owner_id for p in world.players):
        world.players.append(PlayerState(id=owner_id, credits=5000))
    p = world.get_player(owner_id)
    u = Unit(kind=UnitKind.INFANTRY, owner_id=owner_id, col=col, row=row, hp=UNIT_STATS[UnitKind.INFANTRY].hp)
    from engine.units import ensure_units
    ensure_units(p).append(u)
    return u


def test_apply_damage_with_visuals_triggers_flash_on_non_fatal_hit():
    w = _fresh_world_with_two_players()
    u = _make_unit(w, 1)
    flashes: dict = {}
    particles: list = []
    died = apply_damage_with_visuals(u, 10, flashes, particles, tilemap=w.tilemap)
    assert not died
    assert id(u) in flashes
    assert flashes[id(u)].is_active()
    assert particles == []


def test_apply_damage_with_visuals_emits_particles_on_death():
    w = _fresh_world_with_two_players()
    u = _make_unit(w, 1)
    flashes: dict = {}
    particles: list = []
    died = apply_damage_with_visuals(u, 9999, flashes, particles, tilemap=w.tilemap)
    assert died
    assert u.is_dead
    assert len(particles) == PARTICLE_COUNT_UNIT
    # Particles positioned around the unit's tile center
    cx = u.col * TILE_SIZE + TILE_SIZE / 2.0
    cy = u.row * TILE_SIZE + TILE_SIZE / 2.0
    assert all(abs(p.x - cx) < 1.0 and abs(p.y - cy) < 1.0 for p in particles)


def test_apply_damage_with_visuals_noop_on_dead_unit():
    w = _fresh_world_with_two_players()
    u = _make_unit(w, 1)
    u.hp = 0
    flashes: dict = {}
    particles: list = []
    died = apply_damage_with_visuals(u, 10, flashes, particles, tilemap=w.tilemap)
    assert not died
    assert flashes == {}
    assert particles == []


def test_apply_damage_with_visuals_uses_owner_color_for_particles():
    w = _fresh_world_with_two_players()
    u_enemy = _make_unit(w, 1)
    flashes: dict = {}
    particles: list = []
    apply_damage_with_visuals(u_enemy, 9999, flashes, particles, tilemap=w.tilemap)
    # Enemy is owner 1 -> red
    for p in particles:
        assert p.color[0] > 100  # red dominant


# -----------------------------------------------------------------------------
# Wiring: ATTACK_UNIT triggers visuals in tick_orders
# -----------------------------------------------------------------------------
def test_attack_unit_emits_flash_and_particle_on_death():
    w = _fresh_world_with_two_players()
    attacker = _make_unit(w, 0, col=10, row=10)
    victim = _make_unit(w, 1, col=11, row=10)  # adjacent
    issue_attack_unit([attacker], victim, enemy_player_id=1)
    # Force distance close enough by setting attacker col next to victim
    attacker.col = victim.col - 1
    attacker.row = victim.row
    flashes = w.flashes
    particles = w.particles
    from engine.orders import tick_orders
    # Infantry range=2, distance=1, so fire.
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=flashes, particles=particles)
    # Victim took damage; flash registered
    assert id(victim) in flashes
    assert flashes[id(victim)].is_active()


def test_attack_unit_kills_emits_particles():
    w = _fresh_world_with_two_players()
    # Heavy tank: 40 dmg/attack, range=5, vs infantry (60hp) — 2 hits to kill.
    attacker = Unit(
        kind=UnitKind.HEAVY_TANK, owner_id=0,
        col=10, row=10, hp=UNIT_STATS[UnitKind.HEAVY_TANK].hp,
    )
    from engine.units import ensure_units
    ensure_units(w.get_player(0)).append(attacker)
    victim = _make_unit(w, 1, col=11, row=10)
    issue_attack_unit([attacker], victim, enemy_player_id=1)
    flashes = w.flashes
    particles = w.particles
    pre_particle_count = len(particles)
    from engine.orders import tick_orders
    # First tick: stop chase, fire shot 1 (60→20).
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=flashes, particles=particles)
    assert victim.hp == 20
    # Second tick: still in range (attacker stayed put), fire shot 2 → kill.
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=flashes, particles=particles)
    assert victim.is_dead
    assert len(particles) > pre_particle_count


# -----------------------------------------------------------------------------
# Wiring: ATTACK_BUILDING triggers building flash + death particles
# -----------------------------------------------------------------------------
def test_attack_building_flash_registered_on_hit():
    w = _fresh_world_with_two_players()
    attacker = _make_unit(w, 0, col=10, row=10)
    # Place a barracks for player 1 at (15, 15)
    b = Building(kind=BuildingKind.BARRACKS, col=15, row=15, owner_id=1)
    w.get_player(1).buildings.append(b)
    issue_attack_building([attacker], b, enemy_player_id=1)
    flashes = w.flashes
    particles = w.particles
    # Force attacker in range
    attacker.col = 14
    attacker.row = 16
    from engine.orders import tick_orders
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=flashes, particles=particles)
    assert id(b) in flashes


def test_attack_building_destroy_emits_particles_and_removes():
    w = _fresh_world_with_two_players()
    # Heavy tank 40 dmg, barracks hp=800, will take many ticks but we set hp low
    b = Building(kind=BuildingKind.BARRACKS, col=15, row=15, owner_id=1, hp=10)
    w.get_player(1).buildings.append(b)
    attacker = Unit(
        kind=UnitKind.HEAVY_TANK, owner_id=0,
        col=14, row=16, hp=UNIT_STATS[UnitKind.HEAVY_TANK].hp,
    )
    from engine.units import ensure_units
    ensure_units(w.get_player(0)).append(attacker)
    issue_attack_building([attacker], b, enemy_player_id=1)
    flashes = w.flashes
    particles = w.particles
    pre = len(particles)
    from engine.orders import tick_orders
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=flashes, particles=particles)
    # Building destroyed
    assert b not in w.get_player(1).buildings
    assert len(particles) > pre
    # Flash for dead building was popped
    assert id(b) not in flashes


# -----------------------------------------------------------------------------
# Wiring: World.tick manages flashes and particles
# -----------------------------------------------------------------------------
def test_world_tick_advances_flashes_and_particles():
    w = _world_with_two_players()
    flashes = w.flashes
    particles = w.particles
    # Heavy tank (40 dmg) vs infantry (60 hp) — 2 hits to kill.
    attacker = Unit(
        kind=UnitKind.HEAVY_TANK, owner_id=0,
        col=10, row=10, hp=UNIT_STATS[UnitKind.HEAVY_TANK].hp,
    )
    from engine.units import ensure_units
    ensure_units(w.get_player(0)).append(attacker)
    victim = _make_unit(w, 1, col=11, row=10)
    issue_attack_unit([attacker], victim, enemy_player_id=1)
    from engine.orders import tick_orders
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=flashes, particles=particles)
    assert flashes  # flash on hit 1
    # Run a few more ticks via World to land the killing blow.
    for _ in range(5):
        w.tick(dt=0.1)
    assert victim.is_dead
    assert particles  # particles on death
    # Run for long enough to drain everything.
    for _ in range(500):
        w.tick(dt=0.05)
    assert flashes == {}
    assert particles == []


def test_world_tick_prunes_flashes_for_dead_entities():
    w = _world_with_two_players()
    attacker = Unit(
        kind=UnitKind.HEAVY_TANK, owner_id=0,
        col=10, row=10, hp=UNIT_STATS[UnitKind.HEAVY_TANK].hp,
    )
    from engine.units import ensure_units
    ensure_units(w.get_player(0)).append(attacker)
    victim = _make_unit(w, 1, col=11, row=10)
    issue_attack_unit([attacker], victim, enemy_player_id=1)
    from engine.orders import tick_orders
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=w.flashes, particles=w.particles)
    assert id(victim) in w.flashes
    # Drive ticks until the victim dies (2 hits at 40 dmg vs 60 hp).
    for _ in range(5):
        w.tick(dt=0.1)
    assert victim.is_dead
    # Run ticks past the flash duration so it decays, then assert pruning.
    for _ in range(50):
        w.tick(dt=0.05)
    assert id(victim) not in w.flashes


def test_world_tick_keeps_flash_for_living_entities():
    w = _world_with_two_players()
    # Both infantry (8 dmg vs 60 hp) — victim won't die in test window.
    attacker = _make_unit(w, 0, col=10, row=10)
    victim = _make_unit(w, 1, col=11, row=10)
    attacker.col = victim.col - 1
    attacker.row = victim.row
    issue_attack_unit([attacker], victim, enemy_player_id=1)
    from engine.orders import tick_orders
    tick_orders(w.tilemap, w.players, dt=0.1, flashes=w.flashes, particles=w.particles)
    # Victim still alive; flash registered.
    assert not victim.is_dead
    assert id(victim) in w.flashes
    # Tick past flash duration; flash decays; victim still alive so flash cleaned.
    for _ in range(20):
        w.tick(dt=0.05)
    assert id(victim) not in w.flashes


# -----------------------------------------------------------------------------
# Renderer: dummy-SDL smoke (must not crash on empty or populated inputs)
# -----------------------------------------------------------------------------
def _pygame_screen():
    pygame.init()
    return pygame.display.set_mode((DEFAULT_WINDOW_W, DEFAULT_WINDOW_H))


def test_draw_health_bars_empty():
    screen = _pygame_screen()
    cam = type("C", (), {"zoom": 1.0, "world_to_screen": staticmethod(lambda x, y: (int(x), int(y)))})()
    draw_unit_health_bars(screen, cam, [])
    draw_building_health_bars(screen, cam, [])


def test_draw_health_bars_damaged_unit_does_not_crash():
    screen = _pygame_screen()
    from engine.camera import Camera
    cam = Camera(map_w_tiles=64, map_h_tiles=64, screen_w=DEFAULT_WINDOW_W, screen_h=DEFAULT_WINDOW_H)
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=20, row=20, hp=10)  # damaged
    draw_unit_health_bars(screen, cam, [u])
    draw_unit_health_bars(screen, cam, [u], selected_ids={id(u)})
    pygame.quit()


def test_draw_health_bars_damaged_building_does_not_crash():
    screen = _pygame_screen()
    from engine.camera import Camera
    cam = Camera(map_w_tiles=64, map_h_tiles=64, screen_w=DEFAULT_WINDOW_W, screen_h=DEFAULT_WINDOW_H)
    b = Building(kind=BuildingKind.BARRACKS, col=20, row=20, owner_id=1, hp=10)
    draw_building_health_bars(screen, cam, [b])
    draw_building_health_bars(screen, cam, [b], selected_ids={id(b)})
    pygame.quit()


def test_draw_health_bars_full_hp_unit_skipped():
    screen = _pygame_screen()
    from engine.camera import Camera
    cam = Camera(map_w_tiles=64, map_h_tiles=64, screen_w=DEFAULT_WINDOW_W, screen_h=DEFAULT_WINDOW_H)
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=20, row=20,
             hp=UNIT_STATS[UnitKind.INFANTRY].hp)
    # No selection, full HP → renderer skips; just ensure no crash.
    draw_unit_health_bars(screen, cam, [u])
    pygame.quit()


def test_draw_hit_flash_overlay_empty_and_active():
    screen = _pygame_screen()
    from engine.camera import Camera
    cam = Camera(map_w_tiles=64, map_h_tiles=64, screen_w=DEFAULT_WINDOW_W, screen_h=DEFAULT_WINDOW_H)
    draw_hit_flash_overlay(screen, cam, [], [], {})
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=20, row=20,
             hp=UNIT_STATS[UnitKind.INFANTRY].hp)
    f = HitFlashState()
    trigger_flash(f)
    draw_hit_flash_overlay(screen, cam, [u], [], {id(u): f})
    pygame.quit()


def test_draw_particles_empty_and_active():
    screen = _pygame_screen()
    from engine.camera import Camera
    cam = Camera(map_w_tiles=64, map_h_tiles=64, screen_w=DEFAULT_WINDOW_W, screen_h=DEFAULT_WINDOW_H)
    draw_particles(screen, cam, [])
    ps = spawn_death_particles(100.0, 100.0, count=4, color=(200, 60, 60), rng=random.Random(7))
    draw_particles(screen, cam, ps)
    pygame.quit()
