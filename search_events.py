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
    'Joaquin "Joe" Claussell', "Joe Claussell", "Motor City Drum Ensemble",
    "Danny Krivit", "Anané", "Louie Vega", "Little Louie Vega", "Move D",
    "Larry Heard", "Mr. Fingers", "Mike Huckaby", "Saint James Joy", "Ali Coleman"
]

VENUES_AND_PROMOTERS = [
    "Public Records", "Shelter", "Soul in the Horn", "Mister Sunday",
    "Nowadays", "718 Sessions", "ReSolute", "Refuge", "Knockdown Center",
    "Under the K Bridge", "Prospect Park", "Central Park", "Brooklyn Bridge Park"
]

# ── Date helpers ─────────────────────────────────────────────────────────────
def get_upcoming_weekend_dates():
    """Return list of upcoming Saturday/Sunday dates (from today onwards) for next 4 weekends."""
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
    start = dates[0].strftime("%B %-d")
    end = dates[-1].strftime("%B %-d, %Y")
    return f"{start} through {end}"

def parse_event_date(date_str):
    """Try to parse a date string into a date object for sorting/filtering."""
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None

def is_future_event(date_str):
    """Return True if event date is today or in the future."""
    today = datetime.today().date()
    d = parse_event_date(date_str)
    return d is not None and d >= today

# ── Claude search ─────────────────────────────────────────────────────────────
def run_search(client, search_focus, date_range, weekend_dates_str):
    """Run a single targeted search and return raw events list."""
    prompt = f"""Today's date is {datetime.today().strftime("%A, %B %-d, %Y")}.

Search for upcoming NYC daytime dance music events. I want events on these specific dates ONLY: {weekend_dates_str}

SEARCH FOCUS FOR THIS QUERY: {search_focus}

== REQUIRED (every result must meet all of these) ==
- Located in New York City
- Date must be one of the dates listed above (no past events)
- Starts before 8pm

== GENRE (interpret broadly) ==
House, disco, soul, Detroit — but also any daytime dance party, electronic, Afro, Latin. Use judgment: if a known DJ or venue from my lists is involved, include it regardless of how the genre is labeled.

== OUTPUT ==
Return a JSON array. Each object must have:
- name: event name
- date: format exactly as "Saturday, June 7, 2026"
- start_time: e.g. "3:00 PM"
- venue
- neighborhood
- is_outdoor: "true", "false", or "unknown"
- artists: performing DJs/artists as a string
- description: 1-2 sentences
- link: URL or empty string
- priority: "high" if matches a known DJ/venue from my lists, else "normal"

Return ONLY a valid JSON array. No explanation, no markdown."""

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

    try:
        clean = full_text.strip().replace("```json", "").replace("```", "").strip()
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(clean[start:end])
    except Exception as e:
        print(f"Parse error: {e}")
    return []

def search_events():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    upcoming = get_upcoming_weekend_dates()
    weekend_dates_str = ", ".join(d.strftime("%A, %B %-d, %Y") for d in upcoming)
    date_range = get_date_range_string()
    dj_list = ", ".join(DJS)
    venue_list = ", ".join(VENUES_AND_PROMOTERS)

    # Run multiple targeted searches for better coverage
    searches = [
        f"Priority venues and promoters: {venue_list}. Search each venue's website, Instagram, and RA page for daytime weekend events.",
        f"Priority DJs: {dj_list}. Search for any NYC appearances by these artists on upcoming weekends.",
        f"General NYC daytime dance music: search Resident Advisor ra.co for NYC events, Dice.fm, and NYC event blogs for daytime house, disco, soul parties on upcoming weekends.",
    ]

    all_events = []
    seen = set()

    for i, focus in enumerate(searches):
        if i > 0:
            import time
            time.sleep(60)  # wait 60 seconds between searches to avoid rate limits
        print(f"Running search: {focus[:60]}...")
        results = run_search(client, focus, date_range, weekend_dates_str)
        for e in results:
            # Deduplicate by name+date
            key = (e.get("name", "").lower().strip(), e.get("date", "").strip())
            if key not in seen:
                seen.add(key)
                all_events.append(e)

    # Filter out past events
    today = datetime.today().date()
    all_events = [e for e in all_events if is_future_event(e.get("date", ""))]

    print(f"Total unique future events found: {len(all_events)}")
    return all_events

# ── Email builder ─────────────────────────────────────────────────────────────
def sort_events_by_date(events):
    """Sort events chronologically."""
    def sort_key(e):
        d = parse_event_date(e.get("date", ""))
        t_str = e.get("start_time", "12:00 PM")
        try:
            t = datetime.strptime(t_str.strip(), "%I:%M %p").time()
        except:
            try:
                t = datetime.strptime(t_str.strip(), "%I %p").time()
            except:
                t = datetime.min.time()
        return (d or datetime.max.date(), t)
    return sorted(events, key=sort_key)

def group_by_date(events):
    grouped = {}
    for e in events:
        date = e.get("date", "Unknown Date")
        grouped.setdefault(date, []).append(e)
    return grouped

def build_html_email(events):
    date_range = get_date_range_string()

    if not events:
        body = "<p>No matching events found this week. Check back next Wednesday!</p>"
    else:
        # Sort all events chronologically first
        sorted_events = sort_events_by_date(events)
        # Then group by date (preserving order)
        grouped = {}
        for e in sorted_events:
            date = e.get("date", "Unknown Date")
            grouped.setdefault(date, []).append(e)

        sections = []
        for date, day_events in grouped.items():
            cards = []
            for e in day_events:
                outdoor_badge = (
                    ' <span style="background:#d4edda;color:#155724;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600;">🌳 Outdoors</span>'
                    if str(e.get("is_outdoor", "")).lower() == "true" else ""
                )
                priority_badge = (
                    ' <span style="background:#fff3cd;color:#856404;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600;">⭐ Priority</span>'
                    if e.get("priority") == "high" else ""
                )
                artists = e.get("artists", "")
                artist_line = f'<div style="color:#555;font-size:14px;margin:4px 0;">🎧 {artists}</div>' if artists else ""
                link = e.get("link", "")
                link_line = f'<div style="margin-top:8px;"><a href="{link}" style="color:#1a73e8;font-size:13px;">More info →</a></div>' if link else ""

                cards.append(f"""
                <div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin-bottom:12px;background:#fff;">
                    <div style="font-size:16px;font-weight:700;color:#111;">{e.get('name','')}{outdoor_badge}{priority_badge}</div>
                    <div style="color:#444;font-size:14px;margin:4px 0;">🕐 {e.get('start_time','')} &nbsp;|&nbsp; 📍 {e.get('venue','')}, {e.get('neighborhood','')}</div>
                    {artist_line}
                    <div style="color:#666;font-size:13px;margin-top:6px;">{e.get('description','')}</div>
                    {link_line}
                </div>""")

            sections.append(f"""
            <div style="margin-bottom:28px;">
                <h2 style="font-size:18px;font-weight:800;color:#111;border-bottom:2px solid #111;padding-bottom:6px;margin-bottom:12px;">{date}</h2>
                {''.join(cards)}
            </div>""")

        body = "".join(sections)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px;background:#f9f9f9;color:#111;">

    <div style="background:#111;color:#fff;padding:20px 24px;border-radius:8px;margin-bottom:24px;">
        <div style="font-size:22px;font-weight:900;letter-spacing:-0.5px;">🎶 NYC Music Events</div>
        <div style="font-size:13px;color:#aaa;margin-top:4px;">House · Disco · Soul · Detroit &nbsp;|&nbsp; {date_range}</div>
    </div>

    {body}

    <div style="margin-top:32px;font-size:12px;color:#999;text-align:center;border-top:1px solid #e0e0e0;padding-top:16px;">
        Sent every Wednesday. Daytime weekend events only.
    </div>

</body>
</html>"""
    return html

# ── Send email ────────────────────────────────────────────────────────────────
def send_email(html_body, event_count):
    resend.api_key = os.environ["RESEND_API_KEY"]
    date_range = get_date_range_string()
    subject = f"NYC Music Events: {date_range} ({event_count} found)"
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": TO_EMAIL,
        "subject": subject,
        "html": html_body
    })
    print(f"Email sent: {subject}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Searching for events...")
    events = search_events()
    print(f"Found {len(events)} events.")
    html = build_html_email(events)
    send_email(html, len(events))
