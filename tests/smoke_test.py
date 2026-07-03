"""Headless smoke test: runs the game main loop for N frames with no crash.

This is the regression net for every iteration. Each MVP must keep this green.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

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
from engine.settings import DEFAULT_WINDOW_H, DEFAULT_WINDOW_W, FPS
from engine.world import World


def run(frames: int = 300) -> int:
    pygame.init()
    screen = init_display(DEFAULT_WINDOW_W, DEFAULT_WINDOW_H, "smoke")
    clock = pygame.time.Clock()
    world = World.new_default()

    for f in range(frames):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return f
            elif ev.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
                world.resize(*ev.size)
        # Simulate a mouse cursor moving to trigger edge-scroll on a few frames
        mx = (f * 7) % DEFAULT_WINDOW_W
        my = (f * 11) % DEFAULT_WINDOW_H
        world.camera.update_edge_scroll(mx, my, is_window_focused=True)
        # Periodic zoom oscillation
        if f % 60 == 0:
            world.camera.set_zoom(1.0 + 0.5 * ((f // 60) % 3 == 0))

        screen.fill((0, 0, 0))
        draw_tilemap(screen, world.tilemap, world.camera)
        # MVP-7: visual layers — must not crash even with empty pools.
        draw_unit_health_bars(screen, world.camera, world.all_units())
        draw_building_health_bars(screen, world.camera, world.all_buildings())
        draw_hit_flash_overlay(
            screen, world.camera,
            world.all_units(), world.all_buildings(),
            world.flashes,
        )
        draw_particles(screen, world.camera, world.particles)
        draw_minimap(screen, world.tilemap, world.camera)
        world.tick(dt=1.0 / FPS)
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    return frames


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    t0 = time.time()
    done = run(n)
    dt = time.time() - t0
    print(f"smoke: ran {done} frames in {dt:.2f}s")
    if done < n:
        sys.exit(1)
    sys.exit(0)
