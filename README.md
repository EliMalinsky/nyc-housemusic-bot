# NYC House Music Event Bot

A weekly GitHub Actions bot that searches for upcoming NYC daytime dance music events and sends an HTML email digest.

## What it does

Every Wednesday at 9:00 AM Eastern, the bot:

1. Searches for upcoming NYC dance music events over the next four weekends.
2. Includes only events in New York City on Saturdays, Sundays, or US public holidays that start before 8:00 PM.
3. Flags Priority events based on configured DJs, venues, and promoters.
4. Flags Outdoor events when events are outdoors, open-air, rooftop, or in a park.
5. Deduplicates results.
6. Sends a formatted HTML digest by email.

## Setup

Create these GitHub repository secrets:

- `OPENAI_API_KEY`
- `RESEND_API_KEY`
- `EMAIL_FROM`
- `EMAIL_TO`

Example:

- `EMAIL_FROM`: `NYC Music Bot <onboarding@resend.dev>` for testing, or a verified domain sender later
- `EMAIL_TO`: `eli@elimalinsky.com`

## Running manually

In GitHub, go to **Actions** -> **NYC Music Event Digest** -> **Run workflow**.

## Editing the search

Most settings live in `config.yaml`:

- Search keywords
- Priority DJs
- Priority venues/promoters
- Explicit sources to search

