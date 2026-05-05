#!/usr/bin/env python3
"""Audit harness for the Pillow e-ink renderer.

Renders every (design x palette x state) combination plus a few stress
states (3-digit floor temps, long washer status), then for each layout
cell pixel-scans the 2-px ring immediately outside its declared Box and
fails if any ink there isn't accounted for by a separator rule.

Usage:
    python3 scripts/audit_eink_layout.py [--out DIR] [--debug-outlines]

Exit code 0 if every cell is clean, non-zero (with a list of offenders)
otherwise. Used as the verification step for the rock-solid layout
refactor.
"""
from __future__ import annotations

import argparse
import copy
import os
import sys
from datetime import datetime, timezone
from typing import Iterable, List

# Allow running directly from a fresh checkout.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

from backend.services.eink.ha_client import empty_ha_shape  # noqa: E402
from backend.services.eink.pillow import layout, render_eink_image  # noqa: E402
from backend.services.eink.pillow.draw import Box, assert_box_clean  # noqa: E402


# ── Test data ─────────────────────────────────────────────────────────


def _base_state() -> dict:
    base = empty_ha_shape()
    base["weather"] = {
        "state": "partlycloudy", "temperature": 72, "humidity": 44,
        "windSpeed": 6, "windBearing": 10, "pressure": 30.12, "visibility": 10,
    }
    base["people"] = [
        {"name": "Austin", "state": "home"},
        {"name": "Allison", "state": "not_home"},
    ]
    base["temps"] = {"first": 70, "second": 71, "third": 72,
                     "basement": 68, "outdoor": 72}
    base["climates"] = {
        "radiantMain": {"name": "Main", "mode": "heat", "current": 68,
                        "target": 70, "action": "heating"},
        "radiantApt": {"name": "Apt", "mode": "off", "current": 65,
                       "target": 60, "action": "idle"},
    }
    base["allClimates"] = [
        {"name": "First", "mode": "heat", "current": 70, "target": 72,
         "action": "heating"},
    ]
    base["floorActivity"]["first"] = [base["allClimates"][0]]
    base["sun"] = {
        "state": "above_horizon",
        "nextRising": "2026-05-05T09:34:00+00:00",
        "nextSetting": "2026-05-05T23:47:00+00:00",
    }
    base["pool"] = {
        "operation": "idle", "current": 83, "target": 82, "air": 73,
        "heating": False, "pumpRunning": True, "schedule": True,
        "freezeProtect": False,
    }
    return base


def _sauna_state(base: dict) -> dict:
    out = copy.deepcopy(base)
    out["sauna"] = {
        "mode": "heat", "current": 127, "target": 185, "duration": 60,
        "heaters": 3, "door": False, "roomTemp": 84, "roomHumidity": 19,
    }
    out["washer"] = {
        "status": "rinse", "operation": "cycle",
        "remaining": "2026-05-05T22:45:00+00:00",
        "lastNotification": None, "powerOn": True,
        "cycles": 54, "energyMonth": 12000,
    }
    return out


def _stress_state(base: dict) -> dict:
    """Push every numeric field into 3 digits + every label long. The
    audit shouldn't flag overflow on this either."""
    out = copy.deepcopy(base)
    out["weather"] = {
        "state": "thunderstorm", "temperature": -12,
        "humidity": 100, "windSpeed": 122, "windBearing": 320,
        "pressure": 30.12, "visibility": 100,
    }
    out["temps"] = {"first": 102, "second": 101, "third": 99,
                    "basement": -12, "outdoor": -12}
    out["climates"] = {
        "radiantMain": {"name": "Main", "mode": "heat", "current": 100,
                        "target": 110, "action": "heating"},
        "radiantApt": {"name": "Apt", "mode": "heat", "current": 102,
                       "target": 108, "action": "heating"},
    }
    out["allClimates"] = [
        {"name": "First", "mode": "heat", "current": 100, "target": 110,
         "action": "heating"},
        {"name": "Second", "mode": "heat", "current": 99, "target": 110,
         "action": "heating"},
    ]
    out["sauna"] = {
        "mode": "heat", "current": 175, "target": 199, "duration": 120,
        "heaters": 3, "door": True, "roomTemp": 102, "roomHumidity": 99,
    }
    out["pool"] = {
        "operation": "heating", "current": 88, "target": 95, "air": -12,
        "heating": True, "pumpRunning": True, "schedule": True,
        "freezeProtect": True,
    }
    out["washer"] = {
        "status": "prerinse_extended_with_steam", "operation": "cycle",
        "remaining": "2026-05-05T23:59:00+00:00",
        "lastNotification": None, "powerOn": True,
        "cycles": 999, "energyMonth": 999000,
    }
    return out


# ── Cell catalogues ───────────────────────────────────────────────────


def _swiss_cells() -> List[tuple[str, Box, List[Box]]]:
    """Returns (name, cell_box, allow_outside) for every Swiss region.
    `allow_outside` lists every rectangle that's legitimately allowed
    to contain ink immediately outside the cell -- both the declared
    rule lines AND every other cell's own region (so a heating-inverted
    sauna cell doesn't trip the audit on the pool cell above it)."""
    L = layout.SWISS
    rules = [
        L.header_rule_1, L.header_rule_2, L.header_rule_3,
        L.body_mid_rule, L.hero_divider, L.hero_right_inner_rule,
        L.bottom_rule_left, L.bottom_rule_right, L.bottom_middle_rule,
        L.footer_top_rule, L.footer_rule_1, L.footer_rule_2, L.footer_rule_3,
        L.header_bottom_rule,
    ]
    all_cells = [
        ("header_cell_wordmark", L.header_cell_wordmark),
        ("header_cell_status", L.header_cell_status),
        ("header_cell_active", L.header_cell_active),
        ("header_cell_refresh", L.header_cell_refresh),
        ("hero_left", L.hero_left),
        ("hero_right_time", L.hero_right_time),
        ("hero_right_outside", L.hero_right_outside),
        ("bottom_left", L.bottom_left),
        ("bottom_middle_top", L.bottom_middle_top),
        ("bottom_middle_bottom", L.bottom_middle_bottom),
        ("bottom_right", L.bottom_right),
        ("footer_cell_src", L.footer_cell_src),
        ("footer_cell_status", L.footer_cell_status),
        ("footer_cell_zones", L.footer_cell_zones),
        ("footer_cell_refresh", L.footer_cell_refresh),
    ]
    cell_boxes = [b for _, b in all_cells]
    return [(name, box, rules + [b for b in cell_boxes if b is not box])
            for name, box in all_cells]


def _editorial_cells() -> List[tuple[str, Box, List[Box]]]:
    L = layout.EDITORIAL
    rules = [L.body_left_rule, L.body_right_rule,
             L.masthead_thick_rule, L.masthead_hair_rule,
             L.masthead_pin_rule]
    all_cells = [
        ("masthead", L.masthead),
        ("body_left_rail", L.body_left_rail),
        ("body_lead", L.body_lead),
        ("body_right_rail", L.body_right_rail),
        ("colophon", L.colophon),
    ]
    cell_boxes = [b for _, b in all_cells]
    return [(name, box, rules + [b for b in cell_boxes if b is not box])
            for name, box in all_cells]


# ── Audit ─────────────────────────────────────────────────────────────


def _audit_one(img: Image.Image, name: str, design: str) -> List[str]:
    fails: List[str] = []
    cells = _swiss_cells() if design == "swiss" else _editorial_cells()
    for cell_name, box, allow in cells:
        bad = assert_box_clean(img, box, allow_outside=allow, band=2,
                                ink_threshold=50)
        if bad:
            fails.append(
                f"  {name} :: {cell_name} {box}: "
                f"{len(bad)} stray ink pixels (first 3: {bad[:3]})"
            )
    return fails


def audit() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/eink_audit",
                        help="output directory for rendered PNGs")
    parser.add_argument("--debug-outlines", action="store_true",
                        help="also render with EINK_DEBUG_OUTLINES=1")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    base = _base_state()
    sauna = _sauna_state(base)
    stress = _stress_state(base)

    states = [("calm", base), ("sauna", sauna), ("stress", stress)]
    fails: List[str] = []

    for design in ("editorial", "swiss"):
        for palette in ("six", "bw"):
            for state_name, ha in states:
                img = render_eink_image(
                    design, palette, ha,
                    tz_name="America/New_York", use_cache=False,
                )
                path = os.path.join(
                    args.out, f"{design}_{palette}_{state_name}.png",
                )
                img.save(path)
                tag = f"{design}/{palette}/{state_name}"
                cell_fails = _audit_one(img, tag, design)
                if cell_fails:
                    fails.extend(cell_fails)
                    print(f"FAIL {tag}: {len(cell_fails)} cells overflow")
                else:
                    print(f"  ok {tag}")

    if args.debug_outlines:
        os.environ["EINK_DEBUG_OUTLINES"] = "1"
        # Reload the draw module to pick up the env var.
        import importlib
        from backend.services.eink.pillow import draw as _draw, swiss, editorial
        importlib.reload(_draw)
        importlib.reload(swiss)
        importlib.reload(editorial)
        for design in ("editorial", "swiss"):
            img = render_eink_image(
                design, "six", sauna, tz_name="America/New_York",
                use_cache=False,
            )
            img.save(os.path.join(args.out, f"DEBUG_{design}_sauna.png"))
        print(f"debug-outline renders -> {args.out}/DEBUG_*.png")

    if fails:
        print()
        print(f"OVERFLOWS: {len(fails)}")
        for line in fails:
            print(line)
        return 1
    print()
    print("All cells clean.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
