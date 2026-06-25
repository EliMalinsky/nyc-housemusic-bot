import json
import os
import re
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path
from typing import Any

import resend
import yaml
from dateutil import parser as date_parser
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def upcoming_weekend_dates(today: date | None = None) -> list[date]:
    today = today or date.today()
    dates: list[date] = []
    d = today
    while len(dates) < 8:
        if d.weekday() in (5, 6):  # Saturday=5, Sunday=6
            dates.append(d)
        d += timedelta(days=1)
    return dates


def date_range_string(dates: list[date]) -> str:
    return f"{dates[0].strftime('%b %-d')} - {dates[-1].strftime('%b %-d, %Y')}"


def build_prompt(config: dict[str, Any], dates: list[date]) -> str:
    keywords = " ".join(config["search_keywords"])
    explicit_sources = "\n".join(f"- {s}" for s in config["explicit_sources"])
    additional_searches = "\n".join(f"- {s}" for s in config["additional_searches"])
    priority_djs = ", ".join(config["priority_djs"])
    priority_places = ", ".join(config["priority_venues_promoters"])
    weekend_dates = ", ".join(d.strftime("%A %B %-d, %Y") for d in dates)

    return f"""
You are researching NYC daytime dance music events.

Search for upcoming NYC dance music events over the next four weekends. The relevant dates are:
{weekend_dates}

Required criteria for every event:
1. Located in New York City.
2. Takes place on one of the listed Saturdays or Sundays, or a US public holiday in this date range.
3. Starts before 8:00 PM local time, or clearly has a daytime component before 8:00 PM.

Genre guidance:
Interpret broadly. The goal is daytime dance music in the spirit of house, disco, soul, Detroit, deep, electronic, Afro, Latin, funk, and dance. Do not use the genre terms as hard filters. If a priority DJ, venue, or promoter appears, include the event regardless of genre labeling.

Core keyword search string, with no quotation marks:
{keywords}

Search workflow:
First search these explicit sources/queries:
{explicit_sources}

Then run broader searches such as:
{additional_searches}

Priority DJs to flag, not filter:
{priority_djs}

Priority venues/promoters to flag, not filter:
{priority_places}
Also flag any NYC park or outdoor/open-air venue as Priority and Outdoor.

Exclude:
- Events starting at or after 8:00 PM with no daytime component.
- Events outside New York City.
- Weekday events unless they are on a US public holiday.
- Concerts that are clearly seated/non-dance events unless a priority DJ, venue, or promoter makes them relevant.

Return ONLY valid JSON. No markdown. No explanatory text.
Use this schema:
{{
  "events": [
    {{
      "event_name": "string",
      "date": "YYYY-MM-DD",
      "start_time": "HH:MM AM/PM or unknown",
      "venue": "string",
      "neighborhood": "string or unknown",
      "artists": ["string"],
      "outdoor": "yes/no/unknown",
      "priority": true,
      "priority_reason": "string or empty",
      "description": "1-2 sentence description",
      "link": "URL",
      "source": "source name or URL"
    }}
  ]
}}
""".strip()


def ask_openai(prompt: str) -> dict[str, Any]:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.responses.create(
        model="gpt-4.1-mini",
        tools=[{"type": "web_search_preview"}],
        input=prompt,
        temperature=0.2,
    )
    text = response.output_text.strip()
    return extract_json(text)


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    return json.loads(cleaned)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def parse_start_time(value: str) -> time | None:
    if not value or value.lower() == "unknown":
        return None
    try:
        return date_parser.parse(value).time()
    except Exception:
        return None


def is_before_8pm(value: str) -> bool:
    parsed = parse_start_time(value)
    if parsed is None:
        return True
    return parsed < time(20, 0)


def event_matches_priority(event: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    haystack = normalize(" ".join([
        event.get("event_name", ""),
        event.get("venue", ""),
        event.get("neighborhood", ""),
        " ".join(event.get("artists", []) or []),
        event.get("description", ""),
    ]))
    matches = []
    for item in config["priority_djs"] + config["priority_venues_promoters"]:
        if normalize(item) and normalize(item) in haystack:
            matches.append(item)
    if event.get("outdoor", "").lower() == "yes":
        matches.append("Outdoor/open-air")
    return bool(matches), ", ".join(dict.fromkeys(matches))


def clean_and_dedupe(events: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    cleaned = []
    seen = set()
    valid_dates = {d.isoformat() for d in upcoming_weekend_dates()}

    for event in events:
        event_date = str(event.get("date", "")).strip()
        if event_date not in valid_dates:
            continue
        if not is_before_8pm(str(event.get("start_time", ""))):
            continue

        key = (
            event_date,
            normalize(event.get("event_name", ""))[:80],
            normalize(event.get("venue", ""))[:80],
        )
        if key in seen:
            continue
        seen.add(key)

        priority, reason = event_matches_priority(event, config)
        event["priority"] = bool(event.get("priority") or priority)
        event["priority_reason"] = event.get("priority_reason") or reason
        cleaned.append(event)

    return sorted(cleaned, key=lambda e: (e.get("date", ""), parse_start_time(str(e.get("start_time", ""))) or time(23, 59), e.get("venue", "")))


def badge_html(event: dict[str, Any]) -> str:
    badges = []
    if event.get("priority"):
        badges.append('<span style="display:inline-block;padding:3px 8px;border-radius:999px;background:#fff3cd;color:#664d03;font-size:12px;font-weight:700;">Priority</span>')
    if str(event.get("outdoor", "")).lower() == "yes":
        badges.append('<span style="display:inline-block;padding:3px 8px;border-radius:999px;background:#d1e7dd;color:#0f5132;font-size:12px;font-weight:700;">Outdoor</span>')
    return " ".join(badges)


def render_html(events: list[dict[str, Any]], date_range: str) -> str:
    if not events:
        body = "<p>No matching events found this week.</p>"
    else:
        cards = []
        for event in events:
            artists = ", ".join(event.get("artists") or []) or "Unknown"
            link = event.get("link") or ""
            safe_link = escape(link, quote=True)
            link_html = f'<p><a href="{safe_link}">Ticket / info link</a></p>' if link else ""
            venue_line = f"{event.get('venue', 'Unknown venue')} - {event.get('neighborhood', 'unknown')}"
            cards.append(f"""
<div style="border:1px solid #ddd;border-radius:12px;padding:16px;margin:0 0 16px 0;">
  <div style="margin-bottom:8px;">{badge_html(event)}</div>
  <h2 style="font-size:20px;margin:0 0 8px 0;">{escape(event.get('event_name', 'Untitled event'))}</h2>
  <p style="margin:4px 0;"><strong>Date/time:</strong> {escape(event.get('date', 'unknown'))} at {escape(str(event.get('start_time', 'unknown')))}</p>
  <p style="margin:4px 0;"><strong>Venue:</strong> {escape(venue_line)}</p>
  <p style="margin:4px 0;"><strong>Artists/DJs:</strong> {escape(artists)}</p>
  <p style="margin:4px 0;"><strong>Outdoor:</strong> {escape(str(event.get('outdoor', 'unknown')))}</p>
  <p style="margin:8px 0;">{escape(event.get('description', ''))}</p>
  {link_html}
  <p style="font-size:12px;color:#666;margin:8px 0 0 0;">Source: {escape(event.get('source', 'unknown'))}</p>
</div>
""")
        body = "\n".join(cards)

    return f"""
<!doctype html>
<html>
  <body style="font-family:Arial,sans-serif;line-height:1.45;color:#111;max-width:720px;margin:0 auto;padding:24px;">
    <h1 style="font-size:26px;margin-bottom:4px;">NYC Music Events</h1>
    <p style="color:#555;margin-top:0;">{escape(date_range)} - {len(events)} found</p>
    {body}
  </body>
</html>
"""


def send_email(subject: str, html: str) -> None:
    resend.api_key = os.environ["RESEND_API_KEY"]
    params = {
        "from": os.environ["EMAIL_FROM"],
        "to": [os.environ["EMAIL_TO"]],
        "subject": subject,
        "html": html,
    }
    resend.Emails.send(params)


def main() -> int:
    config = load_config()
    dates = upcoming_weekend_dates()
    date_range = date_range_string(dates)
    prompt = build_prompt(config, dates)
    raw = ask_openai(prompt)
    events = clean_and_dedupe(raw.get("events", []), config)
    subject = f"NYC Music Events: {date_range} ({len(events)} found)"
    html = render_html(events, date_range)
    send_email(subject, html)
    print(subject)
    return 0
