"""main.py — entrypoint. Boots the game loop, runs main menu, then a match."""
from __future__ import annotations

import sys

import pygame

from engine.render import (
    draw_building_health_bars,
    draw_hit_flash_overlay,
    draw_minimap,
    draw_particles,
    draw_tilemap,
    draw_unit_health_bars,
    init_display,
)
from engine.settings import (
    DEFAULT_WINDOW_H,
    DEFAULT_WINDOW_W,
    FPS,
    MIN_ZOOM,
    MAX_ZOOM,
)
from engine.victory import GameResult, draw_game_over, is_terminal
from engine.world import World
from ui.hud import (
    ControllerState,
    draw_hud_text,
    draw_selection_box,
    draw_selection_markers,
    handle_event,
    new_controller,
)
from ui.menu import MainMenu


def run_menu(screen: pygame.Surface) -> str:
    """Return 'play' or 'quit' based on user's menu choice."""
    clock = pygame.time.Clock()
    menu = MainMenu(screen.get_size())
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
                menu.resize(screen.get_size())
                continue
            action = menu.handle_event(ev)
            if action:
                return action
        menu.update()
        menu.draw(screen)
        pygame.display.flip()
        clock.tick(FPS)


def run_game() -> int:
    pygame.init()
    screen = init_display(DEFAULT_WINDOW_W, DEFAULT_WINDOW_H, "Red Alert 2D")
    clock = pygame.time.Clock()

    choice = run_menu(screen)
    if choice == "quit":
        pygame.quit()
        return 0

    world = World.new_default()
    ctrl: ControllerState = new_controller()
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
                world.resize(*ev.size)
            elif ev.type == pygame.MOUSEWHEEL:
                # Zoom in/out around the mouse position
                mx, my = pygame.mouse.get_pos()
                wx, wy = world.camera.screen_to_world(mx, my)
                z = world.camera.zoom + (0.1 if ev.y > 0 else -0.1)
                world.camera.set_zoom(max(MIN_ZOOM, min(MAX_ZOOM, z)))
                # Keep the world point under the cursor
                wx2, wy2 = world.camera.screen_to_world(mx, my)
                world.camera.move(wx - wx2, wy - wy2)
            elif ev.type in (
                pygame.MOUSEBUTTONDOWN,
                pygame.MOUSEBUTTONUP,
                pygame.MOUSEMOTION,
                pygame.KEYDOWN,
            ):
                # MVP-9: if the game is over, the only valid input is "return to menu".
                if is_terminal(world.game_result):
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                        running = False
                    elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                        running = False
                    continue
                # MVP-5: selection, orders, control groups
                handle_event(ev, world, ctrl)
        mx, my = pygame.mouse.get_pos()
        if not is_terminal(world.game_result):
            world.camera.update_edge_scroll(mx, my, is_window_focused=(pygame.key.get_focused() or True))

        screen.fill((0, 0, 0))
        if not is_terminal(world.game_result):
            draw_tilemap(screen, world.tilemap, world.camera)
            draw_selection_box(screen, world.camera, ctrl)
            draw_selection_markers(screen, world, ctrl)
            draw_unit_health_bars(
                screen, world.camera, world.all_units(),
                selected_ids={id(u) for u in ctrl.selection.units} if ctrl.selection.units else None,
            )
            draw_building_health_bars(
                screen, world.camera, world.all_buildings(),
                selected_ids={id(b) for b in ctrl.selection.buildings} if ctrl.selection.buildings else None,
            )
            draw_hit_flash_overlay(
                screen, world.camera,
                world.all_units(), world.all_buildings(),
                world.flashes,
            )
            draw_particles(screen, world.camera, world.particles)
            draw_minimap(screen, world.tilemap, world.camera)
            draw_hud_text(screen, world, ctrl)
        world.tick(dt=1.0 / FPS)
        # MVP-9: paint the result overlay last, on top of the world (or on black
        # once the player has left the game running long enough to wipe state).
        if is_terminal(world.game_result):
            draw_game_over(screen, world.game_result)
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(run_game())
