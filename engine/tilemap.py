"""Tile map: 2D grid of terrain. Pure data; no pygame."""
from __future__ import annotations

import random
from typing import Iterable, List, Tuple

from .settings import MAP_H, MAP_W, Terrain, WALKABLE


Coord = Tuple[int, int]  # (col, row)


class TileMap:
    """2D grid of terrain. Tiles are addressed (col, row)."""

    def __init__(self, width: int = MAP_W, height: int = MAP_H, tiles: List[List[int]] | None = None) -> None:
        self.width = width
        self.height = height
        if tiles is None:
            self.tiles = [[int(Terrain.GRASS) for _ in range(width)] for _ in range(height)]
        else:
            assert len(tiles) == height and all(len(row) == width for row in tiles), "tile grid size mismatch"
            self.tiles = [[int(c) for c in row] for row in tiles]

    # ---- queries -----------------------------------------------------------
    def in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.width and 0 <= row < self.height

    def get(self, col: int, row: int) -> int:
        if not self.in_bounds(col, row):
            return int(Terrain.WATER)  # treat OOB as solid
        return self.tiles[row][col]

    def is_walkable(self, col: int, row: int) -> bool:
        return self.in_bounds(col, row) and self.get(col, row) in WALKABLE

    def is_ore(self, col: int, row: int) -> bool:
        return self.get(col, row) == int(Terrain.ORE)

    # ---- mutation ----------------------------------------------------------
    def set(self, col: int, row: int, terrain: int) -> None:
        if self.in_bounds(col, row):
            self.tiles[row][col] = int(terrain)

    # ---- helpers -----------------------------------------------------------
    def iter_ores(self) -> Iterable[Coord]:
        for r in range(self.height):
            for c in range(self.width):
                if self.tiles[r][c] == int(Terrain.ORE):
                    yield (c, r)

    def count(self, terrain: int) -> int:
        t = int(terrain)
        return sum(1 for r in range(self.height) for c in range(self.width) if self.tiles[r][c] == t)

    def ore_within(self, col: int, row: int, radius: int) -> bool:
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if self.is_ore(col + dc, row + dr):
                    return True
        return False


def generate_default_map(width: int = MAP_W, height: int = MAP_H, seed: int = 1) -> TileMap:
    """Default map: grass base, a water lake, several ore patches.

    Deterministic given seed, so tests can assert exact layouts.
    """
    rng = random.Random(seed)
    tm = TileMap(width, height)

    # Lake in the middle band
    lake_w = max(8, width // 6)
    lake_h = max(6, height // 10)
    cx = width // 2
    cy = height // 2
    for r in range(cy - lake_h // 2, cy + lake_h // 2):
        for c in range(cx - lake_w // 2, cx + lake_w // 2):
            if 0 <= c < width and 0 <= r < height:
                tm.set(c, r, Terrain.WATER)

    # 4 ore patches in 4 quadrants
    quadrants = [
        (width // 4, height // 4),
        (3 * width // 4, height // 4),
        (width // 4, 3 * height // 4),
        (3 * width // 4, 3 * height // 4),
    ]
    for qx, qy in quadrants:
        patch_r = max(3, min(width, height) // 12)
        for _ in range(40 + rng.randint(0, 20)):
            dc = rng.randint(-patch_r, patch_r)
            dr = rng.randint(-patch_r, patch_r)
            c, r = qx + dc, qy + dr
            if tm.in_bounds(c, r) and tm.get(c, r) == int(Terrain.GRASS):
                tm.set(c, r, Terrain.ORE)

    # Ensure a player base spot near (5, 5) is clear
    for r in range(3, 8):
        for c in range(3, 8):
            if tm.in_bounds(c, r):
                tm.set(c, r, Terrain.GRASS)

    # Ensure an enemy base spot near (width-8, height-8) is clear
    for r in range(height - 8, height - 3):
        for c in range(width - 8, width - 3):
            if tm.in_bounds(c, r):
                tm.set(c, r, Terrain.GRASS)

    return tm
