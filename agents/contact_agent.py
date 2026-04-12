"""
Contact Extraction Agent
------------------------
Extracts and normalizes Indian phone numbers from listing text.
Uses regex first; falls back to Groq LLM for obfuscated numbers
(e.g. "call nine eight two zero...").

Run standalone:
    python agents/contact_agent.py
"""

import re
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

# ── Regex patterns ────────────────────────────────────────────────────────────
_PHONE_PATTERNS = [
    r"\+91[-\s]?[6-9]\d{9}",          # +91 XXXXXXXXXX
    r"0[6-9]\d{9}",                    # 0XXXXXXXXXX
    r"\b[6-9]\d{9}\b",                 # 10-digit starting 6-9
    r"\b[6-9]\d{4}[-\s]\d{5}\b",      # XXXXX XXXXX with space/dash
]

_COMBINED = re.compile("|".join(_PHONE_PATTERNS))


def extract_phone_regex(text: str) -> str:
    """Extract first phone number from text using regex. Returns normalized +91XXXXXXXXXX."""
    if not text:
        return ""
    text_clean = re.sub(r"\s+", " ", text)
    m = _COMBINED.search(text_clean)
    if m:
        return _normalize(m.group())
    return ""


def _normalize(raw: str) -> str:
    """Normalize any found number to +91XXXXXXXXXX."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return ""


def extract_phone_llm(text: str) -> str:
    """
    Use Groq to extract phone numbers written as words or obfuscated.
    e.g. 'call nine eight zero zero...' → '9800...'
    Only called if regex finds nothing.
    """
    if not text or len(text) < 10:
        return ""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return ""
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        prompt = (
            f"Extract the Indian mobile phone number from this text. "
            f"Return ONLY the 10-digit number starting with 6-9, nothing else. "
            f"If no number is found, return 'none'.\n\nText: {text[:500]}"
        )
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0,
        )
        result = resp.choices[0].message.content.strip()
        if result.lower() == "none":
            return ""
        return _normalize(result)
    except Exception:
        return ""


def extract_contact(listing: dict) -> dict:
    """
    Extract and set `contact` field on a listing dict.
    Returns updated listing.
    """
    # Already has a valid contact
    if listing.get("contact") and listing["contact"].startswith("+91"):
        return listing

    # Build text to search
    text_sources = [
        listing.get("contact_raw", ""),
        listing.get("title", ""),
        listing.get("address", ""),
    ]
    full_text = " ".join(s for s in text_sources if s)

    # Try regex first
    contact = extract_phone_regex(full_text)

    # LLM fallback for obfuscated numbers
    if not contact:
        contact = extract_phone_llm(full_text)

    listing["contact"] = contact
    return listing


def extract_contacts_bulk(listings: list[dict]) -> list[dict]:
    """Extract contacts from all listings."""
    updated = []
    found = 0
    for l in listings:
        l = extract_contact(l)
        if l.get("contact"):
            found += 1
        updated.append(l)
    print(f"  [contact] {found}/{len(listings)} listings have a phone number")
    return updated


def update_contacts_in_db(listings: list[dict]):
    """Write extracted contacts back to Supabase listings table."""
    if not listings:
        return
    from db.client import db
    client = db()
    for l in listings:
        lid = l.get("id")
        if lid and l.get("contact"):
            client.table("listings").update({
                "contact_raw": l.get("contact_raw", ""),
                "contact": l["contact"],
            }).eq("id", lid).execute()


if __name__ == "__main__":
    test_cases = [
        ("Call 9876543210 for details", "+919876543210"),
        ("Contact: +91-98765-43210", "+919876543210"),
        ("Phone: 09876543210", "+919876543210"),
        ("Reach us at 98765 43210", "+919876543210"),
        ("No number here", ""),
    ]
    print("Contact Extraction Agent — self-test:")
    all_pass = True
    for text, expected in test_cases:
        got = extract_phone_regex(text)
        status = "PASS" if got == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] '{text[:40]}' -> '{got}' (expected '{expected}')")
    print("\nAll tests passed!" if all_pass else "\nSome tests failed.")
