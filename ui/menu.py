"""Main menu placeholder. Final implementation lands in MVP-10; the loop is
just enough here so the entrypoint runs."""
from __future__ import annotations

from typing import Tuple

import pygame


class MainMenu:
    def __init__(self, screen_size: Tuple[int, int]) -> None:
        self.w, self.h = screen_size
        self.buttons = {
            "play": pygame.Rect(self.w // 2 - 80, self.h // 2 - 30, 160, 40),
            "quit": pygame.Rect(self.w // 2 - 80, self.h // 2 + 30, 160, 40),
        }

    def handle_event(self, ev: pygame.event.Event) -> str | None:
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.buttons["play"].collidepoint(ev.pos):
                return "play"
            if self.buttons["quit"].collidepoint(ev.pos):
                return "quit"
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return "play"
            if ev.key == pygame.K_ESCAPE:
                return "quit"
        return None

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill((20, 20, 40))
        font = pygame.font.SysFont("arial", 36, bold=True)
        title = font.render("RED ALERT 2D", True, (255, 80, 80))
        screen.blit(title, (self.w // 2 - title.get_width() // 2, self.h // 3))
        bf = pygame.font.SysFont("arial", 22)
        for name, rect in self.buttons.items():
            pygame.draw.rect(screen, (60, 60, 90), rect)
            pygame.draw.rect(screen, (180, 180, 200), rect, 2)
            label = bf.render(name.upper(), True, (255, 255, 255))
            screen.blit(label, (rect.centerx - label.get_width() // 2, rect.centery - label.get_height() // 2))
