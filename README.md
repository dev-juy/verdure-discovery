# Verdure Discovery Engine

Background service that pulls local events from public feeds and organizer submissions, cleans and dedupes them, and builds a ranked, explained feed for every user. It runs on its own schedule with no UI: your app reads the JSON files it writes.

## Directory tree

```
verdure-discovery/
├── run.py                        # entry point: auto-updating loop, --once, --rerank
├── config.yaml                   # region, schedule, sources, ranking weights
├── requirements.txt
├── README.md
├── verdure/
│   ├── __init__.py
│   ├── models.py                 # standard Event format + category inference
│   ├── validate.py               # listing validation rules + quality score
│   ├── dedupe.py                 # cross-source duplicate detection and merging
│   ├── geo.py                    # distance math + named neighborhood centers
│   ├── store.py                  # JSON event store (first/last seen tracking)
│   ├── users.py                  # profiles, feedback learning, per-user state
│   ├── ranking.py                # filters -> score -> diversity re-rank -> reasons
│   ├── pipeline.py               # one full refresh, plus feed/report writers
│   └── sources/
│       ├── __init__.py           # adapter registry
│       ├── base.py               # Source base class
│       ├── ical.py               # any .ics feed (Localist, CivicPlus, libraries)
│       ├── livewhale.py          # LiveWhale JSON (Santa Clara University)
│       ├── ticketmaster.py       # Ticketmaster Discovery API
│       └── submissions.py        # organizer JSON drop folder
├── data/
│   ├── users/
│   │   └── example_family.json   # sample user profile
│   └── submissions/
│       └── example_storytime.json# sample organizer submission
├── tests/
│   └── test_engine.py
└── output/                       # created automatically on first run
    ├── feeds/<user_id>.json      # ranked feed per user
    ├── notifications/<user_id>.json  # pending push notifications
    ├── state/<user_id>.json      # what each user has been shown/notified
    ├── report.json               # data quality + coverage report
    ├── rejected.json             # listings that failed validation
    └── engine.log
```

## Setup

Requires Python 3.10+.

```bash
cd verdure-discovery
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
python -m pytest -q          # should print: 6 passed
```

For Ticketmaster events, get a free key at developer.ticketmaster.com and set it as an environment variable (the engine skips that source if it's missing):

```bash
export TICKETMASTER_API_KEY=your_key_here        # macOS/Linux
setx TICKETMASTER_API_KEY "your_key_here"        # Windows (open a new terminal after)
```

## Running it

```bash
python run.py
```

That's it. The engine:

1. Fetches every enabled source in `config.yaml` immediately, then every `refresh_minutes` (default 60).
2. Checks `data/users/` every 30 seconds. When a profile is added or edited (new interests, a save, a dismiss), it re-ranks feeds right away from stored events without re-fetching sources.
3. Reloads `config.yaml` at each refresh, so edits apply without a restart.
4. Keeps a failed source's last good events instead of wiping them, logs the error, and retries next cycle.

Stop with Ctrl+C.

Other modes:

```bash
python run.py --once      # one refresh, then exit
python run.py --rerank    # rebuild feeds from stored events only
python run.py --verbose   # debug logging
```

### Keeping it running on a server

The loop already auto-updates; you just need it to survive reboots. Pick one.

**Linux (systemd)** — create `/etc/systemd/system/verdure.service`:

```ini
[Unit]
Description=Verdure discovery engine
After=network-online.target

[Service]
WorkingDirectory=/opt/verdure-discovery
ExecStart=/opt/verdure-discovery/.venv/bin/python run.py
Environment=TICKETMASTER_API_KEY=your_key_here
Restart=always

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now verdure`.

**Cron instead of the loop** (no profile-change detection, but simplest):

```
0 * * * * cd /opt/verdure-discovery && .venv/bin/python run.py --once
```

## How your app plugs in

| The app does this | By writing/reading |
|---|---|
| Creates or updates a user | writes `data/users/<user_id>.json` |
| Records a save, click, share, RSVP, dismiss, hide, or report | appends to that user's `interactions` list |
| Accepts an organizer submission | writes `data/submissions/<id>.json` |
| Organizer corrects or cancels | edits the file (set `"status": "cancelled"`) or deletes it |
| Shows the feed | reads `output/feeds/<user_id>.json` |
| Sends push notifications | reads `output/notifications/<user_id>.json`, sends, then deletes the file |

### User profile fields

```jsonc
{
  "user_id": "maria",
  "area": "willow glen",              // or set lat + lon instead
  "lat": null, "lon": null,
  "max_distance_miles": 8,
  "interests": ["kids", "outdoors"],
  "date_range_days": 14,
  "max_price": 25,                    // null = no limit
  "formats": ["in_person", "hybrid"], // add "online" to include online events
  "child_ages": [4],                  // filters to age-appropriate events
  "indoor_only": false,
  "interactions": [
    {"uid": "637d7ff28b7b6531", "action": "save", "at": "2026-10-05T18:00:00Z"}
  ]
}
```

Named areas: downtown san jose, sjsu, willow glen, almaden, cambrian, evergreen, santa clara, sunnyvale, campbell, milpitas (edit `verdure/geo.py` to add more).

Interest categories: family, kids, music, arts, education, outdoors, volunteer, sports, fitness, food, community, campus, tech, social, film, theater, workshop, civic, other.

Interaction actions: `rsvp`, `register_click`, `save`, `share`, `click` (positive), `dismiss`, `hide` (negative, and the event is never shown again), `report` (event hidden for that user, no effect on taste). The `uid` comes from the feed entry. Including `"categories"` on an interaction lets it keep counting after the event leaves the index.

### Organizer submission fields

Required: `title`, `start`. Everything else in `data/submissions/example_storytime.json` is optional but raises the listing's quality score, and therefore its rank. In-person events need a venue/address and `lat`/`lon` to show up in distance-filtered feeds.

## How ranking works

1. **Hard filters** (the user's own constraints): date window, distance, price, format, child age, indoor-only. Dismissed and hidden events are removed.
2. **Score** = weighted average of six components, each 0–1:

| Component | Meaning | Default weight |
|---|---|---|
| interest_match | event category is in the user's interests | 0.35 |
| distance | closer is higher | 0.20 |
| soonness | sooner is higher | 0.15 |
| quality | listing completeness from validation | 0.15 |
| novelty | new to this user; fades over a week of being shown | 0.10 |
| learned_affinity | categories the user has saved/RSVP'd vs dismissed recently | 0.05 |

3. **Diversity re-rank**: each event already placed from the same category or organizer lowers the next one's score, so the feed doesn't turn into ten storytimes in a row.

Learned affinity uses a small learning rate and a 30-day half-life, so stated interests stay in charge and clicks alone can't take over the ranking.

Every feed entry includes `components`, `diversity_penalty`, and plain-language `reasons` (e.g. "Matches your interest in kids' activities", "Close by (0.1 mi)", "Free"), so you can always see why something ranked where it did and tell whether a bad result came from data, filters, or weights.

**Notifications**: an event is queued when its score is at least `notify_threshold` (0.70), it starts within `notify_within_days` (4), the user hasn't saved it, and they haven't been notified about it before.

## Data quality report

`output/report.json` refreshes every cycle with: per-source fetch status, publishable vs rejected counts, duplicates removed, % complete listings, most common missing fields, rejection reasons, and coverage by area and category. `output/rejected.json` lists each rejected listing and why, which is what you send back to organizers.

Blocking rules (listing rejected): missing title or start, end before start, already ended, cancelled, outside the region radius, in-person with no location. Non-blocking issues (missing description, price, URL, organizer, etc.) lower the quality score instead.

## Adding a source

Any platform with an `.ics` feed needs no code, just a config entry:

```yaml
  - id: sunnyvale_library
    name: "Sunnyvale Public Library"
    type: ical
    url: "https://example.gov/calendar.ics"
    default_category: "community"
    enabled: true
```

For a new feed format, add a class in `verdure/sources/` that subclasses `Source` and returns a list of `Event`, then register it in `verdure/sources/__init__.py`. Your existing BiblioCommons adapters can be dropped in this way.

## Tuning

Everything adjustable is in `config.yaml`: refresh interval, region center and radius, ranking weights, diversity penalties, learning rate, notification threshold, and max results per user. Changes are picked up on the next refresh.