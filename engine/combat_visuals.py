"""Combat visual effects: hit flashes, health-bar values, death particles.

Pure logic — no pygame. Holds the data structures (Particle, HitFlashState) and
the small tick/calculation helpers the renderer reads each frame. MVP-7 covers:

  - Hit flash timer: when a unit/building takes damage, briefly tint it white.
    Decays linearly over HIT_FLASH_DURATION seconds.
  - Death particles: when a unit/building dies, spawn N short-lived particles
    that fly outward and fade out, then are removed by tick_particles.
  - Health-bar color/value: given (hp, max_hp), compute the bar fill ratio and
    a green→yellow→red color for the renderer to draw on top of the entity.

The renderer is in ``engine.render`` and reads from these values; the logic
layer is fully unit-testable without pygame.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple


# -----------------------------------------------------------------------------
# Tunables
# -----------------------------------------------------------------------------
HIT_FLASH_DURATION = 0.12  # seconds — short white pulse when damage is taken
PARTICLE_LIFETIME = 0.6  # seconds — death explosion duration
PARTICLE_COUNT_UNIT = 8  # particles per unit death
PARTICLE_COUNT_BUILDING = 16  # particles per building death
PARTICLE_SPEED_MIN = 30.0  # pixels per second
PARTICLE_SPEED_MAX = 90.0
PARTICLE_SIZE = 3  # base radius in pixels (renderer scales by camera zoom)
PARTICLE_GRAVITY = 80.0  # px/s^2 pulling particles downward for visual weight


# -----------------------------------------------------------------------------
# Hit-flash state (attached to Unit / Building via a sidecar list on World)
# -----------------------------------------------------------------------------
@dataclass
class HitFlashState:
    """Per-entity hit-flash bookkeeping. World keeps one of these per living
    unit / building under ``world.flashes`` keyed by id(entity)."""
    timer: float = 0.0  # remaining seconds; 0 ⇒ inactive

    def is_active(self) -> bool:
        return self.timer > 0.0

    def intensity(self) -> float:
        """0..1 fade value (1 ⇒ full white flash, 0 ⇒ no overlay)."""
        if self.timer <= 0.0:
            return 0.0
        return max(0.0, min(1.0, self.timer / HIT_FLASH_DURATION))


def trigger_flash(flash: HitFlashState) -> None:
    """Restart the flash timer on a damage event."""
    flash.timer = HIT_FLASH_DURATION


def tick_flash(flash: HitFlashState, dt: float) -> None:
    if flash.timer > 0.0:
        flash.timer = max(0.0, flash.timer - dt)


# -----------------------------------------------------------------------------
# Death particles
# -----------------------------------------------------------------------------
@dataclass
class Particle:
    """A single short-lived visual particle.

    Position is stored in world-pixel coordinates (col*TILE_SIZE, row*TILE_SIZE)
    plus an offset. The renderer turns this into screen pixels via the camera.
    """
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: Tuple[int, int, int]
    size: float = PARTICLE_SIZE

    @property
    def alive(self) -> bool:
        return self.life > 0.0


def spawn_death_particles(
    center_x: float,
    center_y: float,
    count: int,
    color: Tuple[int, int, int],
    rng: random.Random | None = None,
) -> List[Particle]:
    """Generate a burst of ``count`` particles centered on (cx, cy)."""
    rng = rng or random.Random()
    out: List[Particle] = []
    for _ in range(count):
        # Random direction, full 360°
        angle = rng.uniform(0.0, 2.0 * math.pi)
        speed = rng.uniform(PARTICLE_SPEED_MIN, PARTICLE_SPEED_MAX)
        vx = math.cos(angle) * speed
        vy = math.sin(angle) * speed
        # Small lifetime jitter so they don't all vanish on the same frame
        life = PARTICLE_LIFETIME * rng.uniform(0.7, 1.0)
        # Small color jitter for visual variety
        cr = max(0, min(255, color[0] + rng.randint(-30, 30)))
        cg = max(0, min(255, color[1] + rng.randint(-30, 30)))
        cb = max(0, min(255, color[2] + rng.randint(-30, 30)))
        out.append(
            Particle(
                x=center_x,
                y=center_y,
                vx=vx,
                vy=vy,
                life=life,
                max_life=life,
                color=(cr, cg, cb),
            )
        )
    return out


def tick_particles(particles: List[Particle], dt: float) -> int:
    """Advance every particle by dt seconds; remove dead ones in-place.

    Returns the count removed.
    """
    if dt <= 0.0:
        return 0
    before = len(particles)
    # Update in-place
    for p in particles:
        p.x += p.vx * dt
        p.y += p.vy * dt
        p.vy += PARTICLE_GRAVITY * dt
        p.life -= dt
    # Compact
    particles[:] = [p for p in particles if p.life > 0.0]
    return before - len(particles)


# -----------------------------------------------------------------------------
# Health-bar logic
# -----------------------------------------------------------------------------
def health_ratio(hp: int, max_hp: int) -> float:
    """0..1 fill ratio for a health bar. Clamped to [0, 1]."""
    if max_hp <= 0:
        return 0.0
    return max(0.0, min(1.0, hp / max_hp))


def health_color(hp: int, max_hp: int) -> Tuple[int, int, int]:
    """Pick a green→yellow→red color for the bar fill.

    Above 60%: green. 30..60%: yellow. Below 30%: red. Fully dead: dark gray.
    """
    r = health_ratio(hp, max_hp)
    if hp <= 0:
        return (60, 60, 60)
    if r > 0.6:
        # Full green
        return (60, 200, 60)
    if r > 0.3:
        # Yellow
        return (220, 200, 50)
    # Red
    return (220, 60, 60)


# -----------------------------------------------------------------------------
# Owner color helper (for minimap/particle tinting)
# -----------------------------------------------------------------------------
PLAYER_COLOR: dict[int, Tuple[int, int, int]] = {
    0: (80, 160, 255),   # player — blue
    1: (220, 60, 60),    # enemy — red
}
DEFAULT_COLOR: Tuple[int, int, int] = (200, 200, 200)


def owner_color(owner_id: int) -> Tuple[int, int, int]:
    return PLAYER_COLOR.get(owner_id, DEFAULT_COLOR)
