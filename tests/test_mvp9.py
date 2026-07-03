"""MVP-9 tests — Win/Loss detection.

Exercises:
  * Initial state: ONGOING.
  * Killing the player's yard flips to DEFEAT (and tick stamps it).
  * Killing the AI's yard flips to VICTORY.
  * Killing a non-yard building does not end the game.
  * Killing every yard in a multi-AI setup still yields VICTORY.
  * draw_game_over is a no-op when ONGOING, and never crashes under dummy SDL.
  * When a yard dies mid-tick via a damage hook, the next tick stamps the result.
  * Human player missing entirely is treated as DEFEAT.
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.buildings import BuildingKind, PlayerState, place_building
from engine.render import init_display
from engine.settings import DEFAULT_WINDOW_H, DEFAULT_WINDOW_W
from engine.tilemap import generate_default_map
from engine.victory import (
    GameResult,
    PLAYER_ID,
    check_victory,
    compute_game_result,
    draw_game_over,
    has_yard,
    is_terminal,
)
from engine.world import ENEMY_PLAYER_ID, World


# -----------------------------------------------------------------------------
# Pure-logic tests
# -----------------------------------------------------------------------------
def test_initial_state_is_ongoing():
    w = World.new_default()
    assert w.game_result == GameResult.ONGOING
    assert check_victory(w) == GameResult.ONGOING


def test_has_yard_true_with_yard():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=5000)
    place_building(tm, [p], 0, BuildingKind.CONSTRUCTION_YARD, 5, 5)
    assert has_yard(p) is True


def test_has_yard_false_when_yard_dead():
    tm = generate_default_map(64, 64, seed=1)
    p = PlayerState(id=0, credits=5000)
    place_building(tm, [p], 0, BuildingKind.CONSTRUCTION_YARD, 5, 5)
    yard = next(b for b in p.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    yard.hp = 0
    assert has_yard(p) is False


def test_has_yard_false_when_no_yard_at_all():
    p = PlayerState(id=0, credits=5000)
    assert has_yard(p) is False


def test_player_yard_killed_yields_defeat():
    w = World.new_default()
    p0 = w.get_player(0)
    yard = next(b for b in p0.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    yard.hp = 0
    assert compute_game_result(w.players) == GameResult.DEFEAT
    # check_victory stamps world state
    assert check_victory(w) == GameResult.DEFEAT
    assert w.game_result == GameResult.DEFEAT


def test_ai_yard_killed_yields_victory():
    w = World.new_default()
    p1 = w.get_player(ENEMY_PLAYER_ID)
    yard = next(b for b in p1.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    yard.hp = 0
    assert compute_game_result(w.players) == GameResult.VICTORY
    assert check_victory(w) == GameResult.VICTORY


def test_killing_non_yard_does_not_end_game():
    w = World.new_default()
    # Add a non-yard building to the player (place_building handles cost).
    tm = w.tilemap
    p0 = w.get_player(0)
    place_building(tm, w.players, 0, BuildingKind.POWER_PLANT, 8, 8)
    pp = next(b for b in p0.buildings if b.kind == BuildingKind.POWER_PLANT)
    pp.hp = 0
    assert compute_game_result(w.players) == GameResult.ONGOING


def test_both_yards_dead_is_defeat_for_human():
    # When both sides lose their yards in the same tick, the human is
    # checked first; the player loses by rule priority.
    w = World.new_default()
    p0 = w.get_player(0)
    p1 = w.get_player(ENEMY_PLAYER_ID)
    p0_yard = next(b for b in p0.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    p1_yard = next(b for b in p1.buildings if b.kind == BuildingKind.CONSTRUCTION_YARD)
    p0_yard.hp = 0
    p1_yard.hp = 0
    assert compute_game_result(w.players) == GameResult.DEFEAT


def test_multi_ai_victory_when_every_opponent_yard_dead():
    # Build a tiny synthetic roster: human + 2 AIs; both AIs lose their yards.
    tm = generate_default_map(64, 64, seed=1)
    players = []
    p0 = PlayerState(id=0, credits=5000)
    place_building(tm, [p0], 0, BuildingKind.CONSTRUCTION_YARD, 5, 5)
    players.append(p0)
    p1 = PlayerState(id=1, credits=5000)
    players.append(p1)
    place_building(tm, players, 1, BuildingKind.CONSTRUCTION_YARD, 20, 5)
    p2 = PlayerState(id=2, credits=5000)
    players.append(p2)
    place_building(tm, players, 2, BuildingKind.CONSTRUCTION_YARD, 5, 20)
    # Both AI yards die
    players[1].buildings[0].hp = 0
    players[2].buildings[0].hp = 0
    assert compute_game_result(players) == GameResult.VICTORY


def test_human_missing_is_defeat():
    # Edge case: roster only has AI players — human is absent.
    tm = generate_default_map(64, 64, seed=1)
    p1 = PlayerState(id=1, credits=5000)
    place_building(tm, [p1], 1, BuildingKind.CONSTRUCTION_YARD, 20, 5)
    # Human id=0 is missing entirely.
    assert compute_game_result([p1]) == GameResult.DEFEAT


def test_check_victory_persists_into_world():
    w = World.new_default()
    assert w.game_result == GameResult.ONGOING
    p1 = w.get_player(ENEMY_PLAYER_ID)
    p1.buildings[0].hp = 0
    check_victory(w)
    assert w.game_result == GameResult.VICTORY
    # Calling check_victory again is idempotent.
    assert check_victory(w) == GameResult.VICTORY


# -----------------------------------------------------------------------------
# Tick integration: game_result auto-updates each tick
# -----------------------------------------------------------------------------
def test_world_tick_propagates_defeat_after_yard_killed():
    w = World.new_default()
    p0 = w.get_player(0)
    p0.buildings[0].hp = 0  # kill the yard
    # The yard's hp==0 makes is_dead True; remove_dead will not delete a
    # building (only units), so the dead yard lingers but has_yard() returns False.
    w.tick(dt=0.1)
    assert w.game_result == GameResult.DEFEAT


def test_world_tick_propagates_victory_after_ai_yard_killed():
    w = World.new_default()
    p1 = w.get_player(ENEMY_PLAYER_ID)
    p1.buildings[0].hp = 0
    w.tick(dt=0.1)
    assert w.game_result == GameResult.VICTORY


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------
def test_draw_game_over_no_op_when_ongoing():
    pygame.init()
    screen = init_display(DEFAULT_WINDOW_W, DEFAULT_WINDOW_H, "mvp9-ongoing")
    # Should not raise, should not paint anything.
    draw_game_over(screen, GameResult.ONGOING)
    pygame.quit()


def test_draw_game_over_victory_does_not_crash():
    pygame.init()
    screen = init_display(DEFAULT_WINDOW_W, DEFAULT_WINDOW_H, "mvp9-victory")
    draw_game_over(screen, GameResult.VICTORY)
    pygame.quit()


def test_draw_game_over_defeat_does_not_crash():
    pygame.init()
    screen = init_display(DEFAULT_WINDOW_W, DEFAULT_WINDOW_H, "mvp9-defeat")
    draw_game_over(screen, GameResult.DEFEAT)
    pygame.quit()


# -----------------------------------------------------------------------------
# is_terminal helper
# -----------------------------------------------------------------------------
def test_is_terminal_flags_victory_and_defeat_only():
    assert is_terminal(GameResult.VICTORY) is True
    assert is_terminal(GameResult.DEFEAT) is True
    assert is_terminal(GameResult.ONGOING) is False


# -----------------------------------------------------------------------------
# PLAYER_ID constant sanity
# -----------------------------------------------------------------------------
def test_player_id_constant_is_zero():
    assert PLAYER_ID == 0
