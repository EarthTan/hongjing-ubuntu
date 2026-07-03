"""Pygame rendering for the map, camera, and minimap.

Isolated from logic so headless tests can run without importing pygame at all
in logic files. This module is the only one that needs the dummy SDL driver.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

try:
    import pygame  # type: ignore
except Exception:  # pragma: no cover - headless paths
    pygame = None  # type: ignore

from .camera import Camera
from .settings import (
    MINIMAP_BG,
    MINIMAP_BORDER,
    MINIMAP_MARGIN,
    MINIMAP_VIEWPORT_COLOR,
    MINIMAP_H,
    MINIMAP_W,
    TERRAIN_COLOR,
    TILE_SIZE,
    WALKABLE,
)
from .tilemap import TileMap


def make_screen(width: int, height: int) -> "pygame.Surface":
    """Create a pygame display surface. Caller is responsible for init."""
    return pygame.display.set_mode((width, height), pygame.RESIZABLE)


def init_display(width: int, height: int, title: str = "Red Alert 2D") -> "pygame.Surface":
    pygame.display.set_caption(title)
    return make_screen(width, height)


def draw_tilemap(surface: "pygame.Surface", tilemap: TileMap, camera: Camera) -> None:
    """Draw visible tiles using the camera transform."""
    if pygame is None:
        return
    x0, y0, w, h = camera.visible_world_rect()
    # Tile range
    tile_w_world = TILE_SIZE
    col_start = max(0, int(math.floor(x0 / tile_w_world)))
    col_end = min(tilemap.width, int(math.ceil((x0 + w) / tile_w_world)) + 1)
    row_start = max(0, int(math.floor(y0 / tile_w_world)))
    row_end = min(tilemap.height, int(math.ceil((y0 + h) / tile_w_world)) + 1)
    for r in range(row_start, row_end):
        for c in range(col_start, col_end):
            terrain = tilemap.get(c, r)
            color = TERRAIN_COLOR.get(terrain, TERRAIN_COLOR[0])
            wx = c * tile_w_world
            wy = r * tile_w_world
            sx, sy = camera.world_to_screen(wx, wy)
            ts = max(1, int(TILE_SIZE * camera.zoom))
            pygame.draw.rect(surface, color, pygame.Rect(int(sx), int(sy), ts, ts))
            # Subtle gridline for tiles
            if ts >= 12:
                pygame.draw.rect(surface, (0, 0, 0), pygame.Rect(int(sx), int(sy), ts, ts), 1)


def draw_minimap(
    surface: "pygame.Surface",
    tilemap: TileMap,
    camera: Camera,
    extra: Sequence[Tuple[int, int, Tuple[int, int, int]]] | None = None,
) -> None:
    """Draw a minimap in the top-right corner. extra = list of (col, row, color) dots to overlay."""
    if pygame is None:
        return
    sw, sh = surface.get_size()
    mw, mh = MINIMAP_W, MINIMAP_H
    x = sw - mw - MINIMAP_MARGIN
    y = MINIMAP_MARGIN
    # Background
    pygame.draw.rect(surface, MINIMAP_BG, pygame.Rect(x, y, mw, mh))
    # Tiles
    scale_x = mw / tilemap.width
    scale_y = mh / tilemap.height
    for r in range(tilemap.height):
        for c in range(tilemap.width):
            terrain = tilemap.get(c, r)
            color = TERRAIN_COLOR.get(terrain, TERRAIN_COLOR[0])
            px = int(x + c * scale_x)
            py = int(y + r * scale_y)
            pw = max(1, int(math.ceil(scale_x)))
            ph = max(1, int(math.ceil(scale_y)))
            pygame.draw.rect(surface, color, pygame.Rect(px, py, pw, ph))
    # Extras (units / buildings) overlay
    if extra:
        for (c, r, color) in extra:
            if 0 <= c < tilemap.width and 0 <= r < tilemap.height:
                px = int(x + c * scale_x)
                py = int(y + r * scale_y)
                pw = max(1, int(math.ceil(scale_x)))
                ph = max(1, int(math.ceil(scale_y)))
                pygame.draw.rect(surface, color, pygame.Rect(px, py, pw, ph))
    # Viewport rectangle
    vx, vy, vw, vh = camera.visible_world_rect()
    vx0 = x + (vx / (tilemap.width * TILE_SIZE)) * mw
    vy0 = y + (vy / (tilemap.height * TILE_SIZE)) * mh
    vw0 = (vw / (tilemap.width * TILE_SIZE)) * mw
    vh0 = (vh / (tilemap.height * TILE_SIZE)) * mh
    pygame.draw.rect(surface, MINIMAP_VIEWPORT_COLOR, pygame.Rect(int(vx0), int(vy0), int(vw0) + 1, int(vh0) + 1), 1)
    # Border on top
    pygame.draw.rect(surface, MINIMAP_BORDER, pygame.Rect(x, y, mw, mh), 1)


def minimap_click_to_tile(camera_screen_pos: Tuple[int, int], tilemap: TileMap, screen_size: Tuple[int, int]) -> Tuple[int, int] | None:
    """If the given screen coord is inside the minimap, return the (col, row) tile it points to."""
    sw, sh = screen_size
    mw, mh = MINIMAP_W, MINIMAP_H
    x = sw - mw - MINIMAP_MARGIN
    y = MINIMAP_MARGIN
    sx, sy = camera_screen_pos
    if not (x <= sx < x + mw and y <= sy < y + mh):
        return None
    tx = (sx - x) / mw * tilemap.width
    ty = (sy - y) / mh * tilemap.height
    return (int(tx), int(ty))


def draw_fps(surface: "pygame.Surface", clock: "pygame.time.Clock", x: int = 8, y: int = 8) -> None:
    if pygame is None:
        return
    fps = clock.get_fps()
    font = pygame.font.SysFont("monospace", 14)
    txt = font.render(f"FPS: {fps:5.1f}  Zoom: x1.0", True, (255, 255, 255))
    surface.blit(txt, (x, y))
