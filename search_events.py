import anthropic
import resend
import json
from datetime import datetime, timedelta
import os

# ── Config ──────────────────────────────────────────────────────────────────
TO_EMAIL = "eli@elimalinsky.com"
FROM_EMAIL = "onboarding@resend.dev"  # replace with your verified Resend sender

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
    "Under the K Bridge", "any NYC park", "Prospect Park", "Central Park",
    "Brooklyn Bridge Park"
]

# ── Date helpers ─────────────────────────────────────────────────────────────
def get_date_range_string():
    today = datetime.today()
    end = today + timedelta(weeks=4)
    return f"{today.strftime('%B %-d')} through {end.strftime('%B %-d, %Y')}"

# ── Claude search ─────────────────────────────────────────────────────────────
def search_events():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    date_range = get_date_range_string()
    dj_list = ", ".join(DJS)
    venue_list = ", ".join(VENUES_AND_PROMOTERS)

    prompt = f"""Search for upcoming NYC dance music events for the dates: {date_range}.

== REQUIRED CRITERIA (every result must meet all of these) ==
- Located in New York City
- Takes place on a Saturday, Sunday, or public holiday
- Starts before 8pm (daytime or early evening events only)

== GENRE GUIDANCE (interpret broadly, do not use as keyword filters) ==
I am interested in daytime dance music events in the spirit of house, disco, soul, and Detroit. This includes — but is not limited to — events described as deep, electronic, dance, Afro, Latin, or simply "music." If a well-known DJ from my list is playing, include the event regardless of how the genre is described. If a known venue or promoter from my list is hosting an event, include it regardless of genre description. Use judgment: a Mister Sunday party or a Public Records afternoon event belongs on this list even if it doesn't say "house music."

== PREFERRED (prioritize and highlight these, but do not exclude events that lack them) ==
DJs/artists to watch for: {dj_list}

Venues and promoters to watch for: {venue_list}

Also flag events referencing: soul, disco, detroit, house, daytime, day party, outdoor

I am especially interested in outdoor events (parks, rooftops, open air).

== OUTPUT FORMAT ==
Return a JSON array. Each object must have these fields:
- name: event name
- date: date as "Saturday, June 7, 2025"
- start_time: e.g. "2:00 PM"
- venue: venue name
- neighborhood: NYC neighborhood
- is_outdoor: "true", "false", or "unknown"
- artists: DJ or artist names as a string
- description: 1-2 sentence description
- link: URL for tickets or info (or empty string)
- priority: "high" if it matches a preferred DJ or venue, otherwise "normal"

Search across: Resident Advisor (ra.co), venue websites, promoter Instagram and websites, NYC event listings, and any other relevant sources.

Return ONLY valid JSON with no preamble, explanation, or markdown formatting."""

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

    print("Raw response preview:")
    print(full_text[:1000])

    # Try to extract JSON array from anywhere in the response
    try:
        clean = full_text.strip().replace("```json", "").replace("```", "").strip()
        # Find the first [ and last ] to extract just the array
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start != -1 and end > start:
            json_str = clean[start:end]
            events = json.loads(json_str)
            print(f"Successfully parsed {len(events)} events.")
        else:
            print("No JSON array found in response.")
            events = []
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print("Full response:")
        print(full_text)
        events = []

    return events

# ── Email builder ─────────────────────────────────────────────────────────────
def group_by_date(events):
    grouped = {}
    for e in events:
        date = e.get("date", "Unknown Date")
        grouped.setdefault(date, []).append(e)
    return dict(sorted(grouped.items()))

def build_html_email(events):
    grouped = group_by_date(events)
    date_range = get_date_range_string()

    if not events:
        body = "<p>No matching events found this week. Check back next Wednesday!</p>"
    else:
        sections = []
        for date, day_events in grouped.items():
            # Sort: high priority first
            day_events.sort(key=lambda e: 0 if e.get("priority") == "high" else 1)
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

    html = f"""
    <!DOCTYPE html>
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
    </html>
    """
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
