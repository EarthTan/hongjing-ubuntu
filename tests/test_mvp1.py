"""Tests for MVP-1: tilemap, camera, world."""
from __future__ import annotations

import os

import pytest

# Headless pygame
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine.camera import Camera
from engine.settings import DEFAULT_ZOOM, EDGE_SCROLL_MARGIN, EDGE_SCROLL_SPEED, MAX_ZOOM, MIN_ZOOM, TILE_SIZE, Terrain
from engine.tilemap import TileMap, generate_default_map
from engine.world import World


# ---------------------------------------------------------------------------
# TileMap
# ---------------------------------------------------------------------------
def test_tilemap_default_is_grass_with_water_and_ore():
    tm = generate_default_map(64, 64, seed=1)
    assert tm.width == 64 and tm.height == 64
    assert tm.count(Terrain.WATER) > 0, "expected a lake"
    assert tm.count(Terrain.ORE) > 0, "expected ore patches"


def test_tilemap_walkability():
    tm = TileMap(4, 4, tiles=[[0] * 4 for _ in range(4)])
    assert tm.is_walkable(0, 0)
    tm.set(1, 1, Terrain.WATER)
    assert not tm.is_walkable(1, 1)
    assert not tm.is_walkable(99, 99), "OOB should be unwalkable"


def test_tilemap_ore_patches_in_quadrants():
    """Default map should have ore in all four quadrants so the player has a chance."""
    tm = generate_default_map(64, 64, seed=1)
    quadrants = [
        (16, 16),  # NW
        (48, 16),  # NE
        (16, 48),  # SW
        (48, 48),  # SE
    ]
    for qx, qy in quadrants:
        assert tm.ore_within(qx, qy, 12), f"no ore near ({qx},{qy})"


def test_tilemap_player_and_enemy_base_spots_clear():
    """Default map should clear small grass patches for the two construction yards."""
    tm = generate_default_map(64, 64, seed=1)
    for r in range(3, 8):
        for c in range(3, 8):
            assert tm.get(c, r) == Terrain.GRASS
    for r in range(64 - 8, 64 - 3):
        for c in range(64 - 8, 64 - 3):
            assert tm.get(c, r) == Terrain.GRASS


def test_tilemap_deterministic_with_seed():
    a = generate_default_map(64, 64, seed=42)
    b = generate_default_map(64, 64, seed=42)
    for r in range(64):
        for c in range(64):
            assert a.get(c, r) == b.get(c, r)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
def test_camera_default_position_is_map_centre():
    cam = Camera(64, 64, 1024, 768)
    cx, cy = cam.cx, cam.cy
    assert abs(cx - 64 * TILE_SIZE / 2) < 1
    assert abs(cy - 64 * TILE_SIZE / 2) < 1


def test_camera_world_to_screen_and_back():
    cam = Camera(64, 64, 1024, 768)
    sx, sy = cam.world_to_screen(0, 0)
    wx, wy = cam.screen_to_world(sx, sy)
    assert abs(wx) < 1 and abs(wy) < 1


def test_camera_zoom_clamped():
    cam = Camera(64, 64, 1024, 768)
    cam.set_zoom(-5.0)
    assert cam.zoom == MIN_ZOOM
    cam.set_zoom(99.0)
    assert cam.zoom == MAX_ZOOM


def test_camera_move_clamps_to_map():
    cam = Camera(64, 64, 1024, 768)
    cam.move(1_000_000, 1_000_000)
    x, y, w, h = cam.visible_world_rect()
    assert x >= 0
    assert y >= 0
    assert x + w <= 64 * TILE_SIZE
    assert y + h <= 64 * TILE_SIZE


def test_camera_edge_scroll_left_moves_cam_left():
    cam = Camera(64, 64, 1024, 768)
    cam.set_zoom(1.0)
    # Make sure we start away from the left edge so the move registers
    cam.cx = cam.map_w_px / 2
    cam.cy = cam.map_h_px / 2
    start_cx = cam.cx
    cam.update_edge_scroll(mouse_x=0, mouse_y=cam.screen_h // 2, is_window_focused=True)
    assert cam.cx < start_cx


def test_camera_edge_scroll_right_moves_cam_right():
    cam = Camera(64, 64, 1024, 768)
    cam.set_zoom(1.0)
    cam.cx = cam.map_w_px / 2
    cam.cy = cam.map_h_px / 2
    start_cx = cam.cx
    cam.update_edge_scroll(mouse_x=cam.screen_w - 1, mouse_y=cam.screen_h // 2, is_window_focused=True)
    assert cam.cx > start_cx


def test_camera_edge_scroll_centre_does_nothing():
    cam = Camera(64, 64, 1024, 768)
    cam.set_zoom(1.0)
    cam.cx = cam.map_w_px / 2
    cam.cy = cam.map_h_px / 2
    start = (cam.cx, cam.cy)
    cam.update_edge_scroll(mouse_x=cam.screen_w // 2, mouse_y=cam.screen_h // 2, is_window_focused=True)
    assert (cam.cx, cam.cy) == start


def test_camera_unfocused_no_scroll():
    cam = Camera(64, 64, 1024, 768)
    cam.set_zoom(1.0)
    cam.cx = cam.map_w_px / 2
    cam.cy = cam.map_h_px / 2
    start = (cam.cx, cam.cy)
    cam.update_edge_scroll(mouse_x=0, mouse_y=0, is_window_focused=False)
    assert (cam.cx, cam.cy) == start


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------
def test_world_default_builds():
    w = World.new_default(64, 64, 1024, 768, seed=1)
    assert w.tilemap.width == 64
    assert w.camera.screen_w == 1024


def test_world_resize_updates_camera():
    w = World.new_default(64, 64, 1024, 768, seed=1)
    w.resize(800, 600)
    assert w.camera.screen_w == 800
    assert w.camera.screen_h == 600
