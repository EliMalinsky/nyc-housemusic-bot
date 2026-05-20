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
    """Extract a JSON array from text, trying multiple strategies."""
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
    dates_str = ", ".join(d.strftime("%A %B %-d %Y") for d in upcoming)

    # Step 1: search for events
    search_prompt = f"""Today is {today.strftime("%B %-d, %Y")}.

Search for NYC daytime dance music events happening on these dates: {dates_str}

Search these sources:
- ra.co/events/us/newyork (filter to daytime/afternoon)
- dice.fm NYC events
- Nowadays NYC schedule
- Public Records NYC schedule
- Knockdown Center schedule
- 718 Sessions upcoming events
- Mister Sunday at Nowadays
- Brooklyn Bridge Park events
- Prospect Park events

Also search: "Danny Krivit NYC", "Theo Parrish NYC", "Moodymann NYC", "Timmy Regisford NYC", "Louie Vega NYC", "Joe Claussell NYC", "Eamon Harkin NYC", "Justin Carter NYC", "Soul Summit NYC"

Rules: only events in NYC, starting before 8pm, on one of the listed dates, involving dance music.

You MUST respond with ONLY a JSON array. Start your response with [ and end with ]. No text before or after.

Each object must have these exact fields:
name, date, start_time, venue, neighborhood, is_outdoor, artists, description, link, priority

Example format:
[{{"name":"Event Name","date":"Saturday, May 24, 2026","start_time":"3:00 PM","venue":"Venue Name","neighborhood":"Brooklyn","is_outdoor":"true","artists":"DJ Name","description":"One sentence.","link":"https://example.com","priority":"high"}}]

If you find no events, return an empty array: []"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": search_prompt}]
    )

    full_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            full_text += block.text

    print("Raw preview:", full_text[:400])

    events = extract_json(full_text)

    # Step 2: if Claude didn't return JSON, ask it to reformat
    if events is None:
        print("JSON not found, asking Claude to reformat...")
        reformat_response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": search_prompt},
                {"role": "assistant", "content": full_text},
                {"role": "user", "content": "Please reformat your findings as a pure JSON array only. Start with [ and end with ]. No other text."}
            ]
        )
        reformat_text = ""
        for block in reformat_response.content:
            if hasattr(block, "text"):
                reformat_text += block.text
        print("Reformat preview:", reformat_text[:400])
        events = extract_json(reformat_text)

    if events is None:
        print("Could not parse events.")
        events = []

    # Filter past events
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
