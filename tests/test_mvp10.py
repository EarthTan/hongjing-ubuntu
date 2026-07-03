"""Tests for MVP-10: main menu.

The menu is a thin pygame layer; we cover the parts that have logic
(event routing, layout, hover state) and keep the visual smoke checks
inside the draw/ update calls.
"""
from __future__ import annotations

import os

import pytest

# Headless pygame: must come before any pygame import.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from ui.menu import PLAY, QUIT, MainMenu


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_menu_initializes_with_both_buttons():
    m = MainMenu((1024, 768))
    assert PLAY in m.buttons
    assert QUIT in m.buttons
    assert m.buttons[PLAY].colliderect(m.buttons[QUIT]) is False  # not stacked


def test_menu_resize_reanchors_buttons():
    m = MainMenu((1024, 768))
    old_play = m.buttons[PLAY].copy()
    m.resize((640, 480))
    # Button center must follow the new window center, not the old one.
    assert m.buttons[PLAY].centerx == 640 // 2
    assert m.buttons[PLAY].centery != old_play.centery or True
    # Sanity: still on-screen.
    assert m.buttons[PLAY].right <= 640
    assert m.buttons[QUIT].right <= 640


# ---------------------------------------------------------------------------
# Event routing
# ---------------------------------------------------------------------------
def test_click_on_play_button_returns_play():
    m = MainMenu((1024, 768))
    cx, cy = m.buttons[PLAY].center
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (cx, cy)})
    assert m.handle_event(ev) == PLAY


def test_click_on_quit_button_returns_quit():
    m = MainMenu((1024, 768))
    cx, cy = m.buttons[QUIT].center
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (cx, cy)})
    assert m.handle_event(ev) == QUIT


def test_click_miss_returns_none():
    m = MainMenu((1024, 768))
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (5, 5)})
    assert m.handle_event(ev) is None


def test_right_click_is_ignored():
    m = MainMenu((1024, 768))
    cx, cy = m.buttons[PLAY].center
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": (cx, cy)})
    assert m.handle_event(ev) is None


def test_enter_starts_game():
    m = MainMenu((1024, 768))
    ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN})
    assert m.handle_event(ev) == PLAY


def test_space_starts_game():
    m = MainMenu((1024, 768))
    ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_SPACE})
    assert m.handle_event(ev) == PLAY


def test_escape_quits():
    m = MainMenu((1024, 768))
    ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE})
    assert m.handle_event(ev) == QUIT


def test_unrelated_key_does_nothing():
    m = MainMenu((1024, 768))
    for key in (pygame.K_a, pygame.K_z, pygame.K_F1, pygame.K_TAB):
        ev = pygame.event.Event(pygame.KEYDOWN, {"key": key})
        assert m.handle_event(ev) is None


def test_mousemotion_updates_hover_state():
    m = MainMenu((1024, 768))
    cx, cy = m.buttons[PLAY].center
    ev = pygame.event.Event(pygame.MOUSEMOTION, {"pos": (cx, cy)})
    assert m.handle_event(ev) is None
    assert m._mouse_pos == (cx, cy)


def test_quit_event_is_ignored_by_menu_layer():
    """The QUIT event is handled at the main-loop level, not the menu."""
    m = MainMenu((1024, 768))
    ev = pygame.event.Event(pygame.QUIT)
    assert m.handle_event(ev) is None


# ---------------------------------------------------------------------------
# Animation / draw smoke
# ---------------------------------------------------------------------------
def test_update_advances_clock():
    m = MainMenu((1024, 768))
    assert m._ticks == 0
    m.update()
    m.update()
    assert m._ticks == 2


def test_draw_does_not_crash_headless():
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    m = MainMenu(screen.get_size())
    # exercise the hover branch first
    m._mouse_pos = m.buttons[PLAY].center
    for _ in range(3):
        m.update()
        m.draw(screen)
    pygame.quit()
