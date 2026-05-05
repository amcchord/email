"""Swiss / Modular dashboard -- Pillow port of docs/design/swiss.jsx.

Built on top of the layout primitives in [`draw.py`](draw.py): every cell
is composed as a VStack of declarative rows whose heights add up to the
cell's Box. Display digits go through `draw_fit_text_bl` so a 3-digit
temperature or a long-state status never overflows its column.

Architecture
------------
This renderer is pure presentation. It never touches raw HA dicts and
never re-formats a HA timestamp. All state comes from typed views:

* HVAC reads ``FloorView`` / ``ZoneView`` / ``HvacSummary`` from
  ``ha_view.py``. These reconcile ``mode`` + ``hvac_action`` so a stale
  HA action can never label a cooling zone as "heating".
* Appliances read ``ApplianceView`` (built by the registry in
  ``appliances.py``). All clock strings are pre-localized to the
  user's IANA zone, so the washer/dishwasher hero can never print UTC.

See ``backend/services/eink/README.md`` for the full layering rules and
the "how to add a new appliance / new design" guide.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PIL import Image, ImageDraw

from . import fonts, layout
from .appliances import ActiveAppliance, pick_active
from .draw import (
    Box,
    HRow,
    Run,
    VStack,
    bullet,
    dotted_hr,
    draw_headline,
    draw_outlined_text,
    draw_text_bl,
    draw_tracked_text_bl,
    draw_tracked_text_bl_center,
    draw_tracked_text_bl_right,
    em_to_px,
    fill_box,
    fill_box_dither,
    font_metrics,
    hairline_hr,
    pick_fitting_size,
    text_width,
    tracked_width,
)
from .ha_view import (
    ApplianceView,
    FloorView,
    HvacSummary,
    build_appliance_view,
    build_floor_views,
    build_hvac_summary,
)
from .helpers import (
    compass,
    fmt_clock,
    fmt_date,
    fmt_date_short,
    fmt_temp,
    fmt_time,
    lerp_pct,
    safe_int,
    safe_round,
)
from .palette import Palette
from .render_ctx import RenderContext, build_render_context


CANVAS_W, CANVAS_H = 800, 480


# ── Top-level ──────────────────────────────────────────────────────────


def render_dashboard(
    img: Image.Image,
    ha: dict,
    P: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    draw = ImageDraw.Draw(img)

    ctx = build_render_context(ha, P, tz_name=tz_name)
    active = pick_active(ha, ctx)
    lead = active[0] if active else None

    _draw_header(draw, ctx, active)
    _draw_body(draw, ctx, ha, lead, bool(active))
    _draw_footer(draw, ctx, ha, active)


# ── Section labels ─────────────────────────────────────────────────────


def _section_label(
    draw: ImageDraw.ImageDraw,
    box: Box,
    text: str,
    *,
    P: Palette,
    invert: bool = False,
) -> None:
    """Tracked-caps section label baselined against the top of `box`."""
    font = fonts.pix_cherry_small(layout.SwissType.SECTION_LABEL_PX, bold=True)
    tracking = em_to_px(layout.SwissType.SECTION_LABEL_PX,
                        layout.SwissType.SECTION_TRACKING_EM)
    fm = font_metrics(font)
    color = P.bg if invert else P.muted
    baseline = box.y0 + fm.ascent
    draw_tracked_text_bl(draw, (box.x0, baseline),
                         text.upper(), font, color, tracking)


def _sub_label(
    draw: ImageDraw.ImageDraw,
    box: Box,
    text: str,
    *,
    P: Palette,
) -> None:
    font = fonts.pix_cherry_small(9, bold=True)
    tracking = em_to_px(9, 0.20)
    fm = font_metrics(font)
    baseline = box.y0 + fm.ascent
    draw_tracked_text_bl(draw, (box.x0, baseline),
                         text.upper(), font, P.muted, tracking)


# ── Header ─────────────────────────────────────────────────────────────


def _draw_header(draw, ctx: RenderContext, active) -> None:
    """36-px top strip: ink-on-ink wordmark | HOME STATUS / date | active
    indicator | refresh clock. All baselines derived from font_metrics so
    a longer date never collides with a longer status label."""
    L = layout.SWISS
    TY = layout.SwissType
    P = ctx.palette
    now = ctx.now_local

    fill_box(draw, L.header_bottom_rule, P.rule)
    fill_box(draw, L.header_rule_1, P.rule)
    fill_box(draw, L.header_rule_2, P.rule)
    fill_box(draw, L.header_rule_3, P.rule)

    fill_box(draw, L.header_cell_wordmark, P.ink)
    word_font = fonts.pix_cherry(TY.WORDMARK_PX, bold=True)
    wm_tracking = em_to_px(TY.WORDMARK_PX, TY.WORDMARK_TRACKING_EM)
    fm_w = font_metrics(word_font)
    wm_baseline = L.header_cell_wordmark.cy + fm_w.ascent // 2 - 1
    draw_tracked_text_bl(
        draw,
        (L.header_cell_wordmark.x0 + 14, wm_baseline),
        "CAMBRIDGE", word_font, P.bg, wm_tracking,
    )

    label_font = fonts.pix_cherry_small(TY.HEADER_LABEL_PX, bold=True)
    date_font = fonts.pix_cherry_small(TY.HEADER_LABEL_PX, bold=False)
    l_tracking = em_to_px(TY.HEADER_LABEL_PX, TY.HEADER_TRACKING_EM)
    fm_l = font_metrics(label_font)
    label_baseline = L.masthead.cy + fm_l.ascent // 2

    status = L.header_cell_status.inset(left=14, right=14)
    date_s = fmt_date(now).upper()
    date_w = tracked_width(date_font, date_s, l_tracking)
    (HRow(status)
        .flex(lambda b: draw_tracked_text_bl(
            draw, (b.x0, label_baseline), "HOME STATUS",
            label_font, P.ink, l_tracking))
        .fixed(date_w, lambda b: draw_tracked_text_bl(
            draw, (b.x0, label_baseline), date_s,
            date_font, P.ink, l_tracking))
    ).render(draw)

    act = L.header_cell_active.inset(left=14, right=8)
    has_active = bool(active)
    color = ctx.accent("alert") if has_active else ctx.accent("idle")
    text = f"{len(active)} ACTIVE" if has_active else "NOMINAL"
    bullet_dia = 9
    (HRow(act, gap=8)
        .fixed(bullet_dia, lambda b: bullet(
            draw, b.x0 + bullet_dia // 2, label_baseline - fm_l.ascent // 2 + 1,
            3, filled=has_active, color=color))
        .flex(lambda b: draw_tracked_text_bl(
            draw, (b.x0, label_baseline), text,
            label_font, color, l_tracking))
    ).render(draw)

    refresh = L.header_cell_refresh.inset(left=8, right=14)
    rt = f"\u21bb {fmt_time(now).upper().replace(' ', '')}"
    draw_tracked_text_bl_right(
        draw, (refresh.x1, label_baseline),
        rt, label_font, P.muted, l_tracking,
    )


# ── Body ───────────────────────────────────────────────────────────────


def _draw_body(draw, ctx: RenderContext, ha, lead, has_active) -> None:
    """12-col body: hero (top 170 px) + 4|4|4 bottom row. Each cell
    receives a Box and composes its own VStack."""
    L = layout.SWISS
    P = ctx.palette

    fill_box(draw, L.body_mid_rule, P.rule)
    fill_box(draw, L.hero_divider, P.rule)
    fill_box(draw, L.bottom_rule_left, P.rule)
    fill_box(draw, L.bottom_rule_right, P.rule)
    fill_box(draw, L.hero_right_inner_rule, P.rule)
    fill_box(draw, L.bottom_middle_rule, P.rule)

    if has_active and lead is not None:
        _draw_hero_active(draw, ctx, lead, L.hero_left)
    else:
        _draw_hero_quiet(draw, ctx, ha, L.hero_left)

    _draw_time_cell(draw, ctx, L.hero_right_time)
    _draw_outside_cell(draw, ctx, ha, L.hero_right_outside)

    _draw_climate_cell(draw, ctx, ha, L.bottom_left)
    _draw_pool_cell(draw, ctx, ha, L.bottom_middle_top)
    _draw_sauna_cell(draw, ctx, ha, L.bottom_middle_bottom)
    _draw_occupancy_cell(draw, ctx, ha, L.bottom_right)


def _draw_hero_quiet(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    ha: dict,
    box: Box,
) -> None:
    """Calm state: tiny eyebrow + 'Nothing running.' + meta line on the
    left, giant outlined '00' on the right."""
    TY = layout.SwissType
    P = ctx.palette
    inner = box.inset(left=18, right=18, top=12, bottom=12)
    text_col, num_col = inner.split_cols(1.0, 200)

    head_factory = lambda s: fonts.sans(s, weight="bold")
    label_font = fonts.pix_cherry_small(TY.SECTION_LABEL_PX, bold=True)
    fm_lbl = font_metrics(label_font)
    meta_font = fonts.pix_cherry_small(11, bold=True)
    fm_meta = font_metrics(meta_font)

    def _label(b: Box) -> None:
        _section_label(draw, b, "00 / NOW \u00b7 ALL CLEAR", P=P)

    def _headlines(b: Box) -> None:
        font = head_factory(TY.HERO_QUIET_CANDIDATES[-1])
        for size in TY.HERO_QUIET_CANDIDATES:
            cand = head_factory(size)
            fm = font_metrics(cand)
            line_h = fm.line_height - 4
            if line_h * 2 > b.h:
                continue
            wmax = max(text_width(cand, "Nothing"),
                       text_width(cand, "running."))
            if wmax <= b.w:
                font = cand
                break
        fm = font_metrics(font)
        line_h = fm.line_height - 4
        bl2 = b.y1 - fm.descent
        bl1 = bl2 - line_h
        draw_text_bl(draw, (b.x0, bl1), "Nothing", font, P.ink)
        draw_text_bl(draw, (b.x0, bl2), "running.", font, P.ink)

    def _meta(b: Box) -> None:
        people = ha.get("people") or []
        home_count = sum(1 for p in people if p.get("state") == "home")
        total = len(people)
        wins = len(ha.get("openWindows") or [])
        candidates = [
            f"{home_count}/{total} HOME \u00b7 {wins} WIN \u00b7 CLIMATE OK",
            f"{home_count}/{total} HOME \u00b7 {wins} WIN OPEN",
            f"{home_count}/{total} HOME",
        ]
        meta_tracking = em_to_px(11, 0.14)
        s = candidates[-1]
        for cand in candidates:
            if tracked_width(meta_font, cand, meta_tracking) <= b.w:
                s = cand
                break
        baseline = b.y1 - fm_meta.descent
        draw_tracked_text_bl(draw, (b.x0, baseline), s,
                             meta_font, P.muted, meta_tracking)

    (VStack(text_col, gap=4)
        .fixed(fm_lbl.line_height, _label, label="eyebrow")
        .flex(_headlines, label="headlines")
        .fixed(fm_meta.line_height, _meta, label="meta")
    ).render(draw)

    giant_factory = lambda s: fonts.sans(s, weight="bold")
    giant_font, giant_size = pick_fitting_size(
        giant_factory, "00", num_col.w, TY.HERO_QUIET_GIANT_CANDIDATES,
    )
    fm_g = font_metrics(giant_font)
    text_w = text_width(giant_font, "00")
    gx = num_col.x1 - text_w
    gy = num_col.y1 - fm_g.line_height
    draw_outlined_text(
        draw, (gx, gy), "00", giant_font,
        stroke_px=2, stroke_fill=P.ink, fill=P.bg,
    )


def _draw_hero_active(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    item: ActiveAppliance,
    box: Box,
) -> None:
    """Active state: eyebrow + headline + sub + bar on the left, big
    auto-fit number on the right. The big number can never overflow its
    column because it's routed through draw_fit_text_bl."""
    TY = layout.SwissType
    P = ctx.palette
    view = item.view
    meta = _describe_active_swiss(view, ctx)
    accent = meta["accent"]

    inner = box.inset(left=18, right=18, top=12, bottom=12)
    left, right = inner.split_cols(7 / 12.0, 5 / 12.0)
    fill_box(
        draw,
        Box(left.x1, box.y0 + 6, left.x1 + 1, box.y1 - 6),
        P.rule,
    )
    right = right.inset(left=14)

    label_font = fonts.pix_cherry_small(10, bold=True)
    fm_lbl = font_metrics(label_font)
    sub_font = fonts.pix_cherry_small(10, bold=True)
    fm_sub = font_metrics(sub_font)

    def _eyebrow(b: Box) -> None:
        sq = 9
        draw.rectangle(
            [(b.x0, b.y0 + 2),
             (b.x0 + sq - 1, b.y0 + 2 + sq - 1)],
            fill=accent,
        )
        draw_tracked_text_bl(
            draw, (b.x0 + sq + 6, b.y0 + fm_lbl.ascent),
            f"00 / NOW \u00b7 {meta['eyebrow']}",
            label_font, accent, em_to_px(10, 0.22),
        )

    def _headline(b: Box) -> None:
        draw_headline(
            draw, (b.x0, b.y0, b.w, b.h),
            meta["head_runs"], line_height_px=30, align="left",
            max_lines=2,
        )

    def _sub(b: Box) -> None:
        text = meta["sub"]
        if not text:
            return
        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        tracking = em_to_px(10, 0.10)
        for word in words:
            trial = (cur + " " + word).strip()
            if tracked_width(sub_font, trial, tracking) > b.w and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        cy = b.y0 + fm_sub.ascent
        line_h = fm_sub.line_height + 1
        for line in lines[:max(1, b.h // line_h)]:
            draw_tracked_text_bl(draw, (b.x0, cy), line,
                                 sub_font, P.muted, tracking)
            cy += line_h

    def _bar(b: Box) -> None:
        if meta.get("bar"):
            _draw_seg_bar(draw, P, b.x0, b.y0 + 4, b.w, **meta["bar"])

    bar_h = 28 if meta.get("bar") else 0
    (VStack(left, gap=4)
        .fixed(14, _eyebrow, label="eyebrow")
        .fixed(64, _headline, label="headline")
        .flex(_sub, label="sub")
        .fixed(bar_h, _bar, label="bar")
    ).render(draw)

    big_label_font = fonts.pix_cherry_small(9, bold=True)
    big_label_tracking = em_to_px(9, 0.22)
    fm_bl = font_metrics(big_label_font)
    big_sub_font = fonts.pix_cherry_small(10, bold=True)
    big_sub_tracking = em_to_px(10, 0.16)
    fm_bs = font_metrics(big_sub_font)

    def _big_label(b: Box) -> None:
        draw_tracked_text_bl(
            draw, (b.x0, b.y0 + fm_bl.ascent),
            meta["big_label"].upper(),
            big_label_font, P.muted, big_label_tracking,
        )

    def _big(b: Box) -> None:
        big_factory = lambda s: fonts.sans(s, weight="bold")
        font = big_factory(TY.HERO_BIG_CANDIDATES[-1])
        for size in TY.HERO_BIG_CANDIDATES:
            cand = big_factory(size)
            if font_metrics(cand).line_height > b.h:
                continue
            if text_width(cand, meta["big"]) <= b.w:
                font = cand
                break
        fm = font_metrics(font)
        baseline = b.y1 - fm.descent
        draw.text((b.x0, baseline), meta["big"],
                  font=font, fill=accent, anchor="ls")

    def _big_sub(b: Box) -> None:
        draw_tracked_text_bl(
            draw, (b.x0, b.y1 - fm_bs.descent),
            (meta.get("big_sub") or "").upper(),
            big_sub_font, P.muted, big_sub_tracking,
        )

    (VStack(right, gap=4)
        .fixed(fm_bl.line_height, _big_label, label="big_label")
        .flex(_big, label="big_number")
        .fixed(fm_bs.line_height, _big_sub, label="big_sub")
    ).render(draw)


# ── Per-kind hero descriptors ──────────────────────────────────────────
#
# Each ``_describe_<kind>_swiss`` consumes an ``ApplianceView`` (already
# tz-correct) and returns the meta dict ``_draw_hero_active`` consumes.
# Adding a new appliance = add a row to ``_SWISS_HERO_DESCRIBERS`` plus a
# small builder. None of these touch the HA dict directly.


def _describe_active_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    """Dispatch to the per-kind descriptor. Falls back to a placeholder
    for unknown kinds so the renderer never crashes on a future
    appliance the registry knows about but Swiss doesn't."""
    builder = _SWISS_HERO_DESCRIBERS.get(view.kind, _describe_unknown_swiss)
    return builder(view, ctx)


def _describe_sauna_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    head_font = fonts.sans(layout.SwissType.HERO_ACTIVE_HEAD_PX, weight="bold")
    accent = ctx.accent(view.accent_kind)
    target = view.target
    current = view.current
    rem = view.extras.get("remaining_deg")
    runs = [
        Run("Climbing to ", head_font, P.ink),
        Run(f"{safe_round(target)}\u00b0", head_font, accent),
    ]
    if rem is not None:
        runs.append(Run(f", {int(rem)}\u00b0 to go.", head_font, P.ink))
    else:
        runs.append(Run(".", head_font, P.ink))
    heaters = view.extras.get("heaters", 0)
    door = "open" if view.extras.get("door_open") else "closed"
    sub = (f"{heaters}/3 elements \u00b7 "
           f"{view.extras.get('duration', 0)}m cycle \u00b7 "
           f"room {fmt_temp(view.extras.get('room_temp'))} "
           f"{view.extras.get('room_humidity', 0)}%RH \u00b7 "
           f"door {door}")
    return {
        "eyebrow": view.eyebrow_label, "accent": accent,
        "head_runs": runs, "sub": sub,
        "big": f"{safe_round(current)}\u00b0",
        "big_label": "CABIN \u00b7 NOW",
        "big_sub": f"\u2192 {fmt_temp(target)}",
        "bar": {"from": 60, "to": max(float(target or 175), 175),
                "now": current, "target": target, "accent": accent},
    }


def _describe_washer_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    head_font = fonts.sans(layout.SwissType.HERO_ACTIVE_HEAD_PX, weight="bold")
    accent = ctx.accent(view.accent_kind)
    runs = [Run(f"{view.status_label}.", head_font, P.ink)]
    cycle = view.extras.get("cycle_no", 0)
    return {
        "eyebrow": view.eyebrow_label, "accent": accent, "head_runs": runs,
        "sub": f"Cycle #{cycle} \u00b7 finishes {view.finish_label}",
        "big": view.relative_label,
        "big_label": "REMAINING", "big_sub": "CYCLE ACTIVE", "bar": None,
    }


def _describe_washer_done_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    head_font = fonts.sans(layout.SwissType.HERO_ACTIVE_HEAD_PX, weight="bold")
    accent = ctx.accent(view.accent_kind)
    cycle = view.extras.get("cycle_no", 0)
    return {
        "eyebrow": view.eyebrow_label, "accent": accent,
        "head_runs": [Run("Move to dryer.", head_font, P.ink)],
        "sub": f"Cycle #{cycle} finished {view.finish_label}",
        "big": "\u2713", "big_label": "COMPLETE",
        "big_sub": (view.relative_label or "\u2014").upper(),
        "bar": None,
    }


def _describe_dishwasher_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    head_font = fonts.sans(layout.SwissType.HERO_ACTIVE_HEAD_PX, weight="bold")
    accent = ctx.accent(view.accent_kind)
    prog = view.progress_pct
    prog_s = f"{prog}%" if prog is not None else "\u2014"
    program = view.program_label or "\u2014"
    return {
        "eyebrow": view.eyebrow_label, "accent": accent,
        "head_runs": [Run(f"{program}.", head_font, P.ink)],
        "sub": f"Finishes {view.relative_label}",
        "big": prog_s, "big_label": "COMPLETE",
        "big_sub": view.finish_label,
        "bar": ({"from": 0, "to": 100, "now": prog, "target": None,
                 "accent": accent, "hide_labels": True}
                if prog is not None else None),
    }


def _describe_pool_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    head_font = fonts.sans(layout.SwissType.HERO_ACTIVE_HEAD_PX, weight="bold")
    accent = ctx.accent(view.accent_kind)
    target = view.target
    current = view.current
    runs = [
        Run("Climbing to ", head_font, P.ink),
        Run(f"{safe_round(target)}\u00b0", head_font, accent),
        Run(".", head_font, P.ink),
    ]
    freeze = ("freeze guard on" if view.extras.get("freeze_protect")
              else "no freeze risk")
    return {
        "eyebrow": view.eyebrow_label, "accent": accent, "head_runs": runs,
        "sub": (f"Heat exchanger active \u00b7 "
                f"air {fmt_temp(view.extras.get('air_temp'))} \u00b7 {freeze}"),
        "big": f"{safe_round(current)}\u00b0",
        "big_label": "WATER \u00b7 NOW",
        "big_sub": f"\u2192 {fmt_temp(target)}",
        "bar": {"from": 50, "to": max(float(target or 90), 90),
                "now": current, "target": target, "accent": accent},
    }


def _describe_unknown_swiss(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    head_font = fonts.sans(layout.SwissType.HERO_ACTIVE_HEAD_PX, weight="bold")
    return {
        "eyebrow": view.eyebrow_label or "\u2014",
        "accent": ctx.accent(view.accent_kind or "ink"),
        "head_runs": [Run("\u2014", head_font, P.ink)],
        "sub": "", "big": "\u2014", "big_label": "", "big_sub": "", "bar": None,
    }


_SWISS_HERO_DESCRIBERS = {
    "sauna":        _describe_sauna_swiss,
    "washer":       _describe_washer_swiss,
    "washer-done":  _describe_washer_done_swiss,
    "dishwasher":   _describe_dishwasher_swiss,
    "pool":         _describe_pool_swiss,
}


# ── Segment bar ────────────────────────────────────────────────────────


def _draw_seg_bar(draw, P, x0, y, w, *, now=None, target=None,
                  accent=(0, 0, 0), hide_labels=False, **_kwargs) -> None:
    from_v = _kwargs.get("from", 0)
    to_v = _kwargs.get("to", 100)
    if now is None:
        return
    nowf = float(now)
    pct = lerp_pct(nowf, from_v, to_v)
    segs = 36
    fill_count = round(pct * segs)
    bar_h = 10
    bar_y1 = y + bar_h

    draw.rectangle([(x0, y), (x0 + w - 1, bar_y1 - 1)], outline=P.rule, width=1)
    seg_w = (w - 2) / segs
    for i in range(segs):
        sx0 = x0 + 1 + int(i * seg_w)
        sx1 = x0 + 1 + int((i + 1) * seg_w)
        if i < fill_count:
            draw.rectangle([(sx0, y + 1), (sx1 - 1, bar_y1 - 2)], fill=accent)
        elif i % 4 == 0:
            cx = (sx0 + sx1) // 2
            draw.rectangle([(cx, y + 2), (cx, bar_y1 - 3)], fill=P.muted)

    if target is not None:
        tpct = lerp_pct(float(target), from_v, to_v)
        tx = x0 + int(tpct * (w - 2))
        draw.rectangle([(tx, y - 3), (tx + 1, bar_y1 + 2)], fill=P.ink)

    if not hide_labels:
        lf = fonts.pix_cherry_small(9, bold=True)
        tr = em_to_px(9, 0.10)
        fm = font_metrics(lf)
        ly = bar_y1 + 4 + fm.ascent
        draw_tracked_text_bl(draw, (x0, ly), f"{int(from_v)}\u00b0", lf, P.muted, tr)
        mid = f"NOW {int(round(nowf))}\u00b0"
        draw_tracked_text_bl_center(draw, (x0 + w // 2, ly), mid, lf, P.ink, tr)
        right = f"{int(to_v)}\u00b0"
        draw_tracked_text_bl_right(draw, (x0 + w, ly), right, lf, P.muted, tr)


# ── Time + outside cells ───────────────────────────────────────────────


def _draw_time_cell(draw, ctx: RenderContext, box: Box) -> None:
    """VStack [section_label, big time row, date row]. Auto-fit clock so
    even a wide locale fits."""
    TY = layout.SwissType
    P = ctx.palette
    now_local = ctx.now_local
    inner = box.inset(left=16, right=16, top=10, bottom=8)

    label_font = fonts.pix_cherry_small(TY.HEADER_LABEL_PX, bold=True)
    fm_label = font_metrics(label_font)
    date_font = fonts.pix_cherry_small(10, bold=True)
    fm_date = font_metrics(date_font)

    def _label(b: Box) -> None:
        _section_label(draw, b, "01 / TIME \u00b7 LOCAL", P=P)

    def _time(b: Box) -> None:
        time_s = now_local.strftime("%H:%M")
        sec_s = f":{now_local.strftime('%S')}"
        sec_font = fonts.pix_cherry(11, bold=True)
        sec_tracking = em_to_px(11, 0.14)
        sec_w = tracked_width(sec_font, sec_s, sec_tracking) + 6
        big_max_w = b.w - sec_w
        big_factory = lambda s: fonts.sans(s, weight="bold")
        big_font = big_factory(TY.TIME_BIG_CANDIDATES[-1])
        for size in TY.TIME_BIG_CANDIDATES:
            cand = big_factory(size)
            fm_c = font_metrics(cand)
            if fm_c.line_height > b.h:
                continue
            if text_width(cand, time_s) <= big_max_w:
                big_font = cand
                break
        fm_big = font_metrics(big_font)
        baseline = b.y0 + fm_big.ascent
        tw = text_width(big_font, time_s)
        draw.text((b.x0, baseline), time_s,
                  font=big_font, fill=P.ink, anchor="ls")
        draw_tracked_text_bl(
            draw, (b.x0 + tw + 4, baseline),
            sec_s, sec_font, P.muted, sec_tracking,
        )

    def _date(b: Box) -> None:
        baseline = b.y1 - fm_date.descent
        draw_tracked_text_bl(
            draw, (b.x0, baseline),
            fmt_date_short(now_local),
            date_font, P.ink, em_to_px(10, 0.18),
        )

    (VStack(inner, gap=2)
        .fixed(fm_label.line_height, _label, label="section")
        .flex(_time, label="time")
        .fixed(fm_date.line_height, _date, label="date")
    ).render(draw)


def _draw_outside_cell(draw, ctx: RenderContext, ha, box: Box) -> None:
    """VStack [section_label, value+stats HRow]. Temp auto-fits its half
    of the row; stats get a fixed 110-px column on the right."""
    TY = layout.SwissType
    P = ctx.palette
    w = ha.get("weather") or {}
    state = (w.get("state") or "").replace("_", " ").upper()

    inner = box.inset(left=16, right=16, top=8, bottom=8)
    label_font = fonts.pix_cherry_small(TY.SECTION_LABEL_PX, bold=True)
    fm_label = font_metrics(label_font)

    def _label(b: Box) -> None:
        _section_label(draw, b, f"02 / OUTSIDE \u00b7 {state}", P=P)

    def _value_row(b: Box) -> None:
        stats_w = 120
        big_box, stats_box = b.split_cols(1.0, stats_w)
        temp_s = f"{safe_round(w.get('temperature'))}"
        unit_s = "\u00b0F"
        unit_font = fonts.sans(22, weight="bold")
        unit_w = text_width(unit_font, unit_s) + 4
        big_max_w = big_box.w - unit_w
        big_factory = lambda s: fonts.sans(s, weight="bold")
        big_font = big_factory(TY.OUTSIDE_BIG_CANDIDATES[-1])
        for size in TY.OUTSIDE_BIG_CANDIDATES:
            cand = big_factory(size)
            if font_metrics(cand).line_height > big_box.h:
                continue
            if text_width(cand, temp_s) <= big_max_w:
                big_font = cand
                break
        fm_big = font_metrics(big_font)
        baseline = big_box.y0 + fm_big.ascent + 4
        tw = text_width(big_font, temp_s)
        draw.text((big_box.x0, baseline), temp_s,
                  font=big_font, fill=P.ink, anchor="ls")
        draw.text((big_box.x0 + tw + 4, baseline), unit_s,
                  font=unit_font, fill=P.ink, anchor="ls")

        kv_font = fonts.pix_cherry(11, bold=True)
        kv_tr = em_to_px(11, 0.06)
        kf = fonts.pix_cherry_small(9, bold=True)
        kf_tr = em_to_px(9, 0.18)
        fm_kv = font_metrics(kv_font)

        def _kv(by: int, k: str, v: str) -> None:
            v_w = tracked_width(kv_font, v, kv_tr)
            lw = tracked_width(kf, k, kf_tr)
            total = lw + 6 + v_w
            start = stats_box.x1 - total
            draw_tracked_text_bl(draw, (start, by), k, kf, P.muted, kf_tr)
            draw_tracked_text_bl(draw, (start + lw + 6, by), v,
                                 kv_font, P.ink, kv_tr)

        rows = [
            ("WIND", f"{safe_round(w.get('windSpeed'))} {compass(w.get('windBearing'))}"),
            ("HUM", f"{safe_round(w.get('humidity'))}%"),
            ("PRES", (f"{float(w.get('pressure')):.2f}"
                      if w.get('pressure') is not None else "\u2014")),
        ]
        row_h = fm_kv.line_height + 1
        bottom_baseline = stats_box.y1 - fm_kv.descent
        for i, (k, v) in enumerate(reversed(rows)):
            _kv(bottom_baseline - row_h * i, k, v)

    (VStack(inner, gap=2)
        .fixed(fm_label.line_height, _label, label="section")
        .flex(_value_row, label="value")
    ).render(draw)


# ── Pool / Sauna (shared "hot cell") ───────────────────────────────────


def _draw_pool_cell(draw, ctx: RenderContext, ha, box: Box) -> None:
    P = ctx.palette
    pool = ha.get("pool") or {}
    heating = bool(pool.get("heating"))
    pumping = bool(pool.get("pumpRunning"))
    if heating:
        label = "04 / POOL \u00b7 HEATING"
    elif pumping:
        label = "04 / POOL \u00b7 FILTERING"
    else:
        label = "04 / POOL \u00b7 IDLE"
    freeze = "FREEZE GUARD" if pool.get("freezeProtect") else "NO FREEZE"
    sub = f"AIR {fmt_temp(pool.get('air'))} \u00b7 {freeze}"
    _draw_hot_cell(
        draw, P, box, label=label, heating=heating,
        current=pool.get("current"), target=pool.get("target"), sub=sub,
    )


def _draw_sauna_cell(draw, ctx: RenderContext, ha, box: Box) -> None:
    P = ctx.palette
    s = ha.get("sauna") or {}
    heating = s.get("mode") == "heat"
    label = "05 / SAUNA \u00b7 " + ("HEATING" if heating else "STANDBY")
    door = "OPEN" if s.get("door") else "CLOSED"
    sub = (f"ELEMENTS {safe_int(s.get('heaters'))}/3 "
           f"\u00b7 DOOR {door} \u00b7 {safe_int(s.get('duration'))}m")
    _draw_hot_cell(
        draw, P, box, label=label, heating=heating,
        current=s.get("current"), target=s.get("target"), sub=sub,
    )


def _draw_hot_cell(
    draw: ImageDraw.ImageDraw,
    P: Palette,
    box: Box,
    *,
    label: str,
    heating: bool,
    current: Any,
    target: Any,
    sub: str,
) -> None:
    """Shared layout for Pool / Sauna cells. Inverts to red (or ink in
    BW) when heating. Composes:
        VStack [section_label, value HRow, sub_line]
    The big number is auto-fit so 3-digit temps can't overflow.
    """
    TY = layout.SwissType
    if heating:
        fill_box(draw, box, P.red if not P.is_bw else P.ink)
    text_color = P.bg if heating else P.ink
    label_color = P.bg if heating else P.muted

    inner = box.inset(left=14, right=14, top=10, bottom=8)

    label_font = fonts.pix_cherry_small(TY.SECTION_LABEL_PX, bold=True)
    fm_label = font_metrics(label_font)
    sub_font = fonts.pix_cherry_small(9, bold=True)
    fm_sub = font_metrics(sub_font)

    def _label_row(b: Box) -> None:
        _section_label(draw, b, label, P=P, invert=heating)

    def _value_row(b: Box) -> None:
        unit_font = fonts.sans(18, weight="bold")
        fm_unit = font_metrics(unit_font)
        unit_s = "\u00b0F"
        unit_w = text_width(unit_font, unit_s) + 4

        tgt_font = fonts.pix_cherry_small(10, bold=True)
        tgt_tracking = em_to_px(10, 0.14)
        tgt_s = f"\u2192 {fmt_temp(target)}"
        tgt_w = tracked_width(tgt_font, tgt_s, tgt_tracking) + 6

        big_max_w = b.w - unit_w - tgt_w
        big_factory = lambda s: fonts.sans(s, weight="bold")
        big_s = f"{safe_round(current)}"
        big_font = big_factory(TY.POOL_SAUNA_BIG_CANDIDATES[-1])
        for size in TY.POOL_SAUNA_BIG_CANDIDATES:
            cand = big_factory(size)
            if font_metrics(cand).line_height > b.h:
                continue
            if text_width(cand, big_s) <= big_max_w:
                big_font = cand
                break
        fm_big = font_metrics(big_font)
        baseline = b.y1 - fm_big.descent
        tw = text_width(big_font, big_s)
        draw.text((b.x0, baseline), big_s,
                  font=big_font, fill=text_color, anchor="ls")
        draw.text(
            (b.x0 + tw + 4, baseline - (fm_big.ascent - fm_unit.ascent) // 2 - 2),
            unit_s, font=unit_font, fill=text_color, anchor="ls",
        )
        tgt_baseline = baseline - fm_big.ascent // 3
        draw_tracked_text_bl_right(
            draw, (b.x1, tgt_baseline),
            tgt_s, tgt_font, text_color, tgt_tracking,
        )

    def _sub_row(b: Box) -> None:
        baseline = b.y1 - fm_sub.descent
        max_tracking = em_to_px(9, 0.16)
        s = sub
        while s and tracked_width(sub_font, s, max_tracking) > b.w:
            s = s[:-2] + "\u2026"
        draw_tracked_text_bl(
            draw, (b.x0, baseline), s,
            sub_font, text_color, max_tracking,
        )

    (VStack(inner, gap=2)
        .fixed(fm_label.line_height, _label_row, label="section")
        .flex(_value_row, label="value")
        .fixed(fm_sub.line_height, _sub_row, label="sub")
    ).render(draw)


# ── Climate cell ───────────────────────────────────────────────────────


def _draw_climate_cell(draw, ctx: RenderContext, ha, box: Box) -> None:
    """VStack [section_label, *4 floor rows]. Floor rows render heating
    as a solid bar in red, cooling as a 50/50-dithered bar in blue,
    idle as a hollow outlined bar -- the state comes from FloorView so
    a stale HA action can't get the direction wrong.

    Within each row, the floor label, the bar mid-line, the big temp
    digits, and the H{n}/C{n} chip all share a baseline derived from
    the big-temp font's ascent/descent, so the digits are visually
    centered in the row no matter which size the auto-fit picks.
    """
    TY = layout.SwissType
    P = ctx.palette
    inner = box.inset(left=14, right=14, top=10, bottom=8)

    label_font = fonts.pix_cherry_small(TY.SECTION_LABEL_PX, bold=True)
    fm_label = font_metrics(label_font)
    sub_font = fonts.pix_cherry_small(9, bold=True)
    floor_label_font = fonts.pix_cherry(13, bold=True)

    floor_views = build_floor_views(ha, [
        ("third", "3F"),
        ("second", "2F"),
        ("first", "1F"),
        ("basement", "BS"),
    ])
    vals = [v.temp for v in floor_views if v.temp is not None]
    lo = (min(vals) - 2) if vals else 0
    hi = (max(vals) + 2) if vals else 100

    # Pick the big-temp font once against the widest expected string so
    # every row shares the same metric -- otherwise an auto-fit pick
    # for one row could shift its baseline relative to the others.
    big_factory = lambda s: fonts.sans(s, weight="bold")
    sample = max(
        (fmt_temp(v.temp).replace("\u00b0", "") for v in floor_views),
        key=len, default="00",
    ) or "00"
    # Reserve enough room for both the widest temp ("100" stress case)
    # and the widest chip ("C12") so the right cluster never reflows.
    big_font, _ = pick_fitting_size(
        big_factory, sample, 48, TY.FLOOR_TEMP_CANDIDATES,
    )
    fm_big = font_metrics(big_font)
    temp_w = text_width(big_font, sample)
    chip_w = max(
        tracked_width(sub_font, lbl, 2)
        for lbl in ("H1", "C1", "H12", "C12")
    )
    inner_gap = 4
    # Bar is intentionally short so the temp digits sit right next to
    # it (the gap was visually wide when the bar took all the slack).
    bar_w = 80

    def _section(b: Box) -> None:
        _section_label(draw, b, "03 / CLIMATE", P=P)

    def _floor_row(b: Box, view: FloorView, is_first: bool) -> None:
        if not is_first:
            hairline_hr(draw, b.x0, b.x1, b.y0, fill=P.rule)
        accent = ctx.accent(view.accent_kind)
        # Single shared baseline: ink box of the big digits is
        # vertically centered in the row.
        baseline = b.cy + (fm_big.ascent - fm_big.descent) // 2
        # [label][flex spacer][bar][gap][temp][gap][chip] -- the slack
        # sits BETWEEN label and bar so the bar/temp/chip read as one
        # tight cluster on the right.
        (HRow(b.inset(top=4 if not is_first else 2), gap=0)
            .fixed(24, lambda c: _floor_label(c, view.label, baseline))
            .flex(lambda _c: None, label="spacer")
            .fixed(bar_w, lambda c: _floor_bar(c, view), label="bar")
            .fixed(8, lambda _c: None, label="bar_gap")
            .fixed(temp_w,
                   lambda c: _floor_temp_value(c, view, accent, baseline),
                   label="temp")
            .fixed(inner_gap, lambda _c: None, label="temp_chip_gap")
            .fixed(chip_w,
                   lambda c: _floor_temp_chip(c, view, accent, baseline),
                   label="chip")
        ).render(draw)

    def _floor_label(b: Box, lbl: str, baseline: int) -> None:
        draw_tracked_text_bl(draw, (b.x0, baseline),
                             lbl, floor_label_font, P.ink, 1)

    def _floor_bar(b: Box, view: FloorView) -> None:
        bar_h = 5
        by = b.cy - bar_h // 2
        draw.rectangle([(b.x0, by), (b.x1 - 1, by + bar_h)],
                       outline=P.ink, width=1)
        if view.temp is None or view.state == "idle":
            return
        pct = lerp_pct(float(view.temp), lo, hi)
        fw = int((b.w - 2) * pct)
        if fw <= 0:
            return
        fill_box_inner = Box(b.x0 + 1, by + 1, b.x0 + 1 + fw, by + bar_h - 1)
        accent = ctx.accent(view.accent_kind)
        if view.state == "cooling":
            fill_box_dither(draw, fill_box_inner, accent)
        else:
            draw.rectangle(
                [(fill_box_inner.x0, fill_box_inner.y0),
                 (fill_box_inner.x1, fill_box_inner.y1)],
                fill=accent,
            )

    def _floor_temp_value(b: Box, view: FloorView, color, baseline: int) -> None:
        temp_s = fmt_temp(view.temp).replace("\u00b0", "")
        tw = text_width(big_font, temp_s)
        draw.text((b.x1 - tw, baseline), temp_s,
                  font=big_font, fill=color, anchor="ls")

    def _floor_temp_chip(b: Box, view: FloorView, color, baseline: int) -> None:
        # Direction chip: H{n} red when heating, C{n} blue when cooling.
        # Idle: nothing -- the empty bar already says so.
        if view.state not in ("heating", "cooling"):
            return
        draw_tracked_text_bl_right(
            draw, (b.x1, baseline),
            view.chip_label, sub_font, color, 2,
        )

    floor_h = max(fm_big.line_height + 10, 28)

    stack = (VStack(inner, gap=0)
        .fixed(fm_label.line_height, _section, label="section")
        .gap_row(4))
    for i, view in enumerate(floor_views):
        stack.fixed(
            floor_h,
            (lambda b, _v=view, _f=(i == 0): _floor_row(b, _v, _f)),
            label=f"floor_{view.label}",
        )
    stack.flex(lambda _b: None, label="bottom_pad")
    stack.render(draw)


# ── Occupancy cell ─────────────────────────────────────────────────────


def _draw_occupancy_cell(draw, ctx: RenderContext, ha, box: Box) -> None:
    """VStack [section_label, *people, hr, chip row, hr, sun strip]. Chips
    are single-line HRow [label, flex, value] -- no more 2-line layout
    that escapes the chip box."""
    TY = layout.SwissType
    P = ctx.palette
    inner = box.inset(left=14, right=14, top=10, bottom=8)

    label_font = fonts.pix_cherry_small(TY.SECTION_LABEL_PX, bold=True)
    fm_label = font_metrics(label_font)

    name_font = fonts.sans(13, weight="medium")
    fm_name = font_metrics(name_font)
    person_label_font = fonts.pix_cherry(10, bold=True)
    fm_pl = font_metrics(person_label_font)
    person_row_h = max(fm_name.line_height, fm_pl.line_height) + 4

    chip_h = 30
    sun_h = 28

    def _section(b: Box) -> None:
        _section_label(draw, b, "06 / OCCUPANCY", P=P)

    def _person_row(b: Box, p: dict, last: bool) -> None:
        home = p.get("state") == "home"
        name = (p.get("name") or "").split(" ")[0]
        label = "HOME" if home else (p.get("state") or "AWAY").upper().replace("_", " ")
        color = ctx.accent("ok") if home else ctx.accent("idle")
        baseline = b.cy + fm_name.ascent // 2 - 1
        draw_text_bl(draw, (b.x0, baseline), name, name_font, P.ink)
        lr = em_to_px(10, 0.16)
        lw = tracked_width(person_label_font, label, lr)
        bullet_dia = 8
        gap = 5
        label_x = b.x1 - lw
        bullet_cx = label_x - gap - bullet_dia // 2
        bullet(draw, bullet_cx, baseline - fm_pl.ascent // 2 + 1,
               3, filled=home, color=color)
        draw_tracked_text_bl(draw, (label_x, baseline), label,
                             person_label_font, color, lr)
        if not last:
            dotted_hr(draw, b.x0, b.x1, b.y1 - 1, dash=1, gap=3, fill=P.rule)

    def _chips(b: Box) -> None:
        gap = 6
        chip_w = (b.w - gap) // 2
        garage_box = Box(b.x0, b.y0, b.x0 + chip_w, b.y1)
        win_box = Box(b.x0 + chip_w + gap, b.y0, b.x1, b.y1)
        g_state = (ha.get("garage") or {}).get("state") or "?"
        g_accent = ctx.accent("alert") if g_state == "open" else None
        _draw_status_chip(draw, P, garage_box,
                          k="GARAGE", v=g_state.upper(), accent=g_accent)
        wins = len(ha.get("openWindows") or [])
        w_accent = ctx.accent("warn") if wins and P.yellow != P.ink else None
        _draw_status_chip(draw, P, win_box,
                          k="WINDOWS", v=f"{wins} OPEN", accent=w_accent)

    def _sun(b: Box) -> None:
        _draw_sun_strip(draw, ctx, ha, b)

    people = ha.get("people") or []

    stack = (VStack(inner, gap=0)
        .fixed(fm_label.line_height, _section, label="section")
        .gap_row(4))
    for i, p in enumerate(people):
        last = i == len(people) - 1
        stack.fixed(
            person_row_h,
            (lambda b, _p=p, _l=last: _person_row(b, _p, _l)),
            label=f"person_{i}",
        )
    stack.gap_row(6)
    stack.fixed(1, lambda b: hairline_hr(draw, b.x0, b.x1, b.y0, fill=P.rule),
                label="hr1")
    stack.gap_row(4)
    stack.fixed(chip_h, _chips, label="chips")
    stack.gap_row(6)
    stack.fixed(1, lambda b: hairline_hr(draw, b.x0, b.x1, b.y0, fill=P.rule),
                label="hr2")
    stack.gap_row(4)
    stack.fixed(sun_h, _sun, label="sun")
    stack.flex(lambda _b: None, label="bottom_pad")
    stack.render(draw)


def _draw_status_chip(
    draw: ImageDraw.ImageDraw, P: Palette, box: Box, *,
    k: str, v: str, accent,
) -> None:
    """Single-line chip: outlined rectangle with [LABEL: VALUE] inside.
    Auto-fits the value to the available width so a long state never
    escapes the box."""
    bg = None
    text_color = P.ink
    if accent == P.red:
        bg = P.red
        text_color = P.bg
    if bg is not None:
        fill_box(draw, box, bg)
    draw.rectangle([(box.x0, box.y0), (box.x1 - 1, box.y1 - 1)],
                   outline=P.rule, width=1)

    inner = box.inset(left=6, right=6, top=2, bottom=2)
    kf = fonts.pix_cherry_small(8, bold=True)
    ktr = em_to_px(8, 0.18)
    fm_k = font_metrics(kf)
    vf = fonts.pix_cherry(11, bold=True)
    vtr = em_to_px(11, 0.10)
    fm_v = font_metrics(vf)

    lbl_baseline = inner.y0 + fm_k.ascent
    val_baseline = inner.y1 - fm_v.descent
    if val_baseline - fm_v.ascent < lbl_baseline + fm_k.descent + 1:
        baseline = inner.cy + fm_v.ascent // 2
        draw_tracked_text_bl(draw, (inner.x0, baseline),
                             k, kf, text_color, ktr)
        max_w = inner.x1 - tracked_width(kf, k, ktr) - 6 - inner.x0
        s = v
        while s and tracked_width(vf, s, vtr) > max_w:
            s = s[:-2] + "\u2026"
        vcolor = accent if (accent is not None and accent != P.red) else text_color
        draw_tracked_text_bl_right(draw, (inner.x1, baseline),
                                   s, vf, vcolor, vtr)
    else:
        draw_tracked_text_bl(draw, (inner.x0, lbl_baseline),
                             k, kf, text_color, ktr)
        max_w = inner.w
        s = v
        while s and tracked_width(vf, s, vtr) > max_w:
            s = s[:-2] + "\u2026"
        vcolor = accent if (accent is not None and accent != P.red) else text_color
        draw_tracked_text_bl(draw, (inner.x0, val_baseline),
                             s, vf, vcolor, vtr)


def _draw_sun_strip(draw, ctx: RenderContext, ha, box: Box) -> None:
    P = ctx.palette
    sun = ha.get("sun") or {}
    above = sun.get("state") == "above_horizon"
    rise = fmt_clock(sun.get("nextRising") or sun.get("nextDawn"), tz=ctx.zone)
    set_s = fmt_clock(sun.get("nextSetting") or sun.get("nextDusk"), tz=ctx.zone)

    sub_font = fonts.pix_cherry_small(9, bold=True)
    fm_s = font_metrics(sub_font)
    val_font = fonts.pix_cherry(11, bold=True)
    fm_v = font_metrics(val_font)
    val_tracking = em_to_px(11, 0.10)

    label_baseline = box.y0 + fm_s.ascent
    val_baseline = box.y1 - fm_v.descent
    _sub_label(draw, Box(box.x0, box.y0, box.x1, box.y0 + fm_s.line_height),
               "SUN \u00b7 " + ("ABOVE" if above else "BELOW"), P=P)
    draw_tracked_text_bl(draw, (box.x0, val_baseline),
                         f"\u2191 {rise}", val_font, P.ink, val_tracking)
    draw_tracked_text_bl_right(draw, (box.x1, val_baseline),
                               f"\u2193 {set_s}", val_font, P.ink, val_tracking)


# ── Footer ─────────────────────────────────────────────────────────────


def _draw_footer(draw, ctx: RenderContext, ha, active) -> None:
    L = layout.SWISS
    TY = layout.SwissType
    P = ctx.palette
    now = ctx.now_local
    fill_box(draw, L.footer_top_rule, P.rule)
    fill_box(draw, L.footer_rule_1, P.rule)
    fill_box(draw, L.footer_rule_2, P.rule)
    fill_box(draw, L.footer_rule_3, P.rule)

    f = fonts.pix_cherry_small(TY.FOOTER_LABEL_PX, bold=True)
    tr = em_to_px(TY.FOOTER_LABEL_PX, TY.FOOTER_TRACKING_EM)
    fm = font_metrics(f)
    baseline = L.colophon.cy + fm.ascent // 2

    src = L.footer_cell_src.inset(left=14, right=8)
    draw_tracked_text_bl(draw, (src.x0, baseline),
                         "SRC \u00b7 HA\u00b7KBOS", f, P.muted, tr)

    has_active = bool(active)
    status = L.footer_cell_status.inset(left=14, right=8)
    if has_active:
        bullet(draw, status.x0 + 4, baseline - fm.ascent // 2 + 1, 3,
               filled=True, color=ctx.accent("alert"))
        s = f"{len(active)} ITEM{'S' if len(active) > 1 else ''} REQUIRE ATTENTION"
        while s and tracked_width(f, s, tr) > status.w - 12:
            s = s[:-2] + "\u2026"
        draw_tracked_text_bl(draw, (status.x0 + 12, baseline),
                             s, f, ctx.accent("alert"), tr)
    else:
        bullet(draw, status.x0 + 4, baseline - fm.ascent // 2 + 1, 3,
               filled=False, color=ctx.accent("idle"))
        draw_tracked_text_bl(draw, (status.x0 + 12, baseline),
                             "ALL SYSTEMS NOMINAL", f, P.muted, tr)

    # Whole-house HVAC summary (heat/cool/idle reconciled by ha_view).
    summary: HvacSummary = build_hvac_summary(ha)
    zones_color = ctx.accent(summary.dominant) if summary.is_active else P.muted
    zones = L.footer_cell_zones.inset(left=14, right=14)
    draw_tracked_text_bl_right(draw, (zones.x1, baseline),
                               summary.label, f, zones_color, tr)

    refresh = L.footer_cell_refresh.inset(left=14, right=14)
    rt = f"\u21bb {fmt_time(now).upper()}"
    draw_tracked_text_bl_right(draw, (refresh.x1, baseline),
                               rt, f, P.muted, tr)
