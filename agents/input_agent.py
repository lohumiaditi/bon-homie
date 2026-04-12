"""
Input Agent
-----------
Collects and validates user flat-hunting preferences via a CLI form.
Returns a UserPreferences Pydantic model and saves it to Supabase.

Run standalone:  python agents/input_agent.py
"""

import os
import sys
import uuid
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator
from dotenv import load_dotenv

load_dotenv()

# ── Pune localities for validation / autocomplete ─────────────────────────────
PUNE_AREAS = [
    "Aundh", "Baner", "Balewadi", "Bavdhan", "Bibwewadi", "Bhosari",
    "Budhwar Peth", "Camp", "Chinchwad", "Deccan", "Dhanori", "Dhayari",
    "Erandwane", "FC Road", "Hadapsar", "Hinjewadi", "Karve Nagar",
    "Katraj", "Khadki", "Kharadi", "Kondhwa", "Koregaon Park", "Kothrud",
    "Magarpatta", "Mahalunge", "Manjri", "Model Colony", "Mundhwa",
    "Nagar Road", "Narhe", "Pashan", "Pimpri", "Pimple Nilakh",
    "Pimple Saudagar", "Pune Station", "Ravet", "Sadashiv Peth",
    "Salisbury Park", "Sangvi", "Sinhagad Road", "Sus", "Undri",
    "Viman Nagar", "Vishrantwadi", "Wadgaon Sheri", "Wagholi",
    "Wakad", "Warje", "Yerawada",
]


# ── Pydantic model ────────────────────────────────────────────────────────────
class UserPreferences(BaseModel):
    id: str = ""
    city: str = "Pune"
    areas: list[str]
    budget_min: int
    budget_max: int
    furnishing: str          # furnished | semi-furnished | unfurnished | any
    renter_type: str         # family | bachelor | any
    gender: str              # male | female | any
    occupancy: str           # single | double | any
    brokerage: str           # yes | no | any
    destination_address: Optional[str] = None

    @field_validator("furnishing")
    @classmethod
    def valid_furnishing(cls, v):
        allowed = {"furnished", "semi-furnished", "unfurnished", "any"}
        if v.lower() not in allowed:
            raise ValueError(f"furnishing must be one of {allowed}")
        return v.lower()

    @field_validator("renter_type")
    @classmethod
    def valid_renter(cls, v):
        allowed = {"family", "bachelor", "any"}
        if v.lower() not in allowed:
            raise ValueError(f"renter_type must be one of {allowed}")
        return v.lower()

    @field_validator("gender")
    @classmethod
    def valid_gender(cls, v):
        allowed = {"male", "female", "any"}
        if v.lower() not in allowed:
            raise ValueError(f"gender must be one of {allowed}")
        return v.lower()

    @field_validator("occupancy")
    @classmethod
    def valid_occupancy(cls, v):
        allowed = {"single", "double", "any"}
        if v.lower() not in allowed:
            raise ValueError(f"occupancy must be one of {allowed}")
        return v.lower()

    @field_validator("brokerage")
    @classmethod
    def valid_brokerage(cls, v):
        allowed = {"yes", "no", "any"}
        if v.lower() not in allowed:
            raise ValueError(f"brokerage must be one of {allowed}")
        return v.lower()

    @model_validator(mode="after")
    def budget_order(self):
        if self.budget_min > self.budget_max:
            raise ValueError("budget_min cannot be greater than budget_max")
        return self


# ── Helpers ───────────────────────────────────────────────────────────────────
def _prompt(question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    ans = input(f"{question}{hint}: ").strip()
    return ans if ans else default


def _choice(question: str, options: list[str], default: str = "") -> str:
    opts = " / ".join(options)
    while True:
        ans = _prompt(f"{question} ({opts})", default).lower()
        if ans in [o.lower() for o in options]:
            return ans
        print(f"  Please enter one of: {opts}")


def _areas_input() -> list[str]:
    print("\nKnown Pune areas (type part of the name):")
    print("  " + ", ".join(PUNE_AREAS[:20]) + " ... (and more)")
    raw = _prompt("Areas you want (comma-separated, e.g. Kothrud, Baner)")
    parts = [p.strip().title() for p in raw.split(",") if p.strip()]
    if not parts:
        print("  At least one area is required.")
        return _areas_input()
    return parts


# ── Main CLI form ─────────────────────────────────────────────────────────────
def collect_preferences() -> UserPreferences:
    print("\n" + "=" * 55)
    print("  FLAT HUNTER — Search Preferences (Pune)")
    print("=" * 55)

    areas = _areas_input()

    print()
    while True:
        try:
            budget_min = int(_prompt("Minimum monthly rent (₹)", "5000"))
            budget_max = int(_prompt("Maximum monthly rent (₹)", "25000"))
            if budget_min <= budget_max:
                break
            print("  Min must be less than Max.")
        except ValueError:
            print("  Please enter whole numbers only.")

    furnishing = _choice(
        "\nFurnishing type",
        ["furnished", "semi-furnished", "unfurnished", "any"],
        "any",
    )
    renter_type = _choice(
        "Permitted renter",
        ["family", "bachelor", "any"],
        "any",
    )
    gender = _choice(
        "Gender preference",
        ["male", "female", "any"],
        "any",
    )
    occupancy = _choice(
        "Occupancy type",
        ["single", "double", "any"],
        "any",
    )
    brokerage = _choice(
        "Brokerage acceptable?",
        ["yes", "no", "any"],
        "any",
    )

    print()
    destination = _prompt(
        "Your destination address (workplace/college/etc.) — press Enter to skip",
        "",
    )

    prefs = UserPreferences(
        id=str(uuid.uuid4()),
        city="Pune",
        areas=areas,
        budget_min=budget_min,
        budget_max=budget_max,
        furnishing=furnishing,
        renter_type=renter_type,
        gender=gender,
        occupancy=occupancy,
        brokerage=brokerage,
        destination_address=destination or None,
    )
    return prefs


def save_to_supabase(prefs: UserPreferences) -> str:
    """Save preferences to Supabase and return the session ID."""
    from db.client import db

    client = db()
    row = {
        "id": prefs.id,
        "city": prefs.city,
        "areas": prefs.areas,
        "budget_min": prefs.budget_min,
        "budget_max": prefs.budget_max,
        "furnishing": prefs.furnishing,
        "renter_type": prefs.renter_type,
        "gender": prefs.gender,
        "occupancy": prefs.occupancy,
        "brokerage": prefs.brokerage,
        "destination_address": prefs.destination_address,
    }
    client.table("user_preferences").insert(row).execute()
    return prefs.id


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        prefs = collect_preferences()
        print("\n--- Your preferences ---")
        print(f"  Areas       : {', '.join(prefs.areas)}")
        print(f"  Budget      : ₹{prefs.budget_min:,} – ₹{prefs.budget_max:,}/month")
        print(f"  Furnishing  : {prefs.furnishing}")
        print(f"  Renter type : {prefs.renter_type}")
        print(f"  Gender pref : {prefs.gender}")
        print(f"  Occupancy   : {prefs.occupancy}")
        print(f"  Brokerage   : {prefs.brokerage}")
        if prefs.destination_address:
            print(f"  Destination : {prefs.destination_address}")

        save_it = input("\nSave to database? (y/n) [y]: ").strip().lower()
        if save_it in ("", "y", "yes"):
            session_id = save_to_supabase(prefs)
            print(f"\nSaved! Session ID: {session_id}")
            print("Check your Supabase dashboard → Table Editor → user_preferences")
        else:
            print("Not saved.")
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
