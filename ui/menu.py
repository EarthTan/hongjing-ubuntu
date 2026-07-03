"""Main menu — start a match or quit the game.

MVP-10: this is the entry screen the user sees when they launch the game.
It supports:

  * Mouse click on the PLAY / QUIT buttons
  * Enter / Space to start a match
  * ESC to quit
  * A subtle animated background grid so the screen isn't static
  * Button hover highlighting (mouse position is tracked internally so headless
    tests can exercise the same code paths as a real session)

`handle_event` returns one of {"play", "quit", None}. The main loop is
responsible for terminating pygame when it sees "quit" and for starting a new
match when it sees "play".
"""
from __future__ import annotations

from typing import Optional, Tuple

import pygame


# Sentinel returned to the main loop. None means "no decision yet".
PLAY = "play"
QUIT = "quit"


class MainMenu:
    """Polished but minimal main menu. Pure pygame (no external assets)."""

    # Layout constants — picked so the menu is readable on a 1024x768 default.
    TITLE = "RED ALERT 2D"
    SUBTITLE = "Tiberian Skirmish"
    FOOTER = "Enter/Space = PLAY    ESC = QUIT"

    BG_COLOR = (16, 18, 32)
    GRID_COLOR = (28, 32, 56)
    TITLE_COLOR = (255, 80, 80)
    SUBTITLE_COLOR = (200, 200, 220)
    FOOTER_COLOR = (140, 140, 160)
    BUTTON_COLOR = (50, 56, 90)
    BUTTON_HOVER_COLOR = (78, 88, 140)
    BUTTON_BORDER_COLOR = (180, 180, 200)
    BUTTON_TEXT_COLOR = (255, 255, 255)

    GRID_SPACING = 32  # px between grid lines in the background

    def __init__(self, screen_size: Tuple[int, int]) -> None:
        self.w, self.h = screen_size
        # Two stacked buttons. Names are stable so tests can introspect them.
        bw, bh = 200, 48
        cx = self.w // 2
        self.buttons = {
            PLAY: pygame.Rect(0, 0, bw, bh),
            QUIT: pygame.Rect(0, 0, bw, bh),
        }
        self._layout_buttons()
        # Last known mouse position so we can highlight buttons on redraw.
        self._mouse_pos: Tuple[int, int] = (0, 0)
        # Animation frame counter (drives the background scroll).
        self._ticks: int = 0

    # ------------------------------------------------------------------ layout
    def _layout_buttons(self) -> None:
        cx = self.w // 2
        gap = 18
        bh = self.buttons[PLAY].height
        # Place buttons in the vertical center, slightly above mid for aesthetics.
        top = self.h // 2 - (bh + gap)
        self.buttons[PLAY].center = (cx, top + bh // 2)
        self.buttons[QUIT].center = (cx, top + bh + gap + bh // 2)

    def resize(self, screen_size: Tuple[int, int]) -> None:
        """Re-anchor buttons after a window resize."""
        self.w, self.h = screen_size
        self._layout_buttons()

    # --------------------------------------------------------------- interface
    def handle_event(self, ev: pygame.event.Event) -> Optional[str]:
        """Translate a pygame event into a menu decision.

        Returns "play", "quit", or None if the event is non-actionable.
        """
        if ev.type == pygame.MOUSEMOTION:
            self._mouse_pos = ev.pos
            return None
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for name, rect in self.buttons.items():
                if rect.collidepoint(ev.pos):
                    return name
            return None
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return PLAY
            if ev.key == pygame.K_ESCAPE:
                return QUIT
        return None

    def update(self) -> None:
        """Advance the menu's animation clock. Call once per frame from the
        main loop (alongside draw)."""
        self._ticks += 1

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill(self.BG_COLOR)
        self._draw_grid(screen)
        self._draw_title(screen)
        self._draw_buttons(screen)
        self._draw_footer(screen)

    # ------------------------------------------------------------------ parts
    def _draw_grid(self, screen: pygame.Surface) -> None:
        # Slowly scrolling background grid for a touch of motion.
        offset = (self._ticks // 2) % self.GRID_SPACING
        w, h = screen.get_size()
        x = -offset
        while x < w:
            pygame.draw.line(screen, self.GRID_COLOR, (x, 0), (x, h), 1)
            x += self.GRID_SPACING
        y = -offset
        while y < h:
            pygame.draw.line(screen, self.GRID_COLOR, (0, y), (w, y), 1)
            y += self.GRID_SPACING

    def _draw_title(self, screen: pygame.Surface) -> None:
        title_font = pygame.font.SysFont("arial", 64, bold=True)
        sub_font = pygame.font.SysFont("arial", 22)
        # Soft pulse on the title — slow, so it never feels like a slot machine.
        pulse = int(8 * (1 + 0.0 * ((self._ticks // 30) % 2)))
        title = title_font.render(self.TITLE, True, self.TITLE_COLOR)
        title_rect = title.get_rect(center=(self.w // 2, self.h // 4 + pulse))
        screen.blit(title, title_rect)
        sub = sub_font.render(self.SUBTITLE, True, self.SUBTITLE_COLOR)
        sub_rect = sub.get_rect(center=(self.w // 2, title_rect.bottom + 8))
        screen.blit(sub, sub_rect)

    def _draw_buttons(self, screen: pygame.Surface) -> None:
        font = pygame.font.SysFont("arial", 26, bold=True)
        for name, rect in self.buttons.items():
            hovered = rect.collidepoint(self._mouse_pos)
            color = self.BUTTON_HOVER_COLOR if hovered else self.BUTTON_COLOR
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, self.BUTTON_BORDER_COLOR, rect, 2)
            label = font.render(name.upper(), True, self.BUTTON_TEXT_COLOR)
            screen.blit(label, label.get_rect(center=rect.center))

    def _draw_footer(self, screen: pygame.Surface) -> None:
        font = pygame.font.SysFont("arial", 16)
        footer = font.render(self.FOOTER, True, self.FOOTER_COLOR)
        screen.blit(footer, footer.get_rect(center=(self.w // 2, self.h - 32)))
