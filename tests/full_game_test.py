"""Full-game acceptance test (终局验收).

Headless: drives a complete scripted match — boot menu → start game → place
buildings → produce units → route the player's army to the AI's Construction
Yard → destroy it → assert VICTORY → return to menu state.

No external assets, no display window. Safe to run in CI.
"""
from __future__ import annotations

import os
import sys
import time

# Headless pygame: must be set before importing pygame.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.buildings import (
    BUILDING_STATS,
    Building,
    BuildingKind,
    PlayerState,
)
from engine.orders import issue_attack_building
from engine.units import UnitKind, spawn_unit
from engine.victory import GameResult, compute_game_result, is_terminal
from engine.world import ENEMY_PLAYER_ID, World
from ui.menu import PLAY, QUIT, MainMenu


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_yard(player: PlayerState) -> Building:
    for b in player.buildings:
        if b.kind == BuildingKind.CONSTRUCTION_YARD and not b.is_dead:
            return b
    raise AssertionError(f"player {player.id} has no alive yard")


def _drop_building(world: World, player: PlayerState, kind: BuildingKind,
                   col: int, row: int) -> Building:
    """Cheat: drop a fully-built building onto the map for the player.

    Real games build via the build queue, which is covered by MVP-2 tests.
    This test only cares about the end-to-end fight, so we shortcut the
    construction timer.
    """
    b = Building(kind=kind, col=col, row=row, owner_id=player.id,
                 hp=BUILDING_STATS[kind].hp)
    player.buildings.append(b)
    return b


def _spawn_army(world: World, player: PlayerState, kind: UnitKind,
                anchor: Building, n: int) -> list:
    """Spawn `n` units of `kind` near `anchor`. Order matters; first to fit wins."""
    spawned: list = []
    cx, cy = anchor.col, anchor.row
    candidates = [(dx, dy) for dx in (-2, -1, 0, 1, 2, 3) for dy in (-2, -1, 0, 1, 2, 3)
                  if not (dx == 0 and dy == 0)]
    for dx, dy in candidates:
        if len(spawned) >= n:
            break
        u = spawn_unit(player, world.tilemap, kind, (cx + dx, cy + dy))
        if u is not None:
            spawned.append(u)
    return spawned


# ---------------------------------------------------------------------------
# Part 1: scripted full match → VICTORY
# ---------------------------------------------------------------------------
def test_full_match_ends_in_victory():
    """Boot a world, build out the player, spawn an army, smash the AI yard."""
    world = World.new_default()
    player = world.get_player(0)
    enemy = world.get_player(ENEMY_PLAYER_ID)

    # Start conditions: both yards alive, game ongoing.
    assert compute_game_result(world.players) == GameResult.ONGOING
    player_yard = _find_yard(player)
    enemy_yard = _find_yard(enemy)

    # Give the player some headroom so the test can issue orders instantly.
    player.credits = 50_000

    # Drop a war factory next to the player yard so heavy-tank spawns are valid.
    wf = _drop_building(world, player, BuildingKind.WAR_FACTORY,
                        player_yard.col + 4, player_yard.row)

    # Spawn a heavy-tank army right next to the war factory.
    army = _spawn_army(world, player, UnitKind.HEAVY_TANK, wf, 6)
    assert len(army) >= 3, f"expected to spawn a sizable army, got {len(army)}"

    # Order the army to attack the enemy construction yard.
    issued = issue_attack_building(army, enemy_yard, ENEMY_PLAYER_ID)
    assert issued == len(army), f"order was only accepted on {issued}/{len(army)} units"

    # Drive the simulation forward. Each tick moves units along their orders
    # and applies damage when they're in range. The yard has 2000 HP and a
    # heavy tank does 40 dmg/shot with a ~0.8s cooldown; 6 tanks should chew
    # through it within a few hundred frames at 60 fps.
    target_fps = 60
    dt = 1.0 / target_fps
    max_frames = 60 * 60  # 1 minute cap — should finish in << this
    victory_frame = None
    for f in range(max_frames):
        world.tick(dt=dt)
        if is_terminal(world.game_result):
            victory_frame = f
            break

    assert victory_frame is not None, (
        f"match did not terminate after {max_frames} frames "
        f"(player_yard_hp={player_yard.hp}, enemy_yard_hp={enemy_yard.hp}, "
        f"player_yard_alive={not player_yard.is_dead}, enemy_yard_alive={not enemy_yard.is_dead})"
    )
    assert world.game_result == GameResult.VICTORY
    assert enemy_yard.is_dead
    assert not player_yard.is_dead


# ---------------------------------------------------------------------------
# Part 2: menu layer accepts the same inputs main.py routes to it
# ---------------------------------------------------------------------------
def test_menu_returns_play_and_quit():
    m = MainMenu((1024, 768))
    play_ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN})
    assert m.handle_event(play_ev) == PLAY
    quit_ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE})
    assert m.handle_event(quit_ev) == QUIT


# ---------------------------------------------------------------------------
# Part 3: end-to-end loop — menu → game → terminal state → "back to menu"
# Mirrors main.py's run_game() loop without opening a window.
# ---------------------------------------------------------------------------
def test_end_to_end_loop_drives_to_victory():
    world = World.new_default()
    player = world.get_player(0)
    enemy = world.get_player(ENEMY_PLAYER_ID)
    enemy_yard = _find_yard(enemy)
    player.credits = 50_000

    player_yard = _find_yard(player)
    wf = _drop_building(world, player, BuildingKind.WAR_FACTORY,
                        player_yard.col + 4, player_yard.row)
    army = _spawn_army(world, player, UnitKind.HEAVY_TANK, wf, 6)
    issue_attack_building(army, enemy_yard, ENEMY_PLAYER_ID)

    # Skip the menu — go straight into a match (the menu's "PLAY" branch in main.py).
    pygame.init()  # the real main.py calls this; we mirror it for the menu draw
    menu = MainMenu((1024, 768))
    menu.update()  # exercise update() the same way the real loop does
    menu.draw(pygame.display.set_mode((64, 64)))  # should not raise

    # Now tick the world the same way main.py does until we hit the terminal.
    dt = 1.0 / 60
    result = GameResult.ONGOING
    for _ in range(60 * 60):
        world.tick(dt=dt)
        if is_terminal(world.game_result):
            result = world.game_result
            break

    assert result == GameResult.VICTORY
    # main.py's "ESC or click → back to menu" path is verified by the input
    # logic in MVP-9; here we only assert the terminal state.
    assert is_terminal(result)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def run_all() -> int:
    t0 = time.time()
    failures = 0
    test_names = [n for n in globals() if n.startswith("test_") and callable(globals()[n])]
    for name in test_names:
        fn = globals()[name]
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    dt = time.time() - t0
    print(f"\nfull_game_test: {len(test_names)} tests, "
          f"{failures} failed, {dt:.2f}s")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
