"""Game-wide constants. Pure data, no pygame imports here."""
from enum import IntEnum


# Window / screen
DEFAULT_WINDOW_W = 1024
DEFAULT_WINDOW_H = 768
MIN_WINDOW_W = 640
MIN_WINDOW_H = 480
FPS = 60

# Tile grid
TILE_SIZE = 32  # pixels per tile (used for unit-to-tile conversion; rendering scales by zoom)
MAP_W = 64  # tiles wide
MAP_H = 64  # tiles tall

# Camera
MIN_ZOOM = 0.5
MAX_ZOOM = 2.0
DEFAULT_ZOOM = 1.0
EDGE_SCROLL_MARGIN = 8  # px from window edge that triggers scroll
EDGE_SCROLL_SPEED = 12  # px/frame at max edge proximity

# Minimap
MINIMAP_W = 200
MINIMAP_H = 200
MINIMAP_MARGIN = 10
MINIMAP_BG = (0, 0, 0)
MINIMAP_BORDER = (200, 200, 200)
MINIMAP_VIEWPORT_COLOR = (255, 255, 255)

# Terrain
class Terrain(IntEnum):
    GRASS = 0
    WATER = 1
    ORE = 2  # mineral field


# Colors for terrain (RGB)
TERRAIN_COLOR = {
    Terrain.GRASS: (60, 140, 60),
    Terrain.WATER: (40, 80, 200),
    Terrain.ORE: (200, 200, 80),
}

# Walkability
WALKABLE = {Terrain.GRASS, Terrain.ORE}
UNWALKABLE = {Terrain.WATER}

# Tile grid coordinates are (col, row) = (x, y).
