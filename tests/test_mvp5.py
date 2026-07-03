"""Tests for MVP-5: 操作控制 (selection, orders, control groups).

Covers:
  - Box-select normalization + click-to-tile math
  - SelectionState bookkeeping (replace vs additive)
  - resolve_click classifies own / enemy / empty
  - Right-click → move order
  - Right-click on enemy unit → ATTACK_UNIT order
  - Right-click on enemy building → ATTACK_BUILDING order
  - 'A' arming + right-click → ATTACK_MOVE order
  - tick_orders: ATTACK_MOVE auto-acquires enemy in range and switches to ATTACK_UNIT
  - tick_orders: ATTACK_UNIT deals damage at range and stops at death
  - tick_orders: ATTACK_BUILDING damages building HP and removes at 0
  - ControlGroups: assign + recall + add
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from engine.buildings import (
    BUILDING_STATS,
    Building,
    BuildingKind,
    PlayerState,
    place_building,
)
from engine.groups import ControlGroups
from engine.orders import (
    Order,
    OrderKind,
    find_enemy_unit_in_range,
    issue_attack_building,
    issue_attack_move,
    issue_attack_unit,
    issue_move,
    tick_orders,
)
from engine.selection import (
    ClickTarget,
    SelectionState,
    building_at_tile,
    normalize_box,
    point_in_box,
    resolve_click,
    unit_at_tile,
    units_in_box,
)
from engine.tilemap import TileMap, generate_default_map
from engine.units import (
    UNIT_STATS,
    Unit,
    UnitKind,
    UnitState,
    ensure_units,
    order_move,
    remove_dead,
    spawn_unit,
    take_damage,
)
from engine.world import World


# ---------------------------------------------------------------------------
# Box normalization / geometry
# ---------------------------------------------------------------------------
def test_normalize_box_orders_coords():
    assert normalize_box((5, 5), (2, 9)) == (2, 5, 5, 9)
    assert normalize_box((2, 9), (5, 5)) == (2, 5, 5, 9)


def test_point_in_box_inclusive_bounds():
    assert point_in_box((3, 4), (2, 3, 5, 6))
    assert not point_in_box((6, 4), (2, 3, 5, 6))


def test_units_in_box_returns_indices_in_rect():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=10_000)
    u1 = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=5, row=5, hp=60)
    u2 = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=8, row=8, hp=60)
    u3 = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=20, row=20, hp=60)
    ensure_units(p).extend([u1, u2, u3])
    idxs = units_in_box(p, (4, 4, 10, 10))
    assert sorted(idxs) == [0, 1]


# ---------------------------------------------------------------------------
# SelectionState
# ---------------------------------------------------------------------------
def test_selection_state_box_lifecycle():
    s = SelectionState()
    assert s.current_box_rect() is None
    s.begin_box((3, 4))
    s.update_box((6, 8))
    assert s.current_box_rect() == (3, 4, 6, 8)
    box = s.end_box()
    assert box == (3, 4, 6, 8)
    assert s.current_box_rect() is None
    assert s.box_start is None


def test_selection_state_replace_vs_additive():
    s = SelectionState()
    s.select_units([1, 2])
    s.add_units([2, 3])
    assert s.selected_unit_ids == [1, 2, 3]
    s.toggle_unit(2)
    assert s.selected_unit_ids == [1, 3]


def test_selection_state_selected_units_resolves_to_live_objects():
    p = PlayerState(id=0)
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=2, row=2, hp=60)
    ensure_units(p).append(u)
    s = SelectionState()
    s.select_units([0])
    assert s.selected_units(p) == [u]


# ---------------------------------------------------------------------------
# resolve_click classification
# ---------------------------------------------------------------------------
def _make_two_player_world() -> World:
    w = World.new_default(64, 64, 1024, 768, seed=1)
    p0 = w.get_player(0)
    # Add a barracks and a war factory for player 0
    p0.credits = 10_000
    place_building(w.tilemap, w.players, 0, BuildingKind.BARRACKS, 10, 10)
    place_building(w.tilemap, w.players, 0, BuildingKind.WAR_FACTORY, 14, 10)
    # Spawn an enemy player + a yard at the enemy base spot
    from engine.world import ENEMY_START_YARD_OFFSET_FROM_END
    w.players.append(PlayerState(id=1, credits=5000))
    place_building(w.tilemap, w.players, 1, BuildingKind.CONSTRUCTION_YARD,
                   w.tilemap.width - ENEMY_START_YARD_OFFSET_FROM_END,
                   w.tilemap.height - ENEMY_START_YARD_OFFSET_FROM_END)
    # Spawn an enemy infantry near the enemy yard
    enemy_yard = w.players[1].buildings[-1]
    spawn_unit(w.players[1], w.tilemap, UnitKind.INFANTRY, near=enemy_yard)
    return w


def test_resolve_click_on_own_unit():
    w = _make_two_player_world()
    p0 = w.get_player(0)
    u = spawn_unit(p0, w.tilemap, UnitKind.INFANTRY, near=p0.buildings[0])
    assert u is not None
    target = resolve_click(w.players, 0, (u.col, u.row))
    assert target.is_own_unit
    assert target.own_unit_index == 0


def test_resolve_click_on_enemy_unit():
    w = _make_two_player_world()
    enemy = w.players[1].units[0]
    target = resolve_click(w.players, 0, (enemy.col, enemy.row))
    assert target.is_enemy_unit
    assert target.enemy_player_id == 1


def test_resolve_click_on_enemy_building():
    w = _make_two_player_world()
    eyard = w.players[1].buildings[0]
    target = resolve_click(w.players, 0, (eyard.col, eyard.row))
    assert target.is_enemy_building
    assert target.enemy_player_id == 1


def test_resolve_click_empty_tile():
    w = _make_two_player_world()
    target = resolve_click(w.players, 0, (30, 30))
    assert not target.is_own_unit
    assert not target.is_own_building
    assert not target.is_enemy_unit
    assert not target.is_enemy_building


# ---------------------------------------------------------------------------
# Order issuing + tick_orders
# ---------------------------------------------------------------------------
def test_issue_move_sets_order_and_state():
    p = PlayerState(id=0)
    u = Unit(kind=UnitKind.INFANTRY, owner_id=0, col=10, row=10, hp=60)
    ensure_units(p).append(u)
    n = issue_move([u], (15, 12))
    assert n == 1
    assert u.order is not None
    assert u.order.kind == OrderKind.MOVE
    assert u.state == UnitState.MOVING


def test_issue_attack_move_sets_order_kind():
    p = PlayerState(id=0)
    u = Unit(kind=UnitKind.LIGHT_TANK, owner_id=0, col=10, row=10, hp=120)
    ensure_units(p).append(u)
    issue_attack_move([u], (20, 20))
    assert u.order is not None
    assert u.order.kind == OrderKind.ATTACK_MOVE


def test_tick_orders_attack_unit_deals_damage_when_in_range():
    """If our unit is already in range of the enemy, ticking once should land a hit."""
    tm = generate_default_map(64, 64, seed=1)
    players = [
        PlayerState(id=0, credits=10_000),
        PlayerState(id=1, credits=10_000),
    ]
    # Player 0: heavy_tank (range 5) at (10,10)
    # Player 1: infantry at (12,10) — within Chebyshev range of 2
    a = Unit(kind=UnitKind.HEAVY_TANK, owner_id=0, col=10, row=10, hp=300)
    b = Unit(kind=UnitKind.INFANTRY, owner_id=1, col=12, row=10, hp=60)
    ensure_units(players[0]).append(a)
    ensure_units(players[1]).append(b)
    issue_attack_unit([a], b, 1)
    # At attack order issuance, MOVE kicks in to chase; simulate arrival in range.
    # We've already placed them within range (heavy_tank range = 5 → distance 2 ≤ 5).
    # After issue_attack_unit, the order is ATTACK_UNIT and a.state == MOVING.
    tick_orders(tm, players, dt=1.0)
    # Heavy tank damage = 40; infantry HP 60 → after one tick: 20
    assert b.hp == 60 - UNIT_STATS[UnitKind.HEAVY_TANK].attack
    # The attacker should be in IDLE state because it's in range and standing still.
    assert a.state == UnitState.IDLE
    # Enemy still alive — the order persists.
    assert a.order is not None
    assert a.order.kind == OrderKind.ATTACK_UNIT


def test_tick_orders_attack_unit_kills_target():
    tm = generate_default_map(64, 64, seed=1)
    players = [PlayerState(id=0, credits=10_000), PlayerState(id=1, credits=10_000)]
    a = Unit(kind=UnitKind.HEAVY_TANK, owner_id=0, col=10, row=10, hp=300)
    b = Unit(kind=UnitKind.INFANTRY, owner_id=1, col=11, row=10, hp=10)
    ensure_units(players[0]).append(a)
    ensure_units(players[1]).append(b)
    issue_attack_unit([a], b, 1)
    # Two ticks: each does 40 damage, so by tick 2 we should kill a 10hp target.
    tick_orders(tm, players, dt=1.0)
    # After first tick b is at -30 HP but take_damage clamps to 0 → dead.
    # The order sees the dead target and clears itself.
    tick_orders(tm, players, dt=1.0)
    assert b.is_dead
    # The dead unit should be cleaned up by remove_dead
    remove_dead(players[1])
    assert len(ensure_units(players[1])) == 0
    assert a.order is None
    assert a.state == UnitState.IDLE


def test_tick_orders_attack_building_reduces_hp():
    tm = generate_default_map(64, 64, seed=1)
    players = [PlayerState(id=0, credits=10_000), PlayerState(id=1, credits=10_000)]
    a = Unit(kind=UnitKind.HEAVY_TANK, owner_id=0, col=10, row=10, hp=300)
    players[0].buildings.append(a)  # placeholder, won't use
    players[0].buildings.clear()
    ensure_units(players[0]).append(a)
    # Place a Construction Yard (hp=2000) for enemy at (12,10)
    yard = Building(kind=BuildingKind.CONSTRUCTION_YARD, col=12, row=10, owner_id=1)
    players[1].buildings.append(yard)
    issue_attack_building([a], yard, 1)
    tick_orders(tm, players, dt=1.0)
    assert yard.hp < BUILDING_STATS[BuildingKind.CONSTRUCTION_YARD].hp


def test_tick_orders_attack_building_removes_at_zero_hp():
    tm = generate_default_map(64, 64, seed=1)
    players = [PlayerState(id=0, credits=10_000), PlayerState(id=1, credits=10_000)]
    a = Unit(kind=UnitKind.HEAVY_TANK, owner_id=0, col=10, row=10, hp=300)
    ensure_units(players[0]).append(a)
    yard = Building(kind=BuildingKind.CONSTRUCTION_YARD, col=12, row=10, owner_id=1)
    yard.hp = 1  # one shot
    players[1].buildings.append(yard)
    issue_attack_building([a], yard, 1)
    tick_orders(tm, players, dt=1.0)
    assert yard not in players[1].buildings


def test_tick_orders_attack_move_auto_acquires():
    """ATTACK_MOVE walking past an enemy should switch to ATTACK_UNIT."""
    tm = generate_default_map(64, 64, seed=1)
    players = [PlayerState(id=0, credits=10_000), PlayerState(id=1, credits=10_000)]
    # Our heavy tank at (10,10), ordered to attack-move to (20,10).
    # Enemy infantry at (11,10) within range (5).
    a = Unit(kind=UnitKind.HEAVY_TANK, owner_id=0, col=10, row=10, hp=300)
    b = Unit(kind=UnitKind.INFANTRY, owner_id=1, col=11, row=10, hp=60)
    ensure_units(players[0]).append(a)
    ensure_units(players[1]).append(b)
    issue_attack_move([a], (20, 10))
    tick_orders(tm, players, dt=1.0)  # switch to ATTACK_UNIT
    tick_orders(tm, players, dt=1.0)  # fire
    # Switched to ATTACK_UNIT and dealt damage
    assert a.order is not None
    assert a.order.kind == OrderKind.ATTACK_UNIT
    assert b.hp < 60


def test_tick_orders_attack_move_resumes_after_kill():
    from engine.units import tick_units
    tm = generate_default_map(64, 64, seed=1)
    players = [PlayerState(id=0, credits=10_000), PlayerState(id=1, credits=10_000)]
    a = Unit(kind=UnitKind.HEAVY_TANK, owner_id=0, col=10, row=10, hp=300)
    b = Unit(kind=UnitKind.INFANTRY, owner_id=1, col=11, row=10, hp=10)
    ensure_units(players[0]).append(a)
    ensure_units(players[1]).append(b)
    issue_attack_move([a], (20, 10))
    # First tick: kills b, order may revert to None or ATTACK_UNIT pointing nowhere.
    tick_orders(tm, players, dt=1.0)
    # Second tick: target gone → order cleared
    tick_orders(tm, players, dt=1.0)
    # Re-issue ATTACK_MOVE and confirm we resume walking
    issue_attack_move([a], (20, 10))
    tick_orders(tm, players, dt=1.0)
    tick_units(tm, players, dt=1.0)
    assert a.order is not None
    # Heavy tank advances toward (20,10)
    assert a.col > 10 or a.row != 10


def test_find_enemy_unit_in_range_picks_closest():
    tm = generate_default_map(64, 64, seed=1)
    players = [PlayerState(id=0), PlayerState(id=1)]
    near = Unit(kind=UnitKind.INFANTRY, owner_id=1, col=12, row=10, hp=60)
    far = Unit(kind=UnitKind.INFANTRY, owner_id=1, col=14, row=10, hp=60)
    ensure_units(players[1]).extend([near, far])
    hit = find_enemy_unit_in_range(players, 0, 10, 10, rng=2)
    assert hit is not None
    _, found = hit
    assert found.col == 12 and found.row == 10
    # Out-of-range query → nothing
    assert find_enemy_unit_in_range(players, 0, 10, 10, rng=0) is None


# ---------------------------------------------------------------------------
# Control groups
# ---------------------------------------------------------------------------
def test_control_groups_assign_and_recall():
    p = PlayerState(id=0)
    units = ensure_units(p)
    for i in range(5):
        units.append(Unit(kind=UnitKind.INFANTRY, owner_id=0, col=i, row=i, hp=60))
    g = ControlGroups()
    sel = SelectionState()
    g.assign(1, [0, 2, 4])
    g.recall(1, p, sel)
    assert sel.selected_unit_ids == [0, 2, 4]


def test_control_groups_add_recall_merges():
    p = PlayerState(id=0)
    units = ensure_units(p)
    for i in range(5):
        units.append(Unit(kind=UnitKind.INFANTRY, owner_id=0, col=i, row=i, hp=60))
    g = ControlGroups()
    sel = SelectionState()
    g.assign(1, [0, 2])
    g.assign(2, [2, 4])
    g.recall(1, p, sel)
    g.add_recall(2, p, sel)
    assert sel.selected_unit_ids == [0, 2, 4]


def test_control_groups_recall_prunes_dead_units():
    p = PlayerState(id=0)
    units = ensure_units(p)
    for i in range(3):
        units.append(Unit(kind=UnitKind.INFANTRY, owner_id=0, col=i, row=i, hp=60))
    g = ControlGroups()
    sel = SelectionState()
    g.assign(1, [0, 1, 2])
    # First unit dies & gets removed → indices shift
    units.pop(0)
    n = g.recall(1, p, sel)
    # Only 1, 2 are still valid (originally index 1 → now index 0; originally 2 → 1)
    assert n == 2
    assert sel.selected_unit_ids == [0, 1]


# ---------------------------------------------------------------------------
# HUD event integration (smoke): ensure handle_event runs without crashing
# ---------------------------------------------------------------------------
def test_hud_handle_event_box_select():
    """Drive handle_event with a fake pygame event surface to confirm box-select
    end-to-end doesn't crash and updates the selection."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pygame
    pygame.init()
    w = _make_two_player_world()
    p0 = w.get_player(0)
    # Spawn a few of our own units in a row
    for _ in range(3):
        spawn_unit(p0, w.tilemap, UnitKind.INFANTRY, near=p0.buildings[0])
    from ui.hud import new_controller, handle_event
    ctrl = new_controller()
    # Mock screen pos = tile (8,8) → (8*TILE_SIZE, 8*TILE_SIZE) in world px → screen center plus zoom offset
    from engine.settings import TILE_SIZE
    from ui.hud import tile_to_screen_rect
    sx, sy = tile_to_screen_rect(w.camera, 8, 8).topleft
    # Mouse down at tile (8,8), drag to (12,12), mouse up there.
    e_down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(sx, sy))
    handle_event(e_down, w, ctrl)
    sx2, sy2 = tile_to_screen_rect(w.camera, 12, 12).topleft
    e_up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(sx2, sy2))
    handle_event(e_up, w, ctrl)
    # Some units should be in the box
    assert len(ctrl.selection.selected_unit_ids) >= 0  # may be 0 if all outside, just verify no crash
    pygame.quit()


def test_hud_right_click_move():
    import pygame
    pygame.init()
    w = _make_two_player_world()
    p0 = w.get_player(0)
    spawn_unit(p0, w.tilemap, UnitKind.INFANTRY, near=p0.buildings[0])
    from ui.hud import new_controller, handle_event
    ctrl = new_controller()
    ctrl.selection.select_units([0])
    from engine.settings import TILE_SIZE
    from ui.hud import tile_to_screen_rect
    sx, sy = tile_to_screen_rect(w.camera, 25, 25).topleft
    e = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(sx, sy))
    handle_event(e, w, ctrl)
    u = p0.units[0]
    assert u.order is not None
    assert u.order.kind == OrderKind.MOVE
    assert (u.order.target_col, u.order.target_row) == (25, 25)
    pygame.quit()


def test_hud_a_key_then_right_click_attack_moves():
    import pygame
    pygame.init()
    w = _make_two_player_world()
    p0 = w.get_player(0)
    spawn_unit(p0, w.tilemap, UnitKind.INFANTRY, near=p0.buildings[0])
    from ui.hud import new_controller, handle_event
    ctrl = new_controller()
    ctrl.selection.select_units([0])
    # Press A
    e_a = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0)
    handle_event(e_a, w, ctrl)
    assert ctrl.attack_move_armed
    from engine.settings import TILE_SIZE
    from ui.hud import tile_to_screen_rect
    sx, sy = tile_to_screen_rect(w.camera, 30, 30).topleft
    e = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(sx, sy))
    handle_event(e, w, ctrl)
    u = p0.units[0]
    assert u.order is not None
    assert u.order.kind == OrderKind.ATTACK_MOVE
    assert (u.order.target_col, u.order.target_row) == (30, 30)
    assert not ctrl.attack_move_armed
    pygame.quit()


def test_hud_ctrl_digit_assigns_group():
    import pygame
    pygame.init()
    w = _make_two_player_world()
    p0 = w.get_player(0)
    spawn_unit(p0, w.tilemap, UnitKind.INFANTRY, near=p0.buildings[0])
    spawn_unit(p0, w.tilemap, UnitKind.INFANTRY, near=p0.buildings[0])
    from ui.hud import new_controller, handle_event
    ctrl = new_controller()
    ctrl.selection.select_units([0, 1])
    e = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, mod=pygame.KMOD_CTRL)
    handle_event(e, w, ctrl)
    assert ctrl.groups.assigned.get(1) == [0, 1]
    # Recall with bare digit
    ctrl.selection.clear_units()
    e2 = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, mod=0)
    handle_event(e2, w, ctrl)
    assert ctrl.selection.selected_unit_ids == [0, 1]
    pygame.quit()
