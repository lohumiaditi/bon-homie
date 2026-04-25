"""
Comprehensive Pune localities list — used by all scrapers and the batch runner.
Covers all major rental areas in Pune + PCMC.

ALL_PUNE_AREAS: full list (~60 localities) for complete repository scraping.
TOP_AREAS: top 25 high-demand areas, prioritised in on-demand searches.
"""

# ── Complete Pune locality list ────────────────────────────────────────────────
ALL_PUNE_AREAS = [
    # West Pune / IT corridor (Hinjewadi, Wakad belt)
    "Baner",
    "Balewadi",
    "Wakad",
    "Hinjewadi",
    "Pimple Saudagar",
    "Pimple Nilakh",
    "Ravet",
    "Tathawade",
    "Punawale",
    "Mahalunge",
    "Sus",
    "Bavdhan",

    # North-West / Aundh-Pashan belt
    "Aundh",
    "Pashan",
    "Sangvi",
    "Vishrantwadi",

    # Central Pune
    "Kothrud",
    "Deccan",
    "Shivajinagar",
    "Karve Nagar",
    "Erandwane",
    "Warje",
    "Sinhagad Road",
    "Dhankawadi",

    # East Pune / Kalyani-Koregaon belt
    "Viman Nagar",
    "Kalyani Nagar",
    "Koregaon Park",
    "Kharadi",
    "Hadapsar",
    "Magarpatta",
    "Wadgaon Sheri",
    "Mundhwa",
    "Yerwada",
    "Nagar Road",

    # Far East
    "Wagholi",
    "Dhanori",
    "Lohegaon",
    "Keshav Nagar",

    # South Pune
    "Kondhwa",
    "Undri",
    "Bibwewadi",
    "NIBM",
    "NIBM Road",
    "Katraj",
    "Ambegaon",
    "Dhayari",
    "Narhe",
    "Wanowrie",
    "Salunke Vihar",

    # Pune city / Camp
    "Camp",
    "Pune Station",
    "Swargate",
    "Sadashiv Peth",
    "Shukrawar Peth",

    # PCMC (Pimpri-Chinchwad)
    "Pimpri",
    "Chinchwad",
    "Akurdi",
    "Nigdi",
    "Bhosari",
    "Kasarwadi",
    "Phugewadi",
    "Chakan",
    "Moshi",
]

# Top 25 high-demand areas — used for on-demand scraping and prioritised in batch
TOP_AREAS = [
    "Baner",
    "Kothrud",
    "Viman Nagar",
    "Koregaon Park",
    "Wakad",
    "Hinjewadi",
    "Aundh",
    "Kalyani Nagar",
    "Hadapsar",
    "Magarpatta",
    "Bavdhan",
    "Pimple Saudagar",
    "Shivajinagar",
    "Deccan",
    "Kharadi",
    "Wagholi",
    "Undri",
    "Kondhwa",
    "Pimple Nilakh",
    "Pashan",
    "Balewadi",
    "Warje",
    "Ravet",
    "Mundhwa",
    "Yerwada",
]

# Lat/lng centroids for NoBroker API (all areas)
# Missing ones auto-resolved via Google Maps / Nominatim
AREA_COORDS: dict[str, tuple[float, float]] = {
    # West
    "Baner":             (18.5590, 73.7768),
    "Balewadi":          (18.5722, 73.7831),
    "Wakad":             (18.5988, 73.7611),
    "Hinjewadi":         (18.5912, 73.7376),
    "Pimple Saudagar":   (18.6121, 73.7975),
    "Pimple Nilakh":     (18.5966, 73.7873),
    "Ravet":             (18.6476, 73.7289),
    "Tathawade":         (18.6225, 73.7625),
    "Punawale":          (18.6278, 73.7496),
    "Mahalunge":         (18.6037, 73.7440),
    "Sus":               (18.5476, 73.7537),
    "Bavdhan":           (18.5198, 73.7857),
    # North-West
    "Aundh":             (18.5581, 73.8089),
    "Pashan":            (18.5367, 73.7953),
    "Sangvi":            (18.5785, 73.8123),
    "Vishrantwadi":      (18.5882, 73.8762),
    # Central
    "Kothrud":           (18.5074, 73.8077),
    "Deccan":            (18.5163, 73.8442),
    "Shivajinagar":      (18.5308, 73.8474),
    "Karve Nagar":       (18.4961, 73.8192),
    "Erandwane":         (18.5060, 73.8270),
    "Warje":             (18.4879, 73.8013),
    "Sinhagad Road":     (18.4851, 73.8108),
    "Dhankawadi":        (18.4595, 73.8571),
    # East
    "Viman Nagar":       (18.5679, 73.9143),
    "Kalyani Nagar":     (18.5460, 73.9050),
    "Koregaon Park":     (18.5362, 73.8938),
    "Kharadi":           (18.5518, 73.9405),
    "Hadapsar":          (18.5018, 73.9260),
    "Magarpatta":        (18.5090, 73.9316),
    "Wadgaon Sheri":     (18.5594, 73.9200),
    "Mundhwa":           (18.5190, 73.9300),
    "Yerwada":           (18.5614, 73.8855),
    "Nagar Road":        (18.5487, 73.9102),
    # Far East
    "Wagholi":           (18.5726, 73.9745),
    "Dhanori":           (18.5927, 73.9094),
    "Lohegaon":          (18.5987, 73.9214),
    "Keshav Nagar":      (18.5358, 73.9491),
    # South
    "Kondhwa":           (18.4680, 73.8841),
    "Undri":             (18.4627, 73.8954),
    "Bibwewadi":         (18.4772, 73.8488),
    "NIBM":              (18.4692, 73.8982),
    "NIBM Road":         (18.4701, 73.8971),
    "Katraj":            (18.4514, 73.8640),
    "Ambegaon":          (18.4409, 73.8576),
    "Dhayari":           (18.4544, 73.8032),
    "Narhe":             (18.4572, 73.8131),
    "Wanowrie":          (18.4930, 73.8950),
    "Salunke Vihar":     (18.5117, 73.9137),
    # City
    "Camp":              (18.5176, 73.8785),
    "Pune Station":      (18.5295, 73.8742),
    "Swargate":          (18.5018, 73.8648),
    "Sadashiv Peth":     (18.5134, 73.8560),
    "Shukrawar Peth":    (18.5210, 73.8590),
    # PCMC
    "Pimpri":            (18.6279, 73.7995),
    "Chinchwad":         (18.6447, 73.8026),
    "Akurdi":            (18.6470, 73.7733),
    "Nigdi":             (18.6601, 73.7738),
    "Bhosari":           (18.6487, 73.8488),
    "Kasarwadi":         (18.6340, 73.8033),
    "Phugewadi":         (18.6289, 73.7901),
    "Chakan":            (18.7603, 73.8607),
    "Moshi":             (18.6783, 73.8543),
}
