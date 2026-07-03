"""main.py — entrypoint. Boots the game loop, runs main menu, then a match."""
from __future__ import annotations

import sys

import pygame

from engine.render import draw_minimap, draw_tilemap, init_display
from engine.settings import (
    DEFAULT_WINDOW_H,
    DEFAULT_WINDOW_W,
    FPS,
    MIN_ZOOM,
    MAX_ZOOM,
)
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
            action = menu.handle_event(ev)
            if action:
                return action
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
                # MVP-5: selection, orders, control groups
                handle_event(ev, world, ctrl)
        mx, my = pygame.mouse.get_pos()
        world.camera.update_edge_scroll(mx, my, is_window_focused=(pygame.key.get_focused() or True))

        screen.fill((0, 0, 0))
        draw_tilemap(screen, world.tilemap, world.camera)
        draw_minimap(screen, world.tilemap, world.camera)
        draw_selection_box(screen, world.camera, ctrl)
        draw_selection_markers(screen, world, ctrl)
        draw_hud_text(screen, world, ctrl)
        world.tick(dt=1.0 / FPS)
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(run_game())
