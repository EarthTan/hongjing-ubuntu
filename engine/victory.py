"""Win/Loss detection and game-over screen.

MVP-9: the match ends the moment one side's Construction Yard is destroyed.
The player (id 0) loses when their yard is gone; the AI (id != 0) loses when
its yard is gone. We expose a tiny pure-logic API (compute_game_result) and
a pygame-based draw helper (draw_game_over) so the test suite can verify the
state machine without touching the display.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, List

try:
    import pygame  # type: ignore
except Exception:  # pragma: no cover - headless paths
    pygame = None  # type: ignore

from .buildings import BuildingKind, PlayerState

if TYPE_CHECKING:
    from .world import World


class GameResult(str, Enum):
    ONGOING = "ongoing"
    VICTORY = "victory"
    DEFEAT = "defeat"


# Player id 0 is the human; everyone else is the AI.
PLAYER_ID = 0


def has_yard(player: PlayerState) -> bool:
    """True if this player still has at least one alive Construction Yard."""
    return any(
        b.kind == BuildingKind.CONSTRUCTION_YARD and not b.is_dead
        for b in player.buildings
    )


def compute_game_result(players: List[PlayerState]) -> GameResult:
    """Derive the current game result from the player roster.

    Rules:
      * If the human (id 0) is missing or has no Construction Yard → DEFEAT.
      * If every non-human player has no Construction Yard → VICTORY.
      * Otherwise → ONGOING.

    The "no AI alive" case is rare (we only ship one AI by default) but the
    general check is "all opponents are yard-less", which extends cleanly
    if the user adds more AIs later.
    """
    human = next((p for p in players if p.id == PLAYER_ID), None)
    if human is None or not has_yard(human):
        return GameResult.DEFEAT
    opponents = [p for p in players if p.id != PLAYER_ID]
    if opponents and all(not has_yard(p) for p in opponents):
        return GameResult.VICTORY
    return GameResult.ONGOING


def check_victory(world: "World") -> GameResult:
    """Convenience wrapper that pulls players off a World and computes result.

    Also stamps `world.game_result` for downstream readers (HUD, AI, etc.).
    """
    result = compute_game_result(world.players)
    world.game_result = result
    return result


def is_terminal(result: GameResult) -> bool:
    return result in (GameResult.VICTORY, GameResult.DEFEAT)


# -----------------------------------------------------------------------------
# Display
# -----------------------------------------------------------------------------
def draw_game_over(
    surface: "pygame.Surface",
    result: GameResult,
) -> None:
    """Draw the full-screen victory/defeat overlay.

    Safe to call when pygame is None (headless); silently no-ops.
    """
    if pygame is None or result == GameResult.ONGOING:
        return
    sw, sh = surface.get_size()
    # Dim the world
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    surface.blit(overlay, (0, 0))
    # Title
    if result == GameResult.VICTORY:
        title_text = "VICTORY"
        title_color = (255, 230, 80)
    else:
        title_text = "DEFEAT"
        title_color = (255, 80, 80)
    title_font = pygame.font.SysFont("arial", 96, bold=True)
    title = title_font.render(title_text, True, title_color)
    surface.blit(title, (sw // 2 - title.get_width() // 2, sh // 3))
    # Subtitle
    sub_font = pygame.font.SysFont("arial", 28)
    sub = sub_font.render("Press ESC or click to return to menu", True, (220, 220, 220))
    surface.blit(sub, (sw // 2 - sub.get_width() // 2, sh // 2 + 20))
