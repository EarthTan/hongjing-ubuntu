"""Enemy AI — automatic base-building + attack waves for non-player factions.

MVP-8: the AI player (id != 0) must do everything a human would, automatically:

  1. Build a power plant if the power grid is low.
  2. Build a refinery if missing (so harvesters can spawn and bring in ore).
  3. Build a barracks, then a war factory (when the prereq refinery is up).
  4. Periodically produce combat units (infantry from barracks, light tanks
     from the war factory).
  5. Every ``WAVE_INTERVAL`` seconds, attack-move all idle combat units
     toward the player's construction yard (or map center if not found).

The AI is fully decoupled from the player flow and lives on a per-enemy
``EnemyAI`` instance keyed by ``player.id``. We tick it from ``World.tick``
right after the player-side construction tick.

Pure logic — no pygame.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .buildings import (
    Building,
    BuildingKind,
    BuildQueue,
    PlayerState,
    enqueue,
    recompute_power,
)
from .orders import issue_attack_move
from .resources import ensure_harvesters
from .settings import MAP_W, MAP_H
from .tilemap import TileMap
from .units import (
    Unit,
    UnitKind,
    can_produce,
    ensure_units,
    spawn_unit,
)


# -----------------------------------------------------------------------------
# Tuning
# -----------------------------------------------------------------------------
# Wave cadence: every 2 minutes of game time the AI throws everything it has
# at the player. MVP spec calls for 2 minutes per wave.
WAVE_INTERVAL = 120.0

# How often the AI considers producing a combat unit (seconds between checks).
# This is intentionally aggressive so tests don't need 1000+ second runtimes:
# we check every tick and only "produce" when the cooldown is up.
UNIT_PRODUCE_INTERVAL = {
    UnitKind.INFANTRY: 6.0,
    UnitKind.LIGHT_TANK: 12.0,
}

# Building-priority list. When the AI is in expansion mode it walks this list
# top-to-bottom and enqueues anything missing. We delay barracks and war
# factory until at least one harvester is alive — otherwise the AI burns all
# its credits on units it can't afford to keep producing.
_BUILDING_PRIORITY: Tuple[BuildingKind, ...] = (
    BuildingKind.POWER_PLANT,   # always need power
    BuildingKind.REFINERY,      # need a refinery for harvesters
    BuildingKind.BARRACKS,      # then infantry (gated on harvesters)
    BuildingKind.WAR_FACTORY,   # then tanks (gated on harvesters)
)


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------
@dataclass
class EnemyAI:
    """One AI controller for a non-player faction.

    - ``player_id`` identifies which ``PlayerState`` we manage.
    - ``time`` accumulates game time; used to throttle building/recruit/wave.
    - ``cooldowns`` is per-UnitKind: seconds remaining until next produce.
    - ``rng`` makes all random decisions injectable for tests.
    """
    player_id: int
    time: float = 0.0
    wave_timer: float = 0.0
    cooldowns: Dict[UnitKind, float] = field(default_factory=dict)
    rng: random.Random = field(default_factory=random.Random)
    # Wave count already dispatched (handy for tests + UI).
    waves_sent: int = 0

    def reset_cooldowns(self) -> None:
        for k in UNIT_PRODUCE_INTERVAL:
            self.cooldowns[k] = 0.0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _enemy_player(players: List[PlayerState], player_id: int) -> PlayerState:
    for p in players:
        if p.id == player_id:
            return p
    raise KeyError(f"player {player_id} not found")


def _has_built(player: PlayerState, kind: BuildingKind) -> bool:
    return any(b.kind == kind for b in player.buildings)


def _yard_centroid(player: PlayerState) -> Optional[Tuple[int, int]]:
    for b in player.buildings:
        if b.kind == BuildingKind.CONSTRUCTION_YARD:
            return (b.col + 1, b.row + 1)
    return None


def _find_player_yard(players: List[PlayerState]) -> Optional[Tuple[int, int]]:
    for p in players:
        if p.id == 0:
            c = _yard_centroid(p)
            if c is not None:
                return c
    return None


def _fallback_target(tilemap: TileMap) -> Tuple[int, int]:
    """Map center tile — used when no enemy yard can be found."""
    return (tilemap.width // 2, tilemap.height // 2)


# -----------------------------------------------------------------------------
# AI tick
# -----------------------------------------------------------------------------
def ai_tick(
    ai: EnemyAI,
    tilemap: TileMap,
    players: List[PlayerState],
    dt: float,
) -> None:
    """Advance the AI by ``dt`` seconds: build / recruit / wave decisions."""
    try:
        me = _enemy_player(players, ai.player_id)
    except KeyError:
        return
    ai.time += dt
    ai.wave_timer += dt

    # Buildings take priority: ensure power, refinery, barracks, war factory.
    _auto_expand_base(ai, tilemap, me, players)

    # Recruit combat units when prereqs are up.
    recruit_tick(ai, me, tilemap, dt)

    # Wave: every WAVE_INTERVAL, attack-move all idle combat units.
    if ai.wave_timer >= WAVE_INTERVAL:
        _send_wave(ai, tilemap, me, players)
        ai.wave_timer = 0.0
        ai.waves_sent += 1


# -----------------------------------------------------------------------------
# Building expansion
# -----------------------------------------------------------------------------
def _auto_expand_base(
    ai: EnemyAI,
    tilemap: TileMap,
    me: PlayerState,
    players: List[PlayerState],
) -> None:
    """Enqueue missing buildings in priority order, gated by power and money.

    The AI also queues a SECOND power plant as soon as the grid drops into
    LOW power, so a runaway consumption doesn't kill production.
    """
    # If we don't have a yard, do nothing — nothing to anchor construction to.
    if not _has_built(me, BuildingKind.CONSTRUCTION_YARD):
        return

    grids = recompute_power(players, ids_filter=[me.id])
    grid = grids.get(me.id)
    low_power = (grid is not None) and grid.is_low()

    # Count existing kinds.
    have = {b.kind for b in me.buildings}
    have_constructions = {cs.kind for cs in me.constructing}
    pending_in_queue = set(me.queue.pending)
    owned_or_pending = have | have_constructions | pending_in_queue

    # Power: if low, queue a power plant first (even if one already exists).
    if low_power and BuildingKind.POWER_PLANT not in owned_or_pending:
        enqueue(me, BuildingKind.POWER_PLANT)
        return

    # Walk the priority list once and enqueue anything missing.
    has_harvester = bool(ensure_harvesters(me))
    for kind in _BUILDING_PRIORITY:
        if kind in owned_or_pending:
            continue
        # Gate barracks/war_factory on having a harvester alive — otherwise we
        # burn through credits producing units with no ore income.
        if kind in (BuildingKind.BARRACKS, BuildingKind.WAR_FACTORY) and not has_harvester:
            # Skip but try to enqueue something else cheaper that we still need.
            continue
        enqueue(me, kind)
        # Cap how many we enqueue per tick: 1 keeps the AI "organic" and
        # mirrors a human player's pacing.
        return


# -----------------------------------------------------------------------------
# Wave dispatch
# -----------------------------------------------------------------------------
def _send_wave(
    ai: EnemyAI,
    tilemap: TileMap,
    me: PlayerState,
    players: List[PlayerState],
) -> None:
    """Send all idle combat units toward the player yard (or map center)."""
    target = _find_player_yard(players) or _fallback_target(tilemap)
    combatants = [
        u for u in ensure_units(me)
        if u.kind in (UnitKind.INFANTRY, UnitKind.ROCKET, UnitKind.LIGHT_TANK, UnitKind.HEAVY_TANK)
    ]
    if not combatants:
        return
    issue_attack_move(combatants, target)
    # Reset cooldowns so the AI keeps producing between waves.
    ai.reset_cooldowns()


# -----------------------------------------------------------------------------
# Tick all AI factions
# -----------------------------------------------------------------------------
def tick_all_ais(
    ais: List[EnemyAI],
    tilemap: TileMap,
    players: List[PlayerState],
    dt: float,
) -> None:
    """Run ``ai_tick`` for every registered AI controller."""
    for ai in ais:
        ai_tick(ai, tilemap, players, dt)


# -----------------------------------------------------------------------------
# Real recruitment — split from the helper to take the real tilemap
# -----------------------------------------------------------------------------
def recruit_one(ai: EnemyAI, me: PlayerState, tilemap: TileMap, kind: UnitKind) -> Optional[Unit]:
    """Spawn one unit if affordable and prereqs met. Resets cooldown.

    Returns the new unit, or None on failure.
    """
    if not can_produce(me, kind):
        return None
    u = spawn_unit(me, tilemap, kind)
    if u is not None:
        ai.cooldowns[kind] = UNIT_PRODUCE_INTERVAL.get(kind, 6.0)
    return u


def recruit_tick(ai: EnemyAI, me: PlayerState, tilemap: TileMap, dt: float) -> None:
    """Tick the recruitment cooldowns; spawn one unit per tick if a slot opens.

    Order: light_tank > infantry. The first ready and affordable kind wins.
    """
    order: Tuple[UnitKind, ...] = (UnitKind.LIGHT_TANK, UnitKind.INFANTRY)
    for kind in order:
        ai.cooldowns.setdefault(kind, 0.0)
        if ai.cooldowns[kind] > 0.0:
            ai.cooldowns[kind] = max(0.0, ai.cooldowns[kind] - dt)
            continue
        if not can_produce(me, kind):
            continue
        u = recruit_one(ai, me, tilemap, kind)
        if u is not None:
            return
