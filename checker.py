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

BROOKLINE_NH = (42.7329, -71.6578)
MAX_RADIUS_MILES = 200
APP_ID = "concert-scout"

ARTISTS = [
    "Gregory Alan Isakov",
    "Josiah and the Bonnevilles",
    "Woodlock",
    "John Craigie",
    "Ocie Elliott",
    "John Vincent III",
    "Richy Mitch & The Coal Miners",
    "River Whyless",
    "Mon Rovia",
    "Monica Heldal",
    "Caamp",
    "Sons of the East",
    "James Bay",
    "Noah Kahan",
    "Lord Huron",
    "The Lumineers",
    "Mt Joy",
    "Chance Pena",
    "Nathaniel Rateliff",
]

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


def fetch_events(artist):
    url = f"https://rest.bandsintown.com/artists/{requests.utils.quote(artist)}/events?app_id={APP_ID}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Error fetching {artist}: {e}")
    return []


def send_slack(messages):
    if not messages:
        return
    text = "*🎵 New Concert Alerts*\n\n" + "\n\n".join(messages)
    requests.post(SLACK_WEBHOOK, json={"text": text})


def main():
    seen = load_seen()
    new_seen = set()
    alerts = []

    cal_service = get_calendar_service()

    for artist in ARTISTS:
        events = fetch_events(artist)
        if not isinstance(events, list):
            continue
        for event in events:
            event_id = event.get('id')
            if not event_id or event_id in seen:
                continue

            venue = event.get('venue', {})
            lat = venue.get('latitude')
            lon = venue.get('longitude')
            city = venue.get('city', '')
            region = venue.get('region', '')
            country = venue.get('country', '')
            venue_name = venue.get('name', 'Unknown Venue')
            date_str = event.get('datetime', '')
            event_url = event.get('url', '')

            if country not in ('United States', 'Canada'):
                continue

            if not lat or not lon:
                continue

            distance = haversine(BROOKLINE_NH[0], BROOKLINE_NH[1], float(lat), float(lon))
            if distance > MAX_RADIUS_MILES:
                continue

            date_display = date_str[:10] if date_str else 'TBD'
            location_display = f"{city}, {region}"

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
