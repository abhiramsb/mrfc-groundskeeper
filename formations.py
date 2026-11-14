"""Formation definitions.

Each slot is (key, label, x, y):
  key   - unique within a formation, stored in the DB
  label - short position code shown on the pitch
  x, y  - 0..1 on the pitch. x: 0 = left touchline, 1 = right.
          y: 0 = opponent goal (top), 1 = own goal (bottom).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    x: float
    y: float


def _row(y: float, specs: list[tuple[str, str]], xs: list[float]) -> list[Slot]:
    return [Slot(k, l, x, y) for (k, l), x in zip(specs, xs)]


def _spread(n: int, margin: float = 0.14) -> list[float]:
    if n == 1:
        return [0.5]
    step = (1 - 2 * margin) / (n - 1)
    return [margin + i * step for i in range(n)]


GK = [Slot("GK", "GK", 0.5, 0.92)]

FORMATIONS: dict[str, list[Slot]] = {
    "4-4-2": GK
    + _row(0.74, [("LB", "LB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "RB")], [0.14, 0.38, 0.62, 0.86])
    + _row(0.50, [("LM", "LM"), ("LCM", "CM"), ("RCM", "CM"), ("RM", "RM")], [0.12, 0.38, 0.62, 0.88])
    + _row(0.20, [("LST", "ST"), ("RST", "ST")], [0.36, 0.64]),
    "4-3-3": GK
    + _row(0.74, [("LB", "LB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "RB")], [0.14, 0.38, 0.62, 0.86])
    + _row(0.50, [("LCM", "CM"), ("CM", "CM"), ("RCM", "CM")], [0.26, 0.5, 0.74])
    + _row(0.20, [("LW", "LW"), ("ST", "ST"), ("RW", "RW")], [0.14, 0.5, 0.86]),
    "4-2-3-1": GK
    + _row(0.76, [("LB", "LB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "RB")], [0.14, 0.38, 0.62, 0.86])
    + _row(0.60, [("LDM", "CDM"), ("RDM", "CDM")], [0.36, 0.64])
    + _row(0.40, [("LM", "LM"), ("CAM", "CAM"), ("RM", "RM")], [0.14, 0.5, 0.86])
    + _row(0.17, [("ST", "ST")], [0.5]),
    "4-1-2-1-2": GK
    + _row(0.76, [("LB", "LB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "RB")], [0.14, 0.38, 0.62, 0.86])
    + _row(0.62, [("CDM", "CDM")], [0.5])
    + _row(0.48, [("LM", "LM"), ("RM", "RM")], [0.16, 0.84])
    + _row(0.35, [("CAM", "CAM")], [0.5])
    + _row(0.18, [("LST", "ST"), ("RST", "ST")], [0.36, 0.64]),
    "4-5-1": GK
    + _row(0.76, [("LB", "LB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "RB")], [0.14, 0.38, 0.62, 0.86])
    + _row(0.48, [("LM", "LM"), ("LCM", "CM"), ("CM", "CM"), ("RCM", "CM"), ("RM", "RM")], _spread(5, 0.1))
    + _row(0.17, [("ST", "ST")], [0.5]),
    "3-5-2": GK
    + _row(0.76, [("LCB", "CB"), ("CB", "CB"), ("RCB", "CB")], [0.24, 0.5, 0.76])
    + _row(0.48, [("LWB", "LWB"), ("LCM", "CM"), ("CM", "CM"), ("RCM", "CM"), ("RWB", "RWB")], _spread(5, 0.1))
    + _row(0.20, [("LST", "ST"), ("RST", "ST")], [0.36, 0.64]),
    "3-4-3": GK
    + _row(0.76, [("LCB", "CB"), ("CB", "CB"), ("RCB", "CB")], [0.24, 0.5, 0.76])
    + _row(0.52, [("LM", "LM"), ("LCM", "CM"), ("RCM", "CM"), ("RM", "RM")], [0.12, 0.38, 0.62, 0.88])
    + _row(0.20, [("LW", "LW"), ("ST", "ST"), ("RW", "RW")], [0.14, 0.5, 0.86]),
    "5-3-2": GK
    + _row(0.76, [("LWB", "LWB"), ("LCB", "CB"), ("CB", "CB"), ("RCB", "CB"), ("RWB", "RWB")], _spread(5, 0.1))
    + _row(0.50, [("LCM", "CM"), ("CM", "CM"), ("RCM", "CM")], [0.26, 0.5, 0.74])
    + _row(0.20, [("LST", "ST"), ("RST", "ST")], [0.36, 0.64]),
}

for _name, _slots in FORMATIONS.items():
    assert len(_slots) == 11, _name
    assert len({s.key for s in _slots}) == 11, _name

DEFAULT_FORMATION = "4-3-3"


def slots_for(formation: str) -> list[Slot]:
    return FORMATIONS[formation]


def slot_map(formation: str) -> dict[str, Slot]:
    return {s.key: s for s in FORMATIONS[formation]}
