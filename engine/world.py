"""World class — owns the tilemap, camera, players, and is the core simulation
container. Logic-only; rendering lives in engine.render.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .buildings import (
    Building,
    BuildingKind,
    PlayerState,
    place_building,
    recompute_power,
    tick_construction,
)
from .camera import Camera
from .orders import tick_orders
from .resources import (
    Harvester,
    tick_harvesters,
    tick_refineries_spawn_harvesters,
)
from .units import tick_units
from .settings import DEFAULT_WINDOW_H, DEFAULT_WINDOW_W, MAP_H, MAP_W
from .tilemap import TileMap, generate_default_map


# Starting credits & initial building placement for a fresh game.
PLAYER_START_CREDITS = 5000
ENEMY_START_CREDITS = 5000
PLAYER_START_YARD = (5, 5)
ENEMY_START_YARD_OFFSET_FROM_END = 8  # yard top-left at (w - 8, h - 8)


@dataclass
class World:
    tilemap: TileMap
    camera: Camera
    players: List[PlayerState] = field(default_factory=list)

    @classmethod
    def new_default(
        cls,
        w_tiles: int = MAP_W,
        h_tiles: int = MAP_H,
        screen_w: int = DEFAULT_WINDOW_W,
        screen_h: int = DEFAULT_WINDOW_H,
        seed: int = 1,
    ) -> "World":
        tm = generate_default_map(w_tiles, h_tiles, seed=seed)
        cam = Camera(w_tiles, h_tiles, screen_w, screen_h)
        world = cls(tilemap=tm, camera=cam)

        # Player 0 gets a Construction Yard at the pre-cleared (5,5) base spot.
        p0 = PlayerState(id=0, credits=PLAYER_START_CREDITS)
        world.players.append(p0)
        b = place_building(tm, world.players, 0, BuildingKind.CONSTRUCTION_YARD, *PLAYER_START_YARD)
        if b is None:
            raise RuntimeError("Default map failed to provide a buildable player yard spot")
        # The construction yard shouldn't have cost the starting credits — refund the yard baseline.
        # Cost of yard = 2000. We gave 5000, so player is left with 3000 by default; users can override.
        return world

    def resize(self, screen_w: int, screen_h: int) -> None:
        self.camera.resize(screen_w, screen_h)

    def get_player(self, player_id: int) -> PlayerState:
        return next(p for p in self.players if p.id == player_id)

    def power_grids(self) -> dict[int, "PowerGrid"]:  # type: ignore[name-defined]
        return recompute_power(self.players)

    def all_buildings(self) -> list[Building]:
        out: list[Building] = []
        for p in self.players:
            out.extend(p.buildings)
        return out

    def all_harvesters(self) -> List[Harvester]:
        out: List[Harvester] = []
        for p in self.players:
            if hasattr(p, "harvesters"):
                out.extend(p.harvesters)
        return out

    def tick(self, dt: float = 1.0) -> None:
        """Advance the full simulation by ``dt`` seconds.

        Order:
          1. Construction tick (per player, in player-id order).
          2. Refinery auto-production of harvesters (per player).
          3. Harvester state machine tick (per player).
          4. Unit tick (per player) — MVP-4 movement.
          5. Order tick (per player) — MVP-5 attack/attack-move.
        """
        for p in sorted(self.players, key=lambda x: x.id):
            tick_construction(self.tilemap, self.players, p.id, dt=dt)
        tick_refineries_spawn_harvesters(self.players, self.tilemap)
        tick_harvesters(self.tilemap, self.players, dt)
        tick_units(self.tilemap, self.players, dt)
        tick_orders(self.tilemap, self.players, dt)

    def all_units(self):
        """Return every player's units, flattened."""
        from .units import ensure_units
        out = []
        for p in self.players:
            out.extend(ensure_units(p))
        return out
