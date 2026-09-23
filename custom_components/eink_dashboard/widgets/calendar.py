# Copyright 2026 Andreas Schneider
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Calendar widget context builder."""

from __future__ import annotations

from datetime import date, datetime

from ..const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ._helpers import (
    _color_context,
    _title_layout,
    _widget_dim,
)

# Layout constants for the agenda-style calendar (fixed pixel sizes
# for consistent legibility on e-ink at any widget height).
_GROUP_HEADING_SZ = 15
_GROUP_HEADING_ADVANCE = 24
_HERO_TIME_SZ = 54
_HERO_TIME_ADVANCE = 62
_HERO_SUMMARY_SZ = 28
_HERO_SUMMARY_ADVANCE = 36
_HERO_INTRO_GAP = 4
_EVENT_ROW_SZ = 24
_EVENT_ROW_ADVANCE = 34
_EVENT_TIME_COL_W = 90
_SECTION_GAP = 18
_LINE_GAP = 8

# Curated "Next appointment" translations.  Languages missing here
# fall back to English; no attempt is made at automatic translation.
_NEXT_APPT_HEADINGS: dict[str, str] = {
    "en": "NEXT APPOINTMENT",
    "de": "NÄCHSTER TERMIN",
    "fr": "PROCHAIN RENDEZ-VOUS",
    "es": "PRÓXIMA CITA",
    "it": "PROSSIMO APPUNTAMENTO",
    "nl": "VOLGENDE AFSPRAAK",
    "pt": "PRÓXIMO COMPROMISSO",
    "da": "NÆSTE AFTALE",
    "sv": "NÄSTA MÖTE",
    "nb": "NESTE AVTALE",
}


def _next_appointment_heading(language: str) -> str:
    """Return the localized "next appointment" heading."""
    lang = language.split("-")[0].lower()
    return _NEXT_APPT_HEADINGS.get(lang, _NEXT_APPT_HEADINGS["en"])


def _fmt_time(hm: tuple[int, int] | None, time_format: str) -> str:
    """Return an ``HH:MM`` (or 12-hour) label for a parsed start time."""
    if hm is None:
        return ""
    hour, minute = hm
    if time_format == "12":
        ampm = "AM" if hour < 12 else "PM"
        h12 = hour % 12 or 12
        return f"{h12}:{minute:02d} {ampm}"
    return f"{hour}:{minute:02d}"


def _group_heading_for(
    event_date: date, today: date, language: str
) -> str:
    """Return the uppercase group heading for an event date.

    Uses relative labels ("TODAY"/"TOMORROW", localized) for the
    two nearest days, weekday abbreviations for the following
    week, and an abbreviated month + day beyond that.
    """
    from ..render import (
        _month_abbrev,
        _relative_day_phrases,
        _weekday_abbrev,
    )

    delta = (event_date - today).days
    today_phrase, tomorrow_phrase, _ = _relative_day_phrases(language)
    if delta <= 0:
        return today_phrase.upper()
    if delta == 1:
        return tomorrow_phrase.upper()
    if 2 <= delta < 7:
        return _weekday_abbrev(event_date, language).upper()
    return f"{_month_abbrev(event_date, language)} {event_date.day}".upper()


def _truncate_to_width(text: str, font_sz: int, max_w: int) -> str:
    """Truncate a string to fit ``max_w`` pixels at ``font_sz``.

    Uses a coarse Roboto width heuristic (~0.55 × font size per
    glyph).  When truncation happens an ellipsis is appended.
    """
    if max_w <= 0 or not text:
        return text
    char_w = max(1.0, font_sz * 0.55)
    max_chars = int(max_w // char_w)
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"
    return text[: max_chars - 1].rstrip() + "…"


def _build_calendar_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the calendar widget.

    Renders upcoming calendar events as a minimalist agenda:
    a hero block highlighting the next event with a large,
    bold start time and its title, followed by compact rows
    of remaining events grouped by day.  Events are sourced
    from ``states[entity_id]["attributes"]["events"]``, which
    is injected by ``_fetch_calendar_events()`` before rendering.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (calendar entity ID),
            ``max_events`` (int, default 5),
            ``title`` (optional header string),
            ``bold_value`` (accepted for backward compat;
            no visual effect in the agenda layout),
            ``card_style`` (accepted for backward compat;
            no visual effect in the agenda layout),
            ``x``, ``w``, ``h``.
        config: Display config with ``states``,
            ``display_levels``, ``time_format``, and ``language``.

    Returns:
        Template context dict consumed by
        ``calendar.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the
        entity is absent, events list is empty, or no events
        remain after capping at ``max_events``.
    """
    from ..render import (
        _get_today,
        _is_event_now,
        _parse_calendar_dt,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    max_events: int = int(widget.get("max_events", 5))
    title: str = widget.get("title", "")
    time_format: str = config.get("time_format", "24")
    language: str = config.get("language", "en")
    states = config.get("states", {})
    display_levels = config.get("display_levels", 16)

    empty_ctx: dict[str, object] = {
        "w": svg_w,
        "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
        "has_rows": False,
        **_color_context(),
    }

    if not entity_id:
        return empty_ctx

    entity_state = states.get(entity_id)
    if entity_state is None:
        return empty_ctx

    attrs = entity_state.get("attributes", {})
    raw_events: list[dict[str, object]] = attrs.get("events", [])

    if not raw_events:
        return empty_ctx

    visible = list(raw_events[:max_events])
    if not visible:
        return empty_ctx

    today = _get_today()
    now = datetime.now()

    # Content area within the widget, honouring PADDING left/right.
    lpad = PADDING
    rpad = PADDING
    content_w = max(1, svg_w - lpad - rpad)

    # Hero (first, most urgent event).
    first = visible[0]
    first_start = str(first.get("start", ""))
    first_end = str(first.get("end", ""))
    first_summary = str(first.get("summary", ""))
    first_all_day = bool(first.get("all_day", False))
    first_date, first_hm = _parse_calendar_dt(first_start)
    first_is_now = _is_event_now(first_start, first_end, now)

    hero_time = _fmt_time(first_hm, time_format)
    hero_is_now = first_is_now and bool(hero_time)
    hero_summary = _truncate_to_width(
        first_summary, _HERO_SUMMARY_SZ, content_w
    )
    hero_context_label = _group_heading_for(first_date, today, language)
    hero_heading = _next_appointment_heading(language)

    # Remaining events, grouped by their day heading.  Order is
    # preserved from the input (no re-sorting).
    groups: list[dict[str, object]] = []
    time_col_w = _EVENT_TIME_COL_W
    summary_col_w = max(1, content_w - time_col_w - _LINE_GAP)
    for event in visible[1:]:
        start = str(event.get("start", ""))
        summary = str(event.get("summary", ""))
        all_day = bool(event.get("all_day", False))
        event_date, hm = _parse_calendar_dt(start)
        heading = _group_heading_for(event_date, today, language)
        time_text = "" if all_day else _fmt_time(hm, time_format)
        row = {
            "time": time_text,
            "summary": _truncate_to_width(
                summary, _EVENT_ROW_SZ, summary_col_w
            ),
        }
        if not groups or groups[-1]["heading"] != heading:
            groups.append({"heading": heading, "rows": [row]})
        else:
            rows_list: list[dict[str, str]] = groups[-1]["rows"]  # type: ignore[assignment]
            rows_list.append(row)

    # Layout: walk top-down assigning y coordinates to each block.
    # svg_h is honoured when the user set an explicit height,
    # otherwise the natural content height is used.
    y = 0

    # Optional widget title reserves a title strip at the top.
    show_title = bool(title)
    if show_title:
        # _title_layout expects an svg_h; compute natural body
        # height first and derive title advance from it below.
        pass

    hero_heading_y = 0
    hero_time_y = 0
    hero_summary_y = 0
    y += _GROUP_HEADING_ADVANCE  # hero heading
    hero_time_y = y + _HERO_INTRO_GAP
    if hero_time:
        y = hero_time_y + _HERO_TIME_ADVANCE
    else:
        y = hero_time_y
    hero_summary_y = y
    y += _HERO_SUMMARY_ADVANCE

    if groups:
        y += _SECTION_GAP

    for group in groups:
        group["heading_y"] = y
        y += _GROUP_HEADING_ADVANCE
        rows_list = group["rows"]  # type: ignore[assignment]
        for row in rows_list:
            row["y"] = y
            y += _EVENT_ROW_ADVANCE
        y += _LINE_GAP
    if groups:
        # Drop the trailing gap after the last group.
        y -= _LINE_GAP

    natural_body = y + _LINE_GAP  # small bottom breathing room

    # Reserve title space above the agenda body when requested.
    if show_title:
        title_font_sz, content_y, _content_h = _title_layout(
            title, natural_body + 40
        )
        title_advance = content_y
    else:
        title_font_sz = 0
        title_advance = 0

    svg_h = _widget_dim(widget, "h", natural_body + title_advance)

    # Shift all agenda y positions below the title strip.
    hero_heading_y += title_advance
    hero_time_y += title_advance
    hero_summary_y += title_advance
    for group in groups:
        group["heading_y"] = int(group["heading_y"]) + title_advance
        for row in group["rows"]:  # type: ignore[assignment]
            row["y"] = int(row["y"]) + title_advance

    # Optional thin divider lines between date groups.  On 2-level
    # displays widen the stroke so the dither still reads as a
    # solid rule.
    divider_stroke_w = 3 if display_levels <= 2 else 1

    hex_black = color_to_hex(COLOR_BLACK)
    hex_gray = color_to_hex(COLOR_GRAY)
    hex_light_gray = color_to_hex(COLOR_LIGHT_GRAY)

    return {
        "w": svg_w,
        "h": svg_h,
        "has_rows": True,
        "title": title,
        "title_font_sz": title_font_sz,
        "lpad": lpad,
        "content_w": content_w,
        "time_col_w": time_col_w,
        # Hero block.
        "hero_heading": hero_heading,
        "hero_context_label": hero_context_label,
        "hero_heading_y": hero_heading_y,
        "hero_time": hero_time,
        "hero_time_y": hero_time_y,
        "hero_time_sz": _HERO_TIME_SZ,
        "hero_summary": hero_summary,
        "hero_summary_y": hero_summary_y,
        "hero_summary_sz": _HERO_SUMMARY_SZ,
        "hero_is_now": hero_is_now,
        # Group heading + row typography.
        "group_heading_sz": _GROUP_HEADING_SZ,
        "event_row_sz": _EVENT_ROW_SZ,
        # Groups of remaining events.
        "groups": groups,
        # Colors.
        "hex_black": hex_black,
        "hex_gray": hex_gray,
        "hex_light_gray": hex_light_gray,
        "divider_stroke_w": divider_stroke_w,
        **_color_context(),
    }
