"""Camera with edge scrolling and zoom. Pure data; no pygame."""
from __future__ import annotations

from typing import Tuple

from .settings import (
    DEFAULT_ZOOM,
    EDGE_SCROLL_MARGIN,
    EDGE_SCROLL_SPEED,
    MAX_ZOOM,
    MIN_ZOOM,
    MAP_H,
    MAP_W,
    TILE_SIZE,
)


class Camera:
    """Centred on (cx, cy) in world pixels. Supports zoom and edge scrolling."""

    def __init__(
        self,
        map_w_tiles: int = MAP_W,
        map_h_tiles: int = MAP_H,
        screen_w: int = 1024,
        screen_h: int = 768,
        zoom: float = DEFAULT_ZOOM,
    ) -> None:
        self.map_w_px = map_w_tiles * TILE_SIZE
        self.map_h_px = map_h_tiles * TILE_SIZE
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        # Centre in world pixels
        self.cx = self.map_w_px / 2.0
        self.cy = self.map_h_px / 2.0

    # ---- world <-> screen conversion --------------------------------------
    def world_to_screen(self, wx: float, wy: float) -> Tuple[float, float]:
        sx = (wx - self.cx) * self.zoom + self.screen_w / 2.0
        sy = (wy - self.cy) * self.zoom + self.screen_h / 2.0
        return (sx, sy)

    def screen_to_world(self, sx: float, sy: float) -> Tuple[float, float]:
        wx = (sx - self.screen_w / 2.0) / self.zoom + self.cx
        wy = (sy - self.screen_h / 2.0) / self.zoom + self.cy
        return (wx, wy)

    # ---- movement ---------------------------------------------------------
    def move(self, dx: float, dy: float) -> None:
        self.cx = self.clamp_x(self.cx + dx)
        self.cy = self.clamp_y(self.cy + dy)

    def clamp_x(self, x: float) -> float:
        half_view = (self.screen_w / 2.0) / self.zoom
        if self.map_w_px <= 2 * half_view:
            return self.map_w_px / 2.0
        return max(half_view, min(self.map_w_px - half_view, x))

    def clamp_y(self, y: float) -> float:
        half_view = (self.screen_h / 2.0) / self.zoom
        if self.map_h_px <= 2 * half_view:
            return self.map_h_px / 2.0
        return max(half_view, min(self.map_h_px - half_view, y))

    def set_zoom(self, z: float) -> None:
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, z))
        # Re-clamp position so we don't go past the map
        self.cx = self.clamp_x(self.cx)
        self.cy = self.clamp_y(self.cy)

    # ---- edge scroll ------------------------------------------------------
    def update_edge_scroll(self, mouse_x: float, mouse_y: float, is_window_focused: bool = True) -> None:
        """If the mouse is near a window edge, scroll the camera.

        mouse_x, mouse_y are screen coordinates (pixels). Window must be focused
        to scroll (prevents the camera from drifting when the user alt-tabs).
        """
        if not is_window_focused:
            return
        dx, dy = 0.0, 0.0
        if mouse_x < EDGE_SCROLL_MARGIN:
            dx = -EDGE_SCROLL_SPEED * (EDGE_SCROLL_MARGIN - mouse_x) / EDGE_SCROLL_MARGIN
        elif mouse_x > self.screen_w - EDGE_SCROLL_MARGIN:
            dx = EDGE_SCROLL_SPEED * (mouse_x - (self.screen_w - EDGE_SCROLL_MARGIN)) / EDGE_SCROLL_MARGIN
        if mouse_y < EDGE_SCROLL_MARGIN:
            dy = -EDGE_SCROLL_SPEED * (EDGE_SCROLL_MARGIN - mouse_y) / EDGE_SCROLL_MARGIN
        elif mouse_y > self.screen_h - EDGE_SCROLL_MARGIN:
            dy = EDGE_SCROLL_SPEED * (mouse_y - (self.screen_h - EDGE_SCROLL_MARGIN)) / EDGE_SCROLL_MARGIN
        if dx or dy:
            self.move(dx / self.zoom, dy / self.zoom)

    # ---- helpers ----------------------------------------------------------
    def visible_world_rect(self) -> Tuple[float, float, float, float]:
        """Return (x, y, w, h) of the visible world rect in world pixels."""
        half_w = (self.screen_w / 2.0) / self.zoom
        half_h = (self.screen_h / 2.0) / self.zoom
        return (self.cx - half_w, self.cy - half_h, 2 * half_w, 2 * half_h)

    def resize(self, screen_w: int, screen_h: int) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.cx = self.clamp_x(self.cx)
        self.cy = self.clamp_y(self.cy)
