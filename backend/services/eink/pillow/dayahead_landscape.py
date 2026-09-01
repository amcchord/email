"""Landscape Editorial Day Ahead layout for 800x480 Spectra 6 panels.

This is a native E1002 composition, not a resized portrait frame.  It keeps
the established Editorial type, ornaments, and semantic accent colors while
prioritizing the information that remains legible on a 7.3-inch landscape
panel: what is next, what follows, what needs attention, weather, and a small
mail/house/tomorrow status rail.

Every rule and ornament lands on integer pixels.  The encoder runs without
error-diffusion dithering; the only halftone is the deterministic, palette-ink
masthead pattern shared with the portrait design.
"""
from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw

from .dayahead_editorial import (
    KIND_ACCENT,
    PRIO_ACCENT,
    _accent,
    _ampm,
    _draw_sky_atkinson,
    _em,
    _prep,
    _serif,
    _temp_color,
    _tr,
    draw_weather_glyph,
)
from .draw import (
    Box,
    diamond,
    draw_refresh_glyph,
    draw_text_bl,
    draw_text_bl_right,
    draw_text_clipped_bl,
    draw_tracked_text_bl,
    draw_tracked_text_bl_right,
    fill_box,
    font_metrics,
    hr,
    text_width,
    tracked_width,
    vline,
)
from .palette import Palette


CANVAS_W, CANVAS_H = 800, 480
PAD_X = 20
X0, X1 = PAD_X, CANVAS_W - PAD_X
HEADER_BOTTOM = 88
BODY_TOP = 100
FOOTER_TOP = 453

LEFT_X0, LEFT_X1 = X0, 504
DIVIDER_X = 516
RIGHT_X0, RIGHT_X1 = 530, X1


def _fit_serif(text: str, max_w: int, sizes: tuple[int, ...], *, weight: str):
    for size in sizes:
        font = _serif(size, weight)
        if text_width(font, text) <= max_w:
            return font
    return _serif(sizes[-1], weight)


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    *,
    x0: int,
    x1: int,
    first_baseline: int,
    text: str,
    font,
    fill,
    line_h: int,
    max_lines: int,
) -> int:
    """Draw a bounded word wrap and ellipsize the last visible line."""

    words = (text or "").split()
    if not words:
        return first_baseline
    max_w = max(0, x1 - x0)
    lines: list[str] = []
    index = 0
    while index < len(words) and len(lines) < max_lines:
        current = words[index]
        index += 1
        while index < len(words):
            trial = f"{current} {words[index]}"
            if text_width(font, trial) > max_w:
                break
            current = trial
            index += 1
        lines.append(current)
    if index < len(words) and lines:
        lines[-1] = f"{lines[-1]} {' '.join(words[index:])}"

    baseline = first_baseline
    for line_index, line in enumerate(lines):
        draw_text_clipped_bl(
            draw,
            (x0, baseline),
            line,
            font,
            fill,
            max_w=max_w,
        )
        if line_index < len(lines) - 1:
            baseline += line_h
    return baseline


def _tab(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    text: str,
    color,
    P: Palette,
) -> int:
    color = P.ink if P.is_bw else color
    font = _tr(16, bold=True)
    fm = font_metrics(font)
    tracking = _em(16, 0.10)
    tab_h = 24
    tab_w = min(x1 - x0, tracked_width(font, text, tracking) + 18)
    fill_box(draw, Box(x0, y, x0 + tab_w, y + tab_h), color)
    draw_tracked_text_bl(
        draw,
        (x0 + 9, y + 4 + fm.ascent),
        text,
        font,
        P.bg,
        tracking,
    )
    rule_y = y + tab_h // 2
    if x0 + tab_w + 8 < x1 - 10:
        hr(draw, x0 + tab_w + 8, x1 - 10, rule_y - 1, thickness=2, fill=color)
    diamond(draw, x1 - 5, rule_y, 10, color)
    return y + tab_h


def _section_label(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    text: str,
    P: Palette,
    *,
    color=None,
) -> int:
    color = color or P.ink
    font = _tr(16, bold=True)
    fm = font_metrics(font)
    baseline = y + fm.ascent
    diamond(draw, x0 + 5, baseline - fm.ascent // 2, 9, color)
    width = draw_tracked_text_bl(
        draw,
        (x0 + 17, baseline),
        text,
        font,
        color,
        _em(16, 0.11),
    )
    rule_x = x0 + 17 + width + 9
    if rule_x < x1:
        hr(draw, rule_x, x1, baseline - fm.ascent // 2 - 1, thickness=2, fill=P.rule)
    return baseline + fm.descent + 5


def _draw_header(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    day: dict,
    P: Palette,
) -> None:
    date = day.get("date") or {}
    weather = day.get("weather") or {}
    now_weather = weather.get("now") or {}
    now_min = int(day.get("nowMin", 0))
    _draw_sky_atkinson(image, 0, 0, CANVAS_W, HEADER_BOTTOM, now_min, P)
    # Keep the 12px status rail on solid paper. The halftone remains a strong
    # masthead texture below it, while every small glyph stays unambiguous on
    # the physical panel.
    fill_box(draw, Box(0, 0, CANVAS_W, 22), P.bg)

    eyebrow = _tr(12)
    fm_eye = font_metrics(eyebrow)
    eye_base = 8 + fm_eye.ascent
    draw_tracked_text_bl(
        draw,
        (X0, eye_base),
        f"AS OF {(day.get('asOf') or '').upper()}",
        eyebrow,
        P.ink,
        _em(12, 0.08),
    )
    draw_tracked_text_bl_right(
        draw,
        (X1, eye_base),
        "THE DAY AHEAD",
        eyebrow,
        P.ink,
        _em(12, 0.12),
    )

    weekday = (date.get("weekday") or "DAY AHEAD").upper()
    weekday_font = _fit_serif(
        weekday,
        438,
        (58, 54, 50, 46, 42),
        weight="bold",
    )
    weekday_base = 72
    draw_text_clipped_bl(
        draw,
        (X0, weekday_base),
        weekday,
        weekday_font,
        P.ink,
        max_w=438,
    )

    right_left = 536
    date_font = _serif(24, "semibold")
    date_text = (date.get("monthDay") or "").upper()
    year = str(date.get("year") or "")
    date_line = f"{date_text} {year}".strip()
    draw_text_bl_right(draw, (X1, 43), date_line, date_font, P.ink)

    code = now_weather.get("code") or "cloudy"
    draw_weather_glyph(
        draw,
        right_left + 17,
        64,
        34,
        code,
        color=P.ink,
        bg=P.bg,
        stroke=2,
    )
    temp = now_weather.get("temp")
    temp_font = _serif(38, "bold")
    temp_text = "--" if temp is None else f"{temp}°"
    draw_text_bl(
        draw,
        (right_left + 43, 76),
        temp_text,
        temp_font,
        _temp_color(P, temp, "now"),
    )

    hi, lo = weather.get("hi"), weather.get("lo")
    hilo = _tr(12, bold=True)
    hilo_parts = []
    if hi is not None:
        hilo_parts.append(f"HI {hi}°")
    if lo is not None:
        hilo_parts.append(f"LO {lo}°")
    draw_text_bl_right(draw, (X1, 75), " · ".join(hilo_parts), hilo, P.ink)

    hr(draw, X0, X1, HEADER_BOTTOM, thickness=3, fill=_accent(P, "red"))


def _hero_color(day: dict, hero: Optional[dict], P: Palette):
    if hero is None:
        return _accent(P, "green")
    now_min = int(day.get("nowMin", 0))
    if hero.get("happeningNow") or int(hero.get("startMin", 0)) - now_min <= 30:
        return _accent(P, "red")
    return _accent(P, "blue")


def _draw_hero(
    draw: ImageDraw.ImageDraw,
    day: dict,
    prep: dict,
    P: Palette,
) -> int:
    hero = prep.get("hero")
    color = _hero_color(day, hero, P)
    if hero is None:
        tab_text = "A QUIET DAY"
    elif hero.get("happeningNow"):
        tab_text = "HAPPENING NOW"
    else:
        rel = (
            hero.get("rel")
            or f"{hero.get('startLabel', '')} {hero.get('startMer', '')}"
        ).upper()
        tab_text = f"UP NEXT · {rel}"
    y = _tab(draw, LEFT_X0, LEFT_X1, BODY_TOP, tab_text, color, P) + 9

    if hero is None:
        headline = "Your calendar is clear."
        headline_font = _serif(38, "bold")
        end = _draw_wrapped(
            draw,
            x0=LEFT_X0,
            x1=LEFT_X1,
            first_baseline=y + font_metrics(headline_font).ascent,
            text=headline,
            font=headline_font,
            fill=P.ink,
            line_h=39,
            max_lines=2,
        )
        mail = day.get("mail") or {}
        need = int(((mail.get("needsReply") or {}).get("count")) or 0)
        deck_font = _serif(18, "regular", italic=True)
        deck = "Nothing scheduled for the rest of today."
        if need:
            deck = f"The day is open; {need} message{'s' if need != 1 else ''} still need a reply."
        draw_text_clipped_bl(
            draw,
            (LEFT_X0, end + 9 + font_metrics(deck_font).ascent),
            deck,
            deck_font,
            P.ink,
            max_w=LEFT_X1 - LEFT_X0,
        )
        hero_bottom = 242
        hr(draw, LEFT_X0, LEFT_X1, hero_bottom, thickness=2, fill=P.rule)
        return hero_bottom + 10

    time_right = LEFT_X0 + 104
    time_font = _fit_serif(
        hero.get("startLabel") or "",
        100,
        (50, 46, 42, 38),
        weight="bold",
    )
    time_base = y + font_metrics(time_font).ascent
    draw_text_bl_right(
        draw,
        (time_right, time_base),
        hero.get("startLabel") or "",
        time_font,
        color,
    )
    mer_font = _tr(12)
    mer_text = " · ".join(
        part for part in (hero.get("startMer"), hero.get("dur")) if part
    )
    draw_text_bl_right(
        draw,
        (time_right, time_base + 4 + font_metrics(mer_font).ascent),
        mer_text,
        mer_font,
        P.ink,
    )

    bar_x = time_right + 12
    fill_box(draw, Box(bar_x, y, bar_x + 4, 229), color)
    body_x = bar_x + 15
    title_font = _serif(37, "bold")
    title_end = _draw_wrapped(
        draw,
        x0=body_x,
        x1=LEFT_X1,
        first_baseline=y + font_metrics(title_font).ascent,
        text=hero.get("title") or "Untitled",
        font=title_font,
        fill=P.ink,
        line_h=38,
        max_lines=2,
    )
    meta_font = _tr(12)
    meta_parts = [
        str(hero.get("loc") or "").upper(),
        f"{hero.get('people')} PEOPLE" if hero.get("people") else "",
    ]
    draw_text_clipped_bl(
        draw,
        (body_x, min(225, title_end + 8 + font_metrics(meta_font).ascent)),
        " · ".join(part for part in meta_parts if part)
        or (hero.get("kind") or "").upper(),
        meta_font,
        P.ink,
        max_w=LEFT_X1 - body_x,
    )

    hero_bottom = 242
    hr(draw, LEFT_X0, LEFT_X1, hero_bottom, thickness=2, fill=P.rule)
    return hero_bottom + 10


def _draw_schedule(
    draw: ImageDraw.ImageDraw,
    prep: dict,
    P: Palette,
    y: int,
) -> None:
    hero = prep.get("hero")
    upcoming = [event for event in prep.get("upcoming", []) if event is not hero]
    allday = prep.get("allday") or []
    y = _section_label(
        draw,
        LEFT_X0,
        LEFT_X1,
        y,
        f"LATER TODAY · {len(upcoming)}",
        P,
    )
    y += 6

    if allday:
        all_font = _tr(12, bold=True)
        titles = [str(event.get("title") or "Untitled") for event in allday]
        shown = " · ".join(titles[:2])
        if len(titles) > 2:
            shown += f" · +{len(titles) - 2} MORE"
        draw_text_clipped_bl(
            draw,
            (LEFT_X0, y + font_metrics(all_font).ascent),
            f"ALL DAY · {shown}".upper(),
            all_font,
            _accent(P, "green"),
            max_w=LEFT_X1 - LEFT_X0,
        )
        y += 24
        hr(draw, LEFT_X0, LEFT_X1, y - 3, thickness=1, fill=P.rule)

    if not upcoming:
        empty_font = _serif(18, "regular", italic=True)
        draw_text_bl(
            draw,
            (LEFT_X0, y + 7 + font_metrics(empty_font).ascent),
            "No more timed events today.",
            empty_font,
            P.ink,
        )
        return

    row_h = 50
    time_right = LEFT_X0 + 71
    body_x = LEFT_X0 + 94
    time_font = _serif(24, "bold")
    mer_font = _tr(12)
    title_font = _serif(21, "semibold")
    meta_font = _tr(12)
    max_rows = max(0, (FOOTER_TOP - 5 - y) // row_h)
    visible = upcoming[:max_rows]
    for index, event in enumerate(visible):
        row_top = y + index * row_h
        if index:
            hr(draw, LEFT_X0, LEFT_X1, row_top, thickness=1, fill=P.rule)
        color = _accent(P, KIND_ACCENT.get(event.get("kind"), "ink"))
        time_base = row_top + 7 + font_metrics(time_font).ascent
        draw_text_bl_right(
            draw,
            (time_right, time_base),
            event.get("startLabel") or "",
            time_font,
            color,
        )
        draw_text_bl(
            draw,
            (time_right - text_width(mer_font, event.get("startMer") or ""), row_top + 45),
            event.get("startMer") or "",
            mer_font,
            P.ink,
        )
        diamond(draw, body_x - 13, time_base - 8, 10, color)
        draw_text_clipped_bl(
            draw,
            (body_x, row_top + 7 + font_metrics(title_font).ascent),
            event.get("title") or "Untitled",
            title_font,
            P.ink,
            max_w=LEFT_X1 - body_x,
        )
        meta = " · ".join(
            part
            for part in (
                str(event.get("loc") or "").upper(),
                str(event.get("dur") or "").upper(),
            )
            if part
        )
        draw_text_clipped_bl(
            draw,
            (body_x, row_top + 29 + font_metrics(meta_font).ascent),
            meta,
            meta_font,
            P.ink,
            max_w=LEFT_X1 - body_x,
        )

    remaining = len(upcoming) - len(visible)
    if remaining and visible:
        more_font = _tr(12, bold=True)
        draw_text_bl_right(
            draw,
            (LEFT_X1, FOOTER_TOP - 8),
            f"+{remaining} MORE",
            more_font,
            P.ink,
        )


def _draw_priorities(
    draw: ImageDraw.ImageDraw,
    day: dict,
    P: Palette,
) -> int:
    items = ((day.get("priorities") or {}).get("items")) or []
    color = _accent(P, "red") if items else _accent(P, "green")
    y = _section_label(
        draw,
        RIGHT_X0,
        RIGHT_X1,
        BODY_TOP,
        "WHAT MATTERS",
        P,
        color=color,
    )
    if not items:
        font = _serif(18, "regular", italic=True)
        draw_text_bl(
            draw,
            (RIGHT_X0, y + 8 + font_metrics(font).ascent),
            "Nothing pressing right now.",
            font,
            P.ink,
        )
        return 279

    title_font = _tr(16, bold=True)
    detail_font = _serif(16, "regular", italic=True)
    row_h = 48
    visible = items[:3]
    for index, item in enumerate(visible):
        row_top = y + index * row_h
        if index:
            hr(draw, RIGHT_X0, RIGHT_X1, row_top, thickness=1, fill=P.rule)
        accent = _accent(P, PRIO_ACCENT.get(item.get("kind"), "ink"))
        title_base = row_top + 6 + font_metrics(title_font).ascent
        diamond(draw, RIGHT_X0 + 5, title_base - 7, 9, accent)
        draw_text_clipped_bl(
            draw,
            (RIGHT_X0 + 17, title_base),
            item.get("title") or "",
            title_font,
            P.ink,
            max_w=RIGHT_X1 - RIGHT_X0 - 17,
        )
        draw_text_clipped_bl(
            draw,
            (RIGHT_X0 + 17, row_top + 25 + font_metrics(detail_font).ascent),
            item.get("detail") or "",
            detail_font,
            P.ink,
            max_w=RIGHT_X1 - RIGHT_X0 - 17,
        )
    return 279


def _draw_glance(
    draw: ImageDraw.ImageDraw,
    day: dict,
    P: Palette,
    y: int,
) -> None:
    hr(draw, RIGHT_X0, RIGHT_X1, y, thickness=2, fill=P.rule)
    y = _section_label(draw, RIGHT_X0, RIGHT_X1, y + 9, "AT A GLANCE", P)
    weather = day.get("weather") or {}
    now = weather.get("now") or {}
    draw_weather_glyph(
        draw,
        RIGHT_X0 + 27,
        y + 28,
        39,
        now.get("code") or "cloudy",
        color=P.ink,
        bg=P.bg,
        stroke=2,
    )
    temp = now.get("temp")
    temp_font = _serif(40, "bold")
    temp_text = "--" if temp is None else f"{temp}°"
    draw_text_bl(
        draw,
        (RIGHT_X0 + 56, y + 42),
        temp_text,
        temp_font,
        _temp_color(P, temp, "now"),
    )
    label_font = _tr(12)
    label_x = RIGHT_X0 + 137
    draw_text_clipped_bl(
        draw,
        (label_x, y + 19),
        (now.get("label") or "Weather unavailable").upper(),
        label_font,
        P.ink,
        max_w=RIGHT_X1 - label_x,
    )
    hi, lo = weather.get("hi"), weather.get("lo")
    hilo = []
    if hi is not None:
        hilo.append(f"HI {hi}°")
    if lo is not None:
        hilo.append(f"LO {lo}°")
    draw_text_clipped_bl(
        draw,
        (label_x, y + 38),
        " · ".join(hilo) or "NO FORECAST",
        label_font,
        P.ink,
        max_w=RIGHT_X1 - label_x,
    )

    stats_top = y + 57
    stats_bottom = stats_top + 51
    hr(draw, RIGHT_X0, RIGHT_X1, stats_top, thickness=1, fill=P.rule)
    hr(draw, RIGHT_X0, RIGHT_X1, stats_bottom, thickness=1, fill=P.rule)
    mail = day.get("mail") or {}
    stats = (
        ("REPLY", int(((mail.get("needsReply") or {}).get("count")) or 0), "red"),
        ("AWAIT", int(mail.get("awaiting") or 0), "ink"),
        ("UNREAD", int(mail.get("unread") or 0), "blue"),
    )
    cell_w = (RIGHT_X1 - RIGHT_X0) // 3
    key_font = _tr(12, bold=True)
    value_font = _serif(27, "bold")
    for index, (key, value, accent_name) in enumerate(stats):
        cell_x0 = RIGHT_X0 + index * cell_w
        if index:
            vline(draw, cell_x0, stats_top, stats_bottom, thickness=1, fill=P.rule)
        center = cell_x0 + cell_w // 2
        value_width = text_width(value_font, str(value))
        draw_text_bl(
            draw,
            (center - value_width // 2, stats_top + 27),
            str(value),
            value_font,
            _accent(P, accent_name),
        )
        key_width = text_width(key_font, key)
        draw_text_bl(
            draw,
            (center - key_width // 2, stats_top + 44),
            key,
            key_font,
            P.ink,
        )

    status_base = stats_bottom + 7 + font_metrics(label_font).ascent
    house = day.get("house") or {}
    advisory = str(house.get("advisory") or "").strip()
    temps = house.get("temps") or {}
    if advisory:
        status = advisory.upper()
        status_color = _accent(P, "yellow")
    else:
        floors = [
            f"{label} {temps.get(key)}°"
            for label, key in (("1F", "first"), ("2F", "second"), ("3F", "third"))
            if temps.get(key) is not None
        ]
        status = "HOUSE · " + (" · ".join(floors) if floors else "QUIET")
        status_color = _accent(P, "green")
    diamond(draw, RIGHT_X0 + 5, status_base - 6, 9, status_color)
    draw_text_clipped_bl(
        draw,
        (RIGHT_X0 + 17, status_base),
        status,
        label_font,
        P.ink,
        max_w=RIGHT_X1 - RIGHT_X0 - 17,
    )


def _draw_footer(draw: ImageDraw.ImageDraw, day: dict, P: Palette) -> None:
    hr(draw, X0, X1, FOOTER_TOP, thickness=2, fill=_accent(P, "red"))
    font = _tr(12)
    fm = font_metrics(font)
    baseline = FOOTER_TOP + 8 + fm.ascent
    tomorrow = (day.get("tomorrow") or {}).get("first") or {}
    if tomorrow:
        left = " ".join(
            part
            for part in (
                "TOMORROW ·",
                str(tomorrow.get("start") or ""),
                str(tomorrow.get("title") or "").upper(),
            )
            if part
        )
    else:
        left = "TOMORROW · CLEAR"
    draw_text_clipped_bl(draw, (X0, baseline), left, font, P.ink, max_w=525)
    as_of = (day.get("asOf") or "").upper()
    refresh_text = f"  {as_of}"
    refresh_w = text_width(font, refresh_text)
    draw_refresh_glyph(draw, X1 - refresh_w - 10, baseline, size=9, fill=P.ink)
    draw_text_bl_right(draw, (X1, baseline), refresh_text, font, P.ink)


def render_dashboard(
    image: Image.Image,
    day: dict,
    P: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    """Paint the native 800x480 Day Ahead frame."""

    if image.size != (CANVAS_W, CANVAS_H):
        raise ValueError(
            f"Landscape Day Ahead requires {(CANVAS_W, CANVAS_H)}, got {image.size}"
        )
    draw = ImageDraw.Draw(image)
    prep = _prep(day)

    _draw_header(image, draw, day, P)
    hero_bottom = _draw_hero(draw, day, prep, P)
    _draw_schedule(draw, prep, P, hero_bottom)
    vline(draw, DIVIDER_X, BODY_TOP, FOOTER_TOP, thickness=2, fill=P.rule)
    glance_top = _draw_priorities(draw, day, P)
    _draw_glance(draw, day, P, glance_top)
    _draw_footer(draw, day, P)
