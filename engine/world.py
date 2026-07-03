"""World class — owns the tilemap, camera, and is the core simulation container.

The world is engine-state; later MVPs add units, buildings, and players to it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .camera import Camera
from .settings import DEFAULT_WINDOW_H, DEFAULT_WINDOW_W, MAP_H, MAP_W
from .tilemap import TileMap, generate_default_map


@dataclass
class World:
    tilemap: TileMap
    camera: Camera

    @classmethod
    def new_default(cls, w_tiles: int = MAP_W, h_tiles: int = MAP_H, screen_w: int = DEFAULT_WINDOW_W, screen_h: int = DEFAULT_WINDOW_H, seed: int = 1) -> "World":
        tm = generate_default_map(w_tiles, h_tiles, seed=seed)
        cam = Camera(w_tiles, h_tiles, screen_w, screen_h)
        return cls(tilemap=tm, camera=cam)

    def resize(self, screen_w: int, screen_h: int) -> None:
        self.camera.resize(screen_w, screen_h)
