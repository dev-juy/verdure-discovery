# Verdure discovery engine configuration
# Edit this file to change sources, region, schedule, and ranking weights.

region:
  name: "San Jose / South Bay"
  # Center point used to reject events far outside the launch area
  center: { lat: 37.3382, lon: -121.8863 }
  max_radius_miles: 30

schedule:
  # How often the engine re-ingests sources and rebuilds every user's feed
  refresh_minutes: 60
  # Events this many hours past their end time are dropped
  drop_past_after_hours: 2
  # Only rank events within this many days from now
  horizon_days: 21

paths:
  store: "data/events.json"
  users_dir: "data/users"
  submissions_dir: "data/submissions"
  output_dir: "output"
  log_file: "output/engine.log"

# Each source has a type (which adapter to use) and adapter-specific settings.
# Set enabled: false to skip a source without deleting it.
sources:
  - id: sjsu
    name: "San José State University"
    type: ical
    url: "https://events.sjsu.edu/calendar/1.ics"
    default_category: "campus"
    enabled: true

  - id: scu
    name: "Santa Clara University"
    type: livewhale
    url: "https://events.scu.edu/live/json/v2/events"
    default_category: "campus"
    enabled: false   # pending verification

  - id: ticketmaster
    name: "Ticketmaster Discovery"
    type: ticketmaster
    api_key_env: "TICKETMASTER_API_KEY"   # read from environment, never hardcode
    lat: 37.3382
    lon: -121.8863
    radius_miles: 25
    enabled: true

  - id: organizers
    name: "Organizer submissions"
    type: submissions
    enabled: true

ranking:
  # Weights for the transparent ranking score. They do not need to sum to 1.
  weights:
    interest_match: 0.35
    distance: 0.20
    soonness: 0.15
    quality: 0.15
    novelty: 0.10
    learned_affinity: 0.05
  # Diversity: after this many events from the same category/organizer in a row,
  # the next one is penalized so the feed doesn't get monotonous.
  diversity:
    same_category_penalty: 0.12
    same_organizer_penalty: 0.15
  max_results_per_user: 50
  # How fast user feedback shifts learned interest weights (0-1). Kept small so
  # a few clicks never dominate stated interests.
  learning_rate: 0.08
  learned_affinity_cap: 1.0

notifications:
  # Events scoring at or above this are flagged as "notify" in the user's feed
  notify_threshold: 0.70
  # Only notify for events starting within this window
  notify_within_days: 4