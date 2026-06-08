import os
import json
import requests
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Configuration ---
SLACK_WEBHOOK = os.environ['SLACK_WEBHOOK']
GOOGLE_CALENDAR_ID = os.environ['GOOGLE_CALENDAR_ID']
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']
WORKER_URL = "https://concert-scout.trekking-higher.workers.dev/"

BROOKLINE_NH = (42.7329, -71.6578)
MAX_RADIUS_MILES = 200

EXCLUDED_CITIES = {
    'New York (NYC)', 'Queens', 'Bronx', 'Brooklyn', 'Manhattan', 'Flushing',
    'Long Island City', 'Astoria', 'Staten Island'
}

SEEN_FILE = "seen_events.json"


def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, 'w') as f:
        json.dump(list(seen), f)


def get_calendar_service():
    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    return build('calendar', 'v3', credentials=creds)


def add_to_calendar(service, artist, venue_name, location_display, date_str, event_url):
    try:
        date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        event = {
            'summary': f'🎵 Concert Alert: {artist} @ {venue_name}',
            'location': location_display,
            'description': f'Ticket link: {event_url}',
            'start': {'date': str(date)},
            'end': {'date': str(date)},
            'colorId': '5',
        }
        service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        return True
    except Exception as e:
        print(f"Calendar error for {artist}: {e}")
        return False


def send_slack(messages):
    if messages:
        text = "*🎵 New Concert Alerts*\n\n" + "\n\n".join(messages)
    else:
        text = "✅ Concert Scout ran — no new shows found within range."
    requests.post(SLACK_WEBHOOK, json={"text": text})


def main():
    seen = load_seen()
    new_seen = set()
    alerts = []

    print("Fetching shows from Worker...")
    try:
        r = requests.get(WORKER_URL, timeout=60)
        data = r.json()
        all_shows = data.get('shows', [])
        print(f"Worker returned {len(all_shows)} total shows across all artists")
    except Exception as e:
        print(f"Worker error: {e}")
        return

    cal_service = get_calendar_service()

    for show in all_shows:
        artist = show.get('artist', '')
        event_url = show.get('url', '')
        event_id = event_url

        if not event_id or event_id in seen:
            continue

        lat = show.get('lat')
        lon = show.get('lon')
        if not lat or not lon:
            continue

        country = show.get('country', '')
        if country not in ('US', 'United States', 'Canada'):
            continue

        city = show.get('city', '')
        if city in EXCLUDED_CITIES:
            continue

        distance = haversine(BROOKLINE_NH[0], BROOKLINE_NH[1], float(lat), float(lon))
        if distance > MAX_RADIUS_MILES:
            continue

        venue_name = show.get('venue', 'Unknown Venue')
        region = show.get('region', '')
        date_str = show.get('date', '')
        location_display = f"{city}, {region}"
        date_display = date_str[:10] if date_str else 'TBD'

        add_to_calendar(cal_service, artist, venue_name, location_display, date_str, event_url)

        alert = (
            f"*{artist}*\n"
            f"📍 {venue_name} — {location_display}\n"
            f"📅 {date_display}\n"
            f"📏 {int(distance)} miles away\n"
            f"🎟 {event_url}"
        )
        alerts.append(alert)
        new_seen.add(event_id)

    save_seen(seen | new_seen)
    send_slack(alerts)
    print(f"Done. {len(alerts)} new shows found.")


if __name__ == "__main__":
    main()
