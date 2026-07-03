"""HUD/controller for MVP-5: selection, orders, control groups.

Translates pygame mouse + keyboard events into engine.selection / engine.orders /
engine.groups calls. No game logic lives here — only event wiring + rendering
of selection box and a tiny credits readout.

Controls (classic RA-style):
  Left drag on map:        box-select own units
  Left click on own unit:  select that unit (additive with Shift)
  Left click on own bldg:  select that building
  Left click empty:        deselect
  Right click on enemy:    attack
  Right click on own unit: move to that tile (no-op for now: classic RA does nothing)
  Right click on map:      move / attack-move depending on last-set mode
  A (held) before R-click: attack-move to tile
  Ctrl+<1..9>: assign current selection to group
  <1..9>: recall group
  Shift+<1..9>: recall group additively
  Esc: clear selection
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

from engine.camera import Camera
from engine.groups import ControlGroups
from engine.orders import (
    Order,
    OrderKind,
    issue_attack_building,
    issue_attack_move,
    issue_attack_unit,
    issue_move,
)
from engine.selection import (
    ClickTarget,
    SelectionState,
    building_at_tile,
    resolve_click,
    units_in_box,
)
from engine.settings import TILE_SIZE
from engine.units import Unit, ensure_units
from engine.world import World


Coord = Tuple[int, int]


# ---------------------------------------------------------------------------
# Controller state (held by main loop)
# ---------------------------------------------------------------------------
@dataclass
class ControllerState:
    selection: SelectionState
    groups: ControlGroups
    # When the user pressed 'A' and hasn't right-clicked yet, the next right-
    # click on the map becomes attack-move instead of plain move.
    attack_move_armed: bool = False
    # Last-action feedback string for the HUD ("Selected 3 units", etc.)
    last_action: str = ""


def new_controller() -> ControllerState:
    return ControllerState(
        selection=SelectionState(),
        groups=ControlGroups(),
    )


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------
def screen_to_tile(camera: Camera, sx: int, sy: int) -> Coord:
    """Convert screen px to tile (col, row). Out-of-bounds clamps to map edge."""
    wx, wy = camera.screen_to_world(sx, sy)
    c = int(wx // TILE_SIZE)
    r = int(wy // TILE_SIZE)
    return (c, r)


def tile_to_screen_rect(camera: Camera, col: int, row: int) -> pygame.Rect:
    wx = col * TILE_SIZE
    wy = row * TILE_SIZE
    sx, sy = camera.world_to_screen(wx, wy)
    ts = max(1, int(TILE_SIZE * camera.zoom))
    return pygame.Rect(int(sx), int(sy), ts, ts)


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------
def handle_event(
    ev: pygame.event.Event,
    world: World,
    ctrl: ControllerState,
) -> None:
    """Dispatch a single pygame event. Mutates world + ctrl in place."""
    if ev.type == pygame.MOUSEBUTTONDOWN:
        _on_mouse_down(ev, world, ctrl)
    elif ev.type == pygame.MOUSEBUTTONUP:
        _on_mouse_up(ev, world, ctrl)
    elif ev.type == pygame.MOUSEMOTION:
        _on_mouse_motion(ev, world, ctrl)
    elif ev.type == pygame.KEYDOWN:
        _on_key_down(ev, world, ctrl)


def _on_mouse_down(ev: pygame.event.Event, world: World, ctrl: ControllerState) -> None:
    if ev.button == 1:
        ctrl.selection.clear_building()  # building selection happens on click release
        tile = screen_to_tile(world.camera, *ev.pos)
        ctrl.selection.begin_box(tile)
    elif ev.button == 3:
        _do_right_click(ev.pos, world, ctrl)


def _on_mouse_up(ev: pygame.event.Event, world: World, ctrl: ControllerState) -> None:
    if ev.button == 1:
        tile = screen_to_tile(world.camera, *ev.pos)
        box = ctrl.selection.end_box()
        owner = world.get_player(0)
        mods = getattr(ev, "mod", 0) or pygame.key.get_mods()
        additive = bool(mods & pygame.KMOD_SHIFT)
        if box is None:
            return  # never began
        c0, r0, c1, r1 = box
        if (c1 - c0) <= 0 and (r1 - r0) <= 0:
            # Single-tile click — try to select a unit/building under it
            _single_click_select(tile, owner, ctrl, additive=additive)
            return
        # Box-select: replace unless additive
        idxs = units_in_box(owner, box)
        if additive:
            ctrl.selection.add_units(idxs)
        else:
            ctrl.selection.select_units(idxs)
        ctrl.last_action = f"Selected {len(ctrl.selection.selected_unit_ids)} units"


def _on_mouse_motion(ev: pygame.event.Event, world: World, ctrl: ControllerState) -> None:
    if not ctrl.selection.dragging:
        return
    tile = screen_to_tile(world.camera, *ev.pos)
    ctrl.selection.update_box(tile)


def _on_key_down(ev: pygame.event.Event, world: World, ctrl: ControllerState) -> None:
    # Prefer the modifier attached to the event (lets tests synthesize
    # Ctrl+1 without an actual keypress); fall back to the live global mods.
    mods = getattr(ev, "mod", 0) or pygame.key.get_mods()
    ctrl_held = bool(mods & pygame.KMOD_CTRL)
    shift_held = bool(mods & pygame.KMOD_SHIFT)
    if ev.key == pygame.K_ESCAPE:
        ctrl.selection.clear_all()
        ctrl.last_action = "Cleared selection"
        return
    if ev.key == pygame.K_a:
        ctrl.attack_move_armed = True
        ctrl.last_action = "Attack-move armed"
        return
    # Digit keys 1..9 for control groups
    if pygame.K_1 <= ev.key <= pygame.K_9:
        slot = ev.key - pygame.K_0  # 1..9
        owner = world.get_player(0)
        if ctrl_held:
            ctrl.groups.assign(slot, ctrl.selection.selected_unit_ids)
            ctrl.last_action = f"Assigned group {slot}"
            return
        if shift_held:
            n = ctrl.groups.add_recall(slot, owner, ctrl.selection)
            ctrl.last_action = f"Added group {slot} (+{n})"
            return
        n = ctrl.groups.recall(slot, owner, ctrl.selection)
        ctrl.last_action = f"Recalled group {slot} ({n})"
        return


def _single_click_select(
    tile: Coord,
    owner,
    ctrl: ControllerState,
    additive: bool,
) -> None:
    """Click on one tile: prefer own unit → own building → deselect."""
    col, r = tile
    ui = None
    units = ensure_units(owner)
    for i, u in enumerate(units):
        if u.col == col and u.row == r:
            ui = i
            break
    if ui is not None:
        if additive:
            ctrl.selection.toggle_unit(ui)
        else:
            ctrl.selection.select_units([ui])
        ctrl.last_action = f"Selected unit"
        return
    bi = building_at_tile(owner, col, r)
    if bi is not None:
        if additive:
            # Toggle building selection (single only)
            if ctrl.selection.selected_building_index == bi:
                ctrl.selection.clear_building()
            else:
                ctrl.selection.select_building(bi)
        else:
            ctrl.selection.clear_units()
            ctrl.selection.select_building(bi)
        ctrl.last_action = "Selected building"
        return
    if not additive:
        ctrl.selection.clear_all()
        ctrl.last_action = ""


def _do_right_click(screen_pos: Tuple[int, int], world: World, ctrl: ControllerState) -> None:
    owner = world.get_player(0)
    selected = ctrl.selection.selected_units(owner)
    if not selected:
        return
    tile = screen_to_tile(world.camera, *screen_pos)
    target: ClickTarget = resolve_click(world.players, owner.id, tile)

    # If a specific enemy unit is under the cursor → attack it.
    if target.is_enemy_unit and target.enemy_unit is not None and not ctrl.attack_move_armed:
        issue_attack_unit(selected, target.enemy_unit, target.enemy_player_id or 0)
        ctrl.last_action = "Attack!"
        ctrl.attack_move_armed = False
        return
    # Same for enemy building.
    if target.is_enemy_building and target.enemy_building is not None and not ctrl.attack_move_armed:
        issue_attack_building(selected, target.enemy_building, target.enemy_player_id or 0)
        ctrl.last_action = "Attack!"
        ctrl.attack_move_armed = False
        return
    # Otherwise: plain move, or attack-move if 'A' was armed.
    if ctrl.attack_move_armed:
        issue_attack_move(selected, tile)
        ctrl.last_action = f"Attack-move → {tile}"
        ctrl.attack_move_armed = False
        return
    issue_move(selected, tile)
    ctrl.last_action = f"Move → {tile}"


# ---------------------------------------------------------------------------
# Rendering (selection box + minimal HUD strip)
# ---------------------------------------------------------------------------
def draw_selection_box(surface: pygame.Surface, camera: Camera, ctrl: ControllerState) -> None:
    rect = ctrl.selection.current_box_rect()
    if rect is None:
        return
    c0, r0, c1, r1 = rect
    # Tile (c0,r0) and (c1,r1) — draw the screen-space rect.
    tl = tile_to_screen_rect(camera, c0, r0)
    br = tile_to_screen_rect(camera, c1 + 1, r1 + 1)
    screen_rect = pygame.Rect(tl.x, tl.y, br.x - tl.x, br.y - tl.y)
    pygame.draw.rect(surface, (0, 255, 0), screen_rect, 2)


def draw_selection_markers(
    surface: pygame.Surface,
    world: World,
    ctrl: ControllerState,
) -> None:
    """Tiny marker under every selected unit and a yellow rect around the
    selected building (if any)."""
    owner = world.get_player(0)
    # Units
    units = ensure_units(owner)
    for i in ctrl.selection.selected_unit_ids:
        if 0 <= i < len(units):
            u = units[i]
            r = tile_to_screen_rect(world.camera, u.col, u.row)
            pygame.draw.rect(surface, (0, 255, 0), r, 1)
    # Building
    b = ctrl.selection.selected_building(owner)
    if b is not None:
        r = tile_to_screen_rect(world.camera, b.col, b.row)
        ts = max(1, int(TILE_SIZE * world.camera.zoom))
        rect = pygame.Rect(r.x, r.y, ts * 2, ts * 2)
        pygame.draw.rect(surface, (255, 255, 0), rect, 2)


def draw_hud_text(surface: pygame.Surface, world: World, ctrl: ControllerState) -> None:
    """Top-left strip: credits + selected-unit count + last action."""
    font = pygame.font.SysFont("monospace", 14)
    owner = world.get_player(0)
    lines = [
        f"Credits: ${owner.credits}",
        f"Selected: {len(ctrl.selection.selected_unit_ids)} unit(s)",
        f"Power: {ctrl.last_action}",
    ]
    for i, t in enumerate(lines):
        s = font.render(t, True, (220, 220, 220))
        surface.blit(s, (8, 30 + i * 16))
    # Attack-move indicator
    if ctrl.attack_move_armed:
        s = font.render("[A] ATTACK-MOVE ARMED — right-click to confirm", True, (255, 100, 100))
        surface.blit(s, (8, 90))
