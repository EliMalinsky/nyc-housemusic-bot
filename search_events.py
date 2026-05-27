import anthropic
import resend
import json
from datetime import datetime, timedelta
import os

TO_EMAIL = "eli@elimalinsky.com"
FROM_EMAIL = "onboarding@resend.dev"

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

def extract_json(text):
    text = text.strip().replace("```json","").replace("```","").strip()
    s, e = text.find("["), text.rfind("]") + 1
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e])
        except:
            pass
    return None

def search_events():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.today().date()
    upcoming = get_upcoming_weekend_dates()
    dates_str = ", ".join(d.strftime("%A, %B %-d, %Y") for d in upcoming)

    prompt = f"""Today is {today.strftime("%A, %B %-d, %Y")}.

Search for NYC daytime dance music events on ALL of these weekend dates — search each date individually, not just the nearest one:
{dates_str}

Search these sources:
- ra.co/events/us/newyork
- dice.fm NYC
- Nowadays NYC (nowadaysnyc.com)
- Public Records NYC
- Knockdown Center
- 718 Sessions
- Mister Sunday
- Brooklyn Bridge Park events
- Prospect Park events
- Soul in the Horn

Also search for NYC weekend appearances by: Danny Krivit, Theo Parrish, Moodymann, Timmy Regisford, Louie Vega, Joe Claussell, Eamon Harkin, Justin Carter, Soul Summit, Francois K, DJ Spinna

Only include events that: start before 8pm, are in NYC, are on one of the listed dates, involve dance music (house/disco/soul/funk/electronic — interpret broadly).

Return ONLY a JSON array. No text before or after. Start with [ and end with ].

Each object must have: name, date (format: "Saturday, May 24, 2026"), start_time, venue, neighborhood, is_outdoor (true/false/unknown), artists, description (1 sentence), link, priority (high if matches a listed DJ/venue, else normal).

If you find no events return []."""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )

    full_text = "".join(b.text for b in response.content if hasattr(b, "text"))
    print("Preview:", full_text[:300])

    events = extract_json(full_text)

    # Fallback: ask Claude to reformat if it returned prose
    if events is None:
        print("Reformatting...")
        reformat = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": "Convert the following event listing text into a JSON array. Output ONLY the JSON array. Start with [ and end with ]. No other text.\n\n" + full_text[:8000]}
            ]
        )
        reformat_text = "".join(b.text for b in reformat.content if hasattr(b, "text"))
        print("Reformat preview:", reformat_text[:300])
        events = extract_json(reformat_text) or []

    events = [e for e in events if (parse_event_date(e.get("date","")) or today) >= today]
    print(f"Found {len(events)} future events.")
    return events

def sort_key(e):
    d = parse_event_date(e.get("date","")) or datetime.max.date()
    try:
        t = datetime.strptime(e.get("start_time","12:00 PM").strip(), "%I:%M %p").time()
    except:
        t = datetime.min.time()
    return (d, t)

def build_html_email(events):
    date_range = get_date_range_string()
    if not events:
        body = "<p style='color:#555;'>No matching events found. Check back next Wednesday!</p>"
    else:
        grouped = {}
        for e in sorted(events, key=sort_key):
            grouped.setdefault(e.get("date","Unknown"), []).append(e)
        sections = []
        for date, day_events in grouped.items():
            cards = []
            for e in day_events:
                badges = ""
                if str(e.get("is_outdoor","")).lower() == "true":
                    badges += ' <span style="background:#d4edda;color:#155724;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:700;">🌳 Outdoors</span>'
                if e.get("priority") == "high":
                    badges += ' <span style="background:#fff3cd;color:#856404;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:700;">⭐ Priority</span>'
                artists = e.get("artists","")
                if isinstance(artists, list):
                    artists = ", ".join(artists)
                link = e.get("link","")
                cards.append(f"""<div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:10px;background:#fff;">
  <div style="font-size:15px;font-weight:700;color:#111;">{e.get('name','')}{badges}</div>
  <div style="color:#555;font-size:13px;margin:4px 0;">🕐 {e.get('start_time','')} &nbsp;·&nbsp; 📍 {e.get('venue','')}, {e.get('neighborhood','')}</div>
  {"<div style='color:#444;font-size:12px;'>🎧 " + artists + "</div>" if artists else ""}
  <div style="color:#666;font-size:12px;margin-top:5px;">{e.get('description','')}</div>
  {"<div style='margin-top:7px;'><a href='" + link + "' style='color:#1a73e8;font-size:12px;'>More info →</a></div>" if link else ""}
</div>""")
            sections.append(f"""<div style="margin-bottom:22px;">
  <h2 style="font-size:16px;font-weight:800;color:#111;border-bottom:2px solid #111;padding-bottom:4px;margin-bottom:10px;">{date}</h2>
  {''.join(cards)}</div>""")
        body = "".join(sections)

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;background:#f5f5f5;">
  <div style="background:#111;color:#fff;padding:16px 20px;border-radius:8px;margin-bottom:18px;">
    <div style="font-size:19px;font-weight:900;">🎶 NYC Music Events</div>
    <div style="font-size:12px;color:#aaa;margin-top:3px;">House · Disco · Soul · Detroit &nbsp;|&nbsp; {date_range}</div>
  </div>
  {body}
  <div style="margin-top:20px;font-size:11px;color:#999;text-align:center;border-top:1px solid #ddd;padding-top:12px;">Sent every Wednesday. Daytime weekend events only.</div>
</body></html>"""

def send_email(html, count):
    resend.api_key = os.environ["RESEND_API_KEY"]
    subject = f"NYC Music Events: {get_date_range_string()} ({count} found)"
    resend.Emails.send({"from": FROM_EMAIL, "to": TO_EMAIL, "subject": subject, "html": html})
    print(f"Sent: {subject}")

if __name__ == "__main__":
    print("Searching...")
    events = search_events()
    send_email(build_html_email(events), len(events))
