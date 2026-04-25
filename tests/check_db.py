"""Quick DB stats — total listings by platform."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()
from db.client import db

client = db()

# Total count
total = client.table("listings").select("id", count="exact").execute()
print(f"Total listings: {total.count}")

# By platform
result = client.table("listings").select("platform").execute()
by_plat = {}
for row in result.data:
    p = row["platform"]
    by_plat[p] = by_plat.get(p, 0) + 1

print("\nBy platform:")
for p, c in sorted(by_plat.items(), key=lambda x: -x[1]):
    print(f"  {p:20} {c}")

# With images ≥3
imgs = client.table("listings").select("image_count").execute()
with_imgs = sum(1 for r in imgs.data if (r.get("image_count") or 0) >= 3)
print(f"\nWith 3+ images: {with_imgs}/{total.count}")

# By city
cities = client.table("listings").select("city").execute()
by_city = {}
for row in cities.data:
    c = row.get("city") or "NULL"
    by_city[c] = by_city.get(c, 0) + 1
print("\nBy city:", by_city)
