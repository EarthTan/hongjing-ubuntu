"""Control groups for MVP-5 (Ctrl+<digit> to assign, <digit> to recall).

Pure data; no pygame. Holds up to 9 slots (1..9). A slot stores a snapshot of
unit indices into ``PlayerState.units`` at assignment time. Recalling re-runs
the box-select-style helper ``select_units``.

Note: the snapshot is by *index* — if a unit dies and shifts the list, the
slot will reference the wrong unit (or get auto-pruned). For MVP-5 simplicity
this is acceptable; MVP-7 can upgrade to id-based references if it matters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .buildings import PlayerState
from .selection import SelectionState
from .units import Unit, ensure_units


SLOTS = 9  # 1..9


@dataclass
class ControlGroups:
    assigned: Dict[int, List[int]] = field(default_factory=dict)

    def assign(self, slot: int, unit_indices: List[int]) -> None:
        if not 1 <= slot <= SLOTS:
            return
        # Dedupe + sort, drop any that are out of bounds at assignment time.
        self.assigned[slot] = sorted(set(unit_indices))

    def clear(self, slot: int) -> None:
        self.assigned.pop(slot, None)

    def recall(self, slot: int, player: PlayerState, selection: SelectionState) -> int:
        """Set ``selection.selected_unit_ids`` to the slot's snapshot.
        Out-of-bounds indices are silently dropped. Returns count actually selected."""
        selection.clear_units()
        indices = self.assigned.get(slot, [])
        units = ensure_units(player)
        valid = [i for i in indices if 0 <= i < len(units)]
        selection.select_units(valid)
        return len(valid)

    def add_recall(self, slot: int, player: PlayerState, selection: SelectionState) -> int:
        """Append (Ctrl+Shift+digit style) the slot's units to current selection."""
        indices = self.assigned.get(slot, [])
        units = ensure_units(player)
        valid = [i for i in indices if 0 <= i < len(units)]
        selection.add_units(valid)
        return len(valid)
