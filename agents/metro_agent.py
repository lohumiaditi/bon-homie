"""
Metro Agent
-----------
For each filtered listing in Pune, finds:
  1. Nearest Pune Metro station (walking distance)
  2. Metro travel time to user's destination station

Uses Google Maps Distance Matrix API.
Fallback: haversine formula with hardcoded station coordinates.

Run standalone:
    python agents/metro_agent.py
"""

import os
import sys
import math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from dotenv import load_dotenv
load_dotenv()

# ── Pune Metro Station Data ───────────────────────────────────────────────────
# Coordinates from official Pune Metro maps (lat, lng)
# Line 1: PCMC → Swargate  |  Line 2: Vanaz → Ramwadi

PUNE_METRO_STATIONS = {
    # Line 1 (Purple) — PCMC to Swargate
    "PCMC": (18.6299, 73.8044),
    "Sant Tukaram Nagar": (18.6226, 73.8022),
    "Bhosari": (18.6153, 73.7995),
    "Kasarwadi": (18.6067, 73.7986),
    "Phugewadi": (18.5987, 73.7975),
    "Dapodi": (18.5876, 73.8003),
    "Bopodi": (18.5768, 73.8050),
    "Khadki": (18.5658, 73.8350),
    "Range Hills": (18.5583, 73.8498),
    "Shivajinagar": (18.5352, 73.8471),
    "Civil Court": (18.5248, 73.8561),
    "Budhwar Peth": (18.5163, 73.8559),
    "Mandai": (18.5110, 73.8547),
    "Swargate": (18.5013, 73.8596),
    # Line 2 (Aqua) — Vanaz to Ramwadi
    "Vanaz": (18.5093, 73.7999),
    "Anand Nagar": (18.5097, 73.8098),
    "Ideal Colony": (18.5093, 73.8198),
    "Nal Stop": (18.5120, 73.8316),
    "Garware College": (18.5163, 73.8414),
    "Deccan Gymkhana": (18.5196, 73.8460),
    "Chhatrapati Sambhajinagar": (18.5265, 73.8510),  # formerly "PMC"
    "Agriculture College": (18.5306, 73.8603),
    "Range Hills Interchange": (18.5583, 73.8498),  # interchange with Line 1
    "Ramwadi": (18.5490, 73.9010),
    # Additional stations on extensions (Phase 2)
    "Hinjewadi": (18.5900, 73.7360),
    "Balewadi": (18.5729, 73.7792),
    "Baner": (18.5590, 73.7900),
    "Wakad": (18.5944, 73.7607),
}

# ── Haversine distance ────────────────────────────────────────────────────────
def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in metres between two lat/lng points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_station_haversine(lat: float, lng: float) -> tuple[str, int]:
    """Return (station_name, walking_distance_metres) using straight-line distance."""
    best_station = None
    best_dist = float("inf")
    for name, (s_lat, s_lng) in PUNE_METRO_STATIONS.items():
        d = haversine_m(lat, lng, s_lat, s_lng)
        if d < best_dist:
            best_dist = d
            best_station = name
    # Walking distance ≈ straight-line × 1.3 (detour factor)
    walking_m = int(best_dist * 1.3)
    return best_station, walking_m


# ── Google Maps API ───────────────────────────────────────────────────────────
GMAPS_KEY = os.environ.get("GOOGLE_MAPS_KEY")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DISTANCE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


def geocode_address(address: str) -> tuple[float, float] | None:
    """Return (lat, lng) for an address string, or None on failure."""
    if not GMAPS_KEY:
        return None
    try:
        resp = requests.get(GEOCODE_URL, params={
            "address": f"{address}, Pune, India",
            "key": GMAPS_KEY,
        }, timeout=10)
        data = resp.json()
        if data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"  [metro] Geocode error: {e}")
    return None


def walking_distance_to_stations(origin_lat: float, origin_lng: float,
                                  station_names: list[str]) -> dict[str, int]:
    """
    Use Google Distance Matrix to get walking distance (metres) from
    origin to each metro station. Returns {station_name: distance_metres}.
    """
    if not GMAPS_KEY:
        return {}

    # Build destination strings
    destinations = []
    for name in station_names:
        lat, lng = PUNE_METRO_STATIONS[name]
        destinations.append(f"{lat},{lng}")

    # API allows max 25 destinations per call
    results = {}
    batch_size = 25
    for i in range(0, len(destinations), batch_size):
        batch_names = station_names[i:i + batch_size]
        batch_dests = "|".join(destinations[i:i + batch_size])
        try:
            resp = requests.get(DISTANCE_URL, params={
                "origins": f"{origin_lat},{origin_lng}",
                "destinations": batch_dests,
                "mode": "walking",
                "key": GMAPS_KEY,
            }, timeout=15)
            data = resp.json()
            rows = data.get("rows", [])
            if rows:
                elements = rows[0].get("elements", [])
                for name, el in zip(batch_names, elements):
                    if el.get("status") == "OK":
                        results[name] = el["distance"]["value"]
        except Exception as e:
            print(f"  [metro] Distance Matrix error: {e}")

    return results


def find_metro_info(listing: dict) -> dict:
    """
    Enrich a listing dict with metro station info.
    Returns updated listing with keys:
      metro_station, walking_distance_m, lat, lng
    """
    # Get coordinates
    lat = listing.get("lat")
    lng = listing.get("lng")

    if not lat or not lng:
        address = listing.get("address") or listing.get("area_name") or ""
        coords = geocode_address(address) if address else None
        if coords:
            lat, lng = coords
            listing["lat"] = lat
            listing["lng"] = lng

    if not lat or not lng:
        # Can't geolocate — use area name heuristic
        listing["metro_station"] = None
        listing["walking_distance_m"] = None
        return listing

    # Try Google Maps walking distance
    if GMAPS_KEY:
        all_station_names = list(PUNE_METRO_STATIONS.keys())
        distances = walking_distance_to_stations(lat, lng, all_station_names)
        if distances:
            best = min(distances, key=distances.get)
            listing["metro_station"] = best
            listing["walking_distance_m"] = distances[best]
            return listing

    # Fallback: haversine
    station, dist = nearest_station_haversine(lat, lng)
    listing["metro_station"] = station
    listing["walking_distance_m"] = dist
    return listing


def calculate_metro_travel_time(from_station: str, to_station: str) -> int:
    """
    Estimate metro travel time in minutes between two stations.
    Formula: |station_index_diff| × 2.5 min + 5 min (boarding buffer)
    """
    station_list = list(PUNE_METRO_STATIONS.keys())
    try:
        i1 = station_list.index(from_station)
        i2 = station_list.index(to_station)
        return abs(i1 - i2) * 2 + 5
    except ValueError:
        return 20  # default if stations not found


def enrich_listings_with_metro(listings: list[dict], destination_station: str | None = None) -> list[dict]:
    """Add metro info to all listings. Returns enriched list."""
    print(f"  [metro] Enriching {len(listings)} listings with metro data...")
    enriched = []
    for i, l in enumerate(listings):
        l = find_metro_info(l)
        if destination_station and l.get("metro_station"):
            l["metro_travel_min"] = calculate_metro_travel_time(
                l["metro_station"], destination_station
            )
        else:
            l["metro_travel_min"] = None
        enriched.append(l)
        if (i + 1) % 10 == 0:
            print(f"  [metro] Processed {i + 1}/{len(listings)}")
    return enriched


if __name__ == "__main__":
    # Test with a known Pune address
    print("Testing Metro Agent with Kothrud address...")
    test_listing = {
        "id": "test1",
        "address": "Paud Road, Kothrud, Pune",
        "area_name": "Kothrud",
        "price": 15000,
        "images": ["a", "b", "c"],
    }
    result = find_metro_info(test_listing)
    print(f"  Nearest station : {result.get('metro_station')}")
    print(f"  Walking distance: {result.get('walking_distance_m')} m")
    print(f"  Lat/Lng         : {result.get('lat')}, {result.get('lng')}")

    travel = calculate_metro_travel_time("Kothrud" if "Kothrud" in PUNE_METRO_STATIONS else "Vanaz", "Shivajinagar")
    print(f"  Metro travel (Vanaz → Shivajinagar): ~{travel} min")
