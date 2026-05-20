import anthropic
import resend
import json
from datetime import datetime, timedelta
import os

# ── Config ──────────────────────────────────────────────────────────────────
TO_EMAIL = "eli@elimalinsky.com"
FROM_EMAIL = "onboarding@resend.dev"

DJS = [
    "Moodymann", "Moodyman", "Kenny Dixon Junior", "Theo Parrish", "Rick Wade",
    "Soul Summit", "Timmy Regisford", "Tony Humphries", "Eli Escobar",
    "Justin Carter", "Eamon Harkin", "Kai Alce", "François K", "DJ Spinna",
    "Joe Claussell", "Motor City Drum Ensemble", "Danny Krivit", "Anané",
    "Louie Vega", "Move D", "Larry Heard", "Mr. Fingers", "Mike Huckaby",
    "Saint James Joy", "Ali Coleman"
]

VENUES = [
    "Public Records", "Shelter", "Soul in the Horn", "Mister Sunday",
    "Nowadays", "718 Sessions", "ReSolute", "Knockdown Center",
    "Prospect Park", "Central Park", "Brooklyn Bridge Park"
]

# ── Date helpers ─────────────────────────────────────────────────────────────
def get_upcoming_weekend_dates():
    today = datetime.today().date()
    dates = []
    d = today
    while len(dates) < 8:
        if d.weekday() in (5, 6):
            dates.append(d)
        d += timedelta(days=1)
    return dates

def get_date_range_string():
    dates = get_upcoming_weekend_dates()
    return f"{dates[0].strftime('%B %-d')} through {dates[-1].strftime('%B %-d, %Y')}"

def parse_event_date(date_str):
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None

# ── Search ────────────────────────────────────────────────────────────────────
def search_events():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.today().date()
    upcoming = get_upcoming_weekend_dates()
    weekend_dates_str = ", ".join(d.strftime("%A, %B %-d, %Y") for d in upcoming)
    dj_list = ", ".join(DJS)
    venue_list = ", ".join(VENUES)

    prompt = f"""Today is {today.strftime("%A, %B %-d, %Y")}.

Search for NYC daytime dance music events on these upcoming weekend dates: {weekend_dates_str}

Search these sources thoroughly:
1. ra.co (Resident Advisor) - search NYC events filtered to daytime
2. dice.fm - search NYC events
3. Each of these venue/promoter pages: {venue_list}
4. Search for NYC appearances by any of these DJs: {dj_list}

RULES - only include events that meet ALL of these:
- In New York City
- On one of the listed dates (no past events)
- Starts before 8pm
- Dance music (house, disco, soul, funk, electronic, Afro, Latin — interpret broadly)

For each event return a JSON object with:
- name
- date (format: "Saturday, May 24, 2026")
- start_time (format: "3:00 PM")
- venue
- neighborhood
- is_outdoor ("true"/"false"/"unknown")
- artists (string of DJ/artist names)
- description (1-2 sentences)
- link (URL or "")
- priority ("high" if matches a listed DJ or venue, else "normal")

Return ONLY a valid JSON array, no markdown, no explanation."""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )

    full_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            full_text += block.text

    print("Response preview:", full_text[:300])

    try:
        clean = full_text.strip().replace("```json", "").replace("```", "").strip()
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start != -1 and end > start:
            events = json.loads(clean[start:end])
        else:
            print("No JSON array found.")
            events = []
    except Exception as e:
        print(f"Parse error: {e}")
        events = []

    # Filter out past events
    events = [e for e in events if (parse_event_date(e.get("date", "")) or today) >= today]
    print(f"Found {len(events)} future events.")
    return events

# ── Email ─────────────────────────────────────────────────────────────────────
def sort_key(e):
    d = parse_event_date(e.get("date", "")) or datetime.max.date()
    try:
        t = datetime.strptime(e.get("start_time", "12:00 PM").strip(), "%I:%M %p").time()
    except:
        t = datetime.min.time()
    return (d, t)

def build_html_email(events):
    date_range = get_date_range_string()

    if not events:
        body = "<p style='color:#555;'>No matching events found this week. Check back next Wednesday!</p>"
    else:
        sorted_events = sorted(events, key=sort_key)
        grouped = {}
        for e in sorted_events:
            grouped.setdefault(e.get("date", "Unknown"), []).append(e)

        sections = []
        for date, day_events in grouped.items():
            cards = []
            for e in day_events:
                outdoor = str(e.get("is_outdoor", "")).lower() == "true"
                priority = e.get("priority") == "high"
                badges = ""
                if outdoor:
                    badges += ' <span style="background:#d4edda;color:#155724;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;">🌳 Outdoors</span>'
                if priority:
                    badges += ' <span style="background:#fff3cd;color:#856404;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;">⭐ Priority</span>'
                artists = e.get("artists", "")
                link = e.get("link", "")
                cards.append(f"""<div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin-bottom:10px;background:#fff;">
  <div style="font-size:15px;font-weight:700;color:#111;">{e.get('name','')}{badges}</div>
  <div style="color:#555;font-size:13px;margin:5px 0;">🕐 {e.get('start_time','')} &nbsp;·&nbsp; 📍 {e.get('venue','')}, {e.get('neighborhood','')}</div>
  {"<div style='color:#444;font-size:13px;'>🎧 " + artists + "</div>" if artists else ""}
  <div style="color:#666;font-size:12px;margin-top:6px;">{e.get('description','')}</div>
  {"<div style='margin-top:8px;'><a href='" + link + "' style='color:#1a73e8;font-size:12px;'>More info →</a></div>" if link else ""}
</div>""")
            sections.append(f"""<div style="margin-bottom:24px;">
  <h2 style="font-size:17px;font-weight:800;color:#111;border-bottom:2px solid #111;padding-bottom:5px;margin-bottom:10px;">{date}</h2>
  {''.join(cards)}
</div>""")
        body = "".join(sections)

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;background:#f5f5f5;color:#111;">
  <div style="background:#111;color:#fff;padding:18px 20px;border-radius:8px;margin-bottom:20px;">
    <div style="font-size:20px;font-weight:900;">🎶 NYC Music Events</div>
    <div style="font-size:12px;color:#aaa;margin-top:3px;">House · Disco · Soul · Detroit &nbsp;|&nbsp; {date_range}</div>
  </div>
  {body}
  <div style="margin-top:24px;font-size:11px;color:#999;text-align:center;border-top:1px solid #ddd;padding-top:12px;">
    Sent every Wednesday. Daytime weekend events only.
  </div>
</body></html>"""

# ── Send ──────────────────────────────────────────────────────────────────────
def send_email(html_body, event_count):
    resend.api_key = os.environ["RESEND_API_KEY"]
    subject = f"NYC Music Events: {get_date_range_string()} ({event_count} found)"
    resend.Emails.send({"from": FROM_EMAIL, "to": TO_EMAIL, "subject": subject, "html": html_body})
    print(f"Email sent: {subject}")

if __name__ == "__main__":
    print("Searching for events...")
    events = search_events()
    html = build_html_email(events)
    send_email(html, len(events))
