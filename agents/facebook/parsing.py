"""
Facebook parsing helpers
------------------------
Pure functions that turn Facebook page HTML and post text into structured data.
No network or browser access, so everything here is unit-tested against
hand-built HTML in tests/test_facebook_parsing.py.

Facebook's markup is obfuscated and changes often, so parsers anchor on the
few stable signals: role="article" containers, URL shapes (/groups/<key>/posts/<id>),
data-ad-preview="message" bodies, and visible text like "12K members".
"""

import hashlib
import math
import re
from urllib.parse import parse_qs, quote, urljoin, urlparse

from bs4 import BeautifulSoup

from agents.pune_areas import ALL_PUNE_AREAS
from agents.scrapers.base import empty_listing, normalize_furnishing, normalize_phone

FB_ROOT = "https://www.facebook.com"


# ── Area ──────────────────────────────────────────────────────────────────────

# Longest names first so "Viman Nagar" wins over "Nagar Road" and "NIBM Road"
# over "NIBM". Word boundaries stop "Sus" matching "suspend" or "Camp" "campus".
_AREA_PATTERNS = [
    (
        area,
        re.compile(
            r"(?<![a-z])"
            + r"[\s\-]*".join(re.escape(w) for w in area.lower().split())
            + r"(?![a-z])"
        ),
    )
    for area in sorted(ALL_PUNE_AREAS, key=len, reverse=True)
]


def extract_area(text: str) -> str:
    t = text.lower()
    for area, pattern in _AREA_PATTERNS:
        if pattern.search(t):
            return area
    return ""


# ── Price ─────────────────────────────────────────────────────────────────────

MIN_RENT, MAX_RENT = 2_000, 3_00_000

# 15000 | 15,000 | 1,20,000 — never part of a longer digit run (phone numbers)
_AMOUNT = r"(?<![\d,])(\d{1,3}(?:,\d{2,3})+|\d{4,6})(?!\d)(?!,\d)"
_CURRENCY = r"(?:₹|\brs\.?|\binr)"

_PRICE_PATTERNS = [
    re.compile(r"\brent(?:al)?\b\s*(?:is|of|:|-|=|@)?\s*" + _CURRENCY + r"?\s*" + _AMOUNT, re.I),
    re.compile(_CURRENCY + r"\s*" + _AMOUNT, re.I),
    re.compile(_AMOUNT + r"\s*(?:/-)?\s*(?:/|per|p\.)\s*(?:month|mon|mo|m)\b", re.I),
    re.compile(_AMOUNT + r"\s*(?:/-)?\s*pm\b", re.I),
]
_K_PATTERNS = [
    re.compile(r"(?:\brent(?:al)?\b\s*(?::|-|=|is|of)?|₹|\brs\.?)\s*(\d{1,3}(?:\.\d)?)\s*k\b", re.I),
    re.compile(r"\b(\d{1,3}(?:\.\d)?)\s*k\b\s*(?:/|per\b|pm\b|p\.m|rent\b|monthly\b)", re.I),
]
_DEPOSIT_AFTER = re.compile(r"^\s*(?:/-)?\s*(?:deposit|dep\b|security|advance)", re.I)
_DEPOSIT_BEFORE = re.compile(
    r"(?:deposit|dep|security|advance)\s*(?:is|of|:|-|=)?\s*" + _CURRENCY + r"?\s*$", re.I
)


def _is_deposit(text: str, start: int, end: int, labelled_rent: bool) -> bool:
    if _DEPOSIT_BEFORE.search(text[max(0, start - 25):start]):
        return True
    # "Rent 22000/- deposit 50000": an amount right after "rent" is the rent
    return not labelled_rent and bool(_DEPOSIT_AFTER.match(text[end:end + 20]))


def extract_price(text: str) -> int | None:
    """Monthly rent in INR, or None. Skips amounts labelled as deposit."""
    for patterns, scale in ((_PRICE_PATTERNS, 1), (_K_PATTERNS, 1000)):
        for pattern in patterns:
            labelled_rent = pattern is _PRICE_PATTERNS[0] or pattern is _K_PATTERNS[0]
            for m in pattern.finditer(text):
                if _is_deposit(text, m.start(), m.end(), labelled_rent):
                    continue
                try:
                    value = int(round(float(m.group(1).replace(",", "")) * scale))
                except ValueError:
                    continue
                if MIN_RENT <= value <= MAX_RENT:
                    return value
    return None


# ── Phone ─────────────────────────────────────────────────────────────────────

# Indian mobile, optionally +91/91/0-prefixed, digits optionally split by
# single spaces or dashes ("98765 43210", "987-654-3210").
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?|0)?([6-9](?:[\s\-]?\d){9})(?!\d)")


def extract_phone(text: str) -> str:
    m = _PHONE_RE.search(text)
    return normalize_phone(m.group(1)) if m else ""


# ── Post classification ───────────────────────────────────────────────────────

_RENTAL_RE = re.compile(
    r"\b(?:rent|rental|rented|bhk|\drk|1rk|flat|flats|apartment|pg|room|rooms|flatmates?|"
    r"roommates?|room\s?mates?|flat\s?mates?|accommodation|paying guest|house|tenants?|"
    r"lease|studio|vacancy|vacant|to[\s\-]let)\b",
    re.I,
)
_HOME = r"(?:\d\s*bhk|\drk|flat\b|flats\b|room(?!\s?mate)\b|rooms\b|house\b|apartment\b|pg\b|accommodation\b|place\b|rental\b|home\b)"
_SEEK_RES = [
    re.compile(r"\blooking\s+(?:out\s+)?for\s+(?:a\s+|an\s+|some\s+)?(?:\w+\s+){0,3}?" + _HOME, re.I),
    re.compile(r"\b(?:need|needed|require|required|requirement|want|wanted|searching\s+for|in\s+search\s+of)\b.{0,40}?" + _HOME, re.I),
    re.compile(r"\bbudget\b", re.I),
]
_STRONG_OFFER_RES = [
    re.compile(r"\b(?:for|on)\s+rent\b", re.I),
    re.compile(r"\bto[\s\-]let\b", re.I),
    re.compile(r"\bvacan(?:t|cy)\b", re.I),
    re.compile(r"\blooking\s+for\s+(?:a\s+|an\s+|\d\s+)?(?:\w+\s+){0,2}?(?:flat\s?mates?|room\s?mates?|tenants?|replacement|family|bachelors?)\b", re.I),
    re.compile(r"\b(?:flat|room|bhk|rk|house|apartment|pg)\s+(?:is\s+)?available\b", re.I),
    re.compile(r"\bavailable\s+(?:for\s+rent|from|immediately|on\s+rent)\b", re.I),
    re.compile(r"\b(?:rent|deposit)\s*[:\-=]", re.I),
]
_WEAK_OFFER_RES = [
    re.compile(r"\bavailable\b", re.I),
    re.compile(r"\b(?:no|zero)\s+brokerage\b", re.I),
    re.compile(r"\bowner\b", re.I),
    re.compile(r"\b(?:furnished|semi[\s\-]?furnished|unfurnished)\b", re.I),
]


def is_rental_post(text: str) -> bool:
    return bool(_RENTAL_RE.search(text))


def classify_post(text: str) -> str:
    """
    'offer'  someone has a flat/room to give (a lead)
    'seek'   someone is looking for a flat (another tenant — not a lead)
    'other'  not about rentals
    """
    if not is_rental_post(text):
        return "other"
    strong = any(p.search(text) for p in _STRONG_OFFER_RES)
    seek = any(p.search(text) for p in _SEEK_RES)
    if seek and not strong:
        return "seek"
    if strong or any(p.search(text) for p in _WEAK_OFFER_RES):
        return "offer"
    if extract_price(text) or extract_phone(text):
        return "offer"
    return "other"


# ── Login wall / membership ───────────────────────────────────────────────────

_LOGIN_URL_MARKERS = ("/login", "checkpoint", "two_step_verification", "/recover")


def is_login_wall(url: str, html: str = "") -> bool:
    """True when Facebook has bounced us to login / checkpoint instead of the page."""
    if any(marker in (url or "") for marker in _LOGIN_URL_MARKERS):
        return True
    if html and ('id="login_form"' in html or ('name="pass"' in html and 'name="email"' in html)):
        return True
    return False


def detect_membership(html: str) -> str:
    """Membership of the logged-in account, read from a group's own page."""
    low = html.lower()
    if 'aria-label="cancel request"' in low or ">cancel request<" in low:
        return "pending"
    if 'aria-label="join group"' in low or ">join group<" in low:
        return "not_member"
    if 'aria-label="joined"' in low or ">joined<" in low or "write something" in low:
        return "member"
    return "unknown"


# ── URLs ──────────────────────────────────────────────────────────────────────

_RESERVED_GROUP_PATHS = {
    "feed", "discover", "joins", "create", "search", "notifications",
    "your_groups", "categories", "browse", "invites", "requests",
}
_GROUP_KEY_RE = re.compile(r"(?:^|facebook\.com)/groups/([^/?#]+)", re.I)
_GROUP_ROOT_RE = re.compile(r"(?:^|facebook\.com)/groups/[^/?#]+/?(?:[?#]|$)", re.I)


def group_key_from_url(url: str) -> str:
    """'https://www.facebook.com/groups/puneflatrentals/?ref=x' → 'puneflatrentals'."""
    m = _GROUP_KEY_RE.search(url or "")
    if not m:
        return ""
    key = m.group(1)
    return "" if key.lower() in _RESERVED_GROUP_PATHS else key


def group_url(key: str) -> str:
    return f"{FB_ROOT}/groups/{key}/"


def _absolute(href: str) -> str:
    return urljoin(FB_ROOT + "/", href)


_GROUP_POST_RE = re.compile(r"/groups/([^/?#]+)/(?:posts|permalink)/(\d+|pfbid\w+)")
_PHP_POST_RE = re.compile(r"/(?:permalink|story)\.php")
_PROFILE_POST_RE = re.compile(r"(?:^|facebook\.com)/([^/?#]+)/posts/(\d+|pfbid\w+)")
_PHOTO_SET_RE = re.compile(r"[?&]set=gm\.(\d+)")
_MARKETPLACE_ITEM_RE = re.compile(r"/marketplace/item/(\d+)")


def find_post_link(container) -> tuple[str, str, str] | None:
    """
    (post_id, canonical_url, group_key) for the first post permalink inside a
    post container, or None. Group photo links (?set=gm.<post_id>) count too —
    Facebook often only fills the timestamp link's href on hover.
    """
    photo_fallback = None
    for a in container.find_all("a", href=True):
        href = a["href"]
        m = _GROUP_POST_RE.search(href)
        if m:
            key, pid = m.group(1), m.group(2)
            return pid, f"{FB_ROOT}/groups/{key}/posts/{pid}/", key
        if _PHP_POST_RE.search(href):
            qs = parse_qs(urlparse(_absolute(href)).query)
            pid = (qs.get("story_fbid") or [""])[0]
            owner = (qs.get("id") or [""])[0]
            if pid:
                url = f"{FB_ROOT}/permalink.php?story_fbid={pid}"
                return pid, url + (f"&id={owner}" if owner else ""), ""
        m = _PROFILE_POST_RE.search(href)
        if m and m.group(1).lower() not in ("groups", "marketplace"):
            return m.group(2), f"{FB_ROOT}/{m.group(1)}/posts/{m.group(2)}/", ""
        m = _PHOTO_SET_RE.search(href)
        if m and photo_fallback is None:
            photo_fallback = m.group(1)
    if photo_fallback:
        return photo_fallback, "", ""
    return None


# ── Post pieces ───────────────────────────────────────────────────────────────

_USER_IN_GROUP_RE = re.compile(r"/groups/[^/?#]+/user/(\d+)")
_PROFILE_ID_RE = re.compile(r"profile\.php\?(?:.*&)?id=(\d+)")
_RESERVED_ROOT_PATHS = {
    "groups", "marketplace", "watch", "events", "pages", "help", "login", "settings",
    "share", "hashtag", "photo", "photo.php", "story.php", "permalink.php", "reel",
    "reels", "stories", "search", "notifications", "messages", "friends", "gaming",
    "bookmarks", "ads", "business", "policies", "privacy", "l.php", "profile.php",
    "home.php", "saved", "memories", "fundraisers", "people",
}
_SKIP_IMAGE_MARKERS = ("static.xx.fbcdn.net", "rsrc.php", "/emoji", "emoji.php")


def extract_poster(container) -> tuple[str, str]:
    """(profile_url, display_name) of whoever wrote the post, or ('', '')."""
    anchors = container.find_all("a", href=True)
    for a in anchors:
        m = _USER_IN_GROUP_RE.search(a["href"]) or _PROFILE_ID_RE.search(a["href"])
        name = a.get_text(" ", strip=True)
        if m and name:
            return f"{FB_ROOT}/profile.php?id={m.group(1)}", name
    for a in anchors:
        name = a.get_text(" ", strip=True)
        parsed = urlparse(_absolute(a["href"]))
        path = parsed.path.strip("/")
        if (
            name
            and parsed.netloc.endswith("facebook.com")
            and path
            and "/" not in path
            and path.lower() not in _RESERVED_ROOT_PATHS
        ):
            return f"{FB_ROOT}/{path}", name
    return "", ""


def extract_images(container, limit: int = 10) -> list[str]:
    urls: list[str] = []
    for img in container.find_all("img"):
        src = img.get("src") or ""
        if not src.startswith("http") or "fbcdn" not in src and "scontent" not in src:
            continue
        if any(marker in src for marker in _SKIP_IMAGE_MARKERS):
            continue
        try:
            if min(int(img.get("width") or 999), int(img.get("height") or 999)) < 80:
                continue
        except ValueError:
            pass
        if src not in urls:
            urls.append(src)
        if len(urls) >= limit:
            break
    return urls


_SEE_MORE_RE = re.compile(r"\s*(?:…|\.\.\.)?\s*See more\s*$", re.I)


def extract_message_text(container) -> str:
    """The post body when Facebook marks it, else all text in the container."""
    for attr in ("data-ad-preview", "data-ad-comet-preview"):
        el = container.find(attrs={attr: "message"})
        if el:
            return _SEE_MORE_RE.sub("", el.get_text(" ", strip=True))
    return _SEE_MORE_RE.sub("", container.get_text(" ", strip=True))


def _text_id(text: str) -> str:
    return "h" + hashlib.md5(text.encode()).hexdigest()[:16]


# ── Feeds (group feed, post search) ───────────────────────────────────────────

_ANY_POST_HREF_RE = re.compile(r"/(?:posts|permalink)/|story_fbid=|set=gm\.")


def _post_containers(soup) -> list:
    articles = [
        a for a in soup.find_all(attrs={"role": "article"})
        if a.find_parent(attrs={"role": "article"}) is None   # skip comments
    ]
    if articles:
        return articles
    containers, seen = [], set()
    for a in soup.find_all("a", href=_ANY_POST_HREF_RE):
        parent = a.find_parent("div")
        if parent is not None and id(parent) not in seen:
            seen.add(id(parent))
            containers.append(parent)
    return containers


def parse_feed_posts(html: str, limit: int = 50) -> list[dict]:
    """
    Posts from a group feed or post-search results page:
      {post_id, url, group_key, text, images, poster_url, poster_name}
    Posts whose permalink can't be found get a text-hash id and an empty url.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts: list[dict] = []
    seen: set[str] = set()
    for container in _post_containers(soup):
        text = extract_message_text(container)
        if len(text) < 15:
            continue
        link = find_post_link(container)
        post_id, url, key = link if link else (_text_id(text), "", "")
        if post_id in seen:
            continue
        seen.add(post_id)
        poster_url, poster_name = extract_poster(container)
        posts.append({
            "post_id": post_id,
            "url": url,
            "group_key": key,
            "text": text,
            "images": extract_images(container),
            "poster_url": poster_url,
            "poster_name": poster_name,
        })
        if len(posts) >= limit:
            break
    return posts


# ── Listings ──────────────────────────────────────────────────────────────────

def whatsapp_link(phone: str, area: str = "", price: int | None = None) -> str:
    msg = (
        f"Hi! I saw your rental listing in {area or 'Pune'}"
        f"{f' at Rs.{price:,}/month' if price else ''}. "
        "Is it still available? I'm interested in visiting."
    )
    return f"https://wa.me/{phone.replace('+', '').replace(' ', '')}?text={quote(msg)}"


def _title(text: str) -> str:
    first = re.split(r"(?<=[.!?\n])\s", text.strip(), maxsplit=1)[0]
    return (first if 20 <= len(first) <= 140 else text[:140]).strip()


def _apply_hints(listing: dict, text: str) -> None:
    t = text.lower()
    if re.search(r"\b(?:double|sharing|twin)\b", t):
        listing["occupancy"] = "double"
    elif re.search(r"\bsingle\b", t):
        listing["occupancy"] = "single"
    if re.search(r"\b(?:ladies|female|females|girls?|women)\b", t):
        listing["gender"] = "female"
    elif re.search(r"\b(?:bachelors?|male|males|boys?|gents)\b", t):
        listing["gender"] = "male"
    if re.search(r"\bfamil(?:y|ies)\b", t):
        listing["renter_type"] = "family"
    elif re.search(r"\bbachelors?\b", t):
        listing["renter_type"] = "bachelor"
    if re.search(r"\b(?:no|zero|without)\s+brokerage\b", t):
        listing["brokerage"] = False
    elif re.search(r"\bbroker(?:age)?\b", t):
        listing["brokerage"] = True


def post_to_listing(post: dict, *, assume_offer: bool = False, id_prefix: str = "fbpost") -> dict | None:
    """Standard listing dict for a post that offers a rental, else None."""
    text = post.get("text") or ""
    if not assume_offer and classify_post(text) != "offer":
        return None

    listing = empty_listing()
    area = extract_area(text)
    price = extract_price(text)
    listing.update({
        "platform": "facebook",
        "listing_id": f"{id_prefix}_{post['post_id']}",
        "url": post.get("url") or (group_url(post["group_key"]) if post.get("group_key") else ""),
        "title": _title(text),
        "price": price,
        "area_name": area or "Pune",
        "address": f"{area}, Pune" if area else "Pune",
        "furnishing": normalize_furnishing(text),
        "images": list(post.get("images") or []),
        "fb_post_text": text[:2000],
    })
    _apply_hints(listing, text)

    phone = extract_phone(text)
    if phone:
        listing["contact"] = listing["contact_raw"] = phone
        listing["wa_url"] = whatsapp_link(phone, area, price)
    if post.get("poster_url"):
        listing["fb_poster_url"] = post["poster_url"]
        listing["fb_poster_name"] = post.get("poster_name", "")
    return listing


def parse_marketplace(html: str, limit: int = 80) -> list[dict]:
    """Listings from a Marketplace property-rentals results page."""
    soup = BeautifulSoup(html, "html.parser")
    listings: list[dict] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=_MARKETPLACE_ITEM_RE):
        item_id = _MARKETPLACE_ITEM_RE.search(link["href"]).group(1)
        if item_id in seen:
            continue
        seen.add(item_id)

        container = link
        for _ in range(6):
            if container.find("img"):
                break
            parent = container.find_parent("div")
            if parent is None:
                break
            container = parent

        listing = post_to_listing(
            {
                "post_id": item_id,
                "url": f"{FB_ROOT}/marketplace/item/{item_id}/",
                "text": container.get_text(" ", strip=True),
                "images": extract_images(container),
            },
            assume_offer=True,
            id_prefix="fbmp",
        )
        listings.append(listing)
        if len(listings) >= limit:
            break
    return listings


# ── Group search ──────────────────────────────────────────────────────────────

_MEMBERS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KkMm])?\s*members\b", re.I)
_ACTIVITY_RE = re.compile(r"(\d+\+?)\s*(?:new\s+)?posts?\s+(?:a|per)\s+(day|week|month)", re.I)
_BUTTON_TEXT = {"join", "join group", "visit", "view group", "joined", "cancel request"}


def parse_member_count(text: str) -> int | None:
    m = _MEMBERS_RE.search(text)
    if not m:
        return None
    number, suffix = m.group(1), (m.group(2) or "").lower()
    if suffix:
        value = float(number.replace(",", "."))
        return int(value * (1_000 if suffix == "k" else 1_000_000))
    return int(number.replace(",", "").replace(".", ""))


def parse_group_search(html: str) -> list[dict]:
    """Groups on a /search/groups results page:
    {group_key, url, name, privacy, member_count, activity, description}"""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _GROUP_ROOT_RE.search(href):
            continue
        key = group_key_from_url(href)
        name = a.get_text(" ", strip=True)
        if not key or not name or name.lower() in _BUTTON_TEXT:
            continue

        container = a
        for _ in range(8):
            if "member" in container.get_text(" ", strip=True).lower():
                break
            parent = container.find_parent()
            if parent is None:
                break
            container = parent
        context = container.get_text(" ", strip=True)

        privacy = None
        if re.search(r"\bprivate\b", context, re.I):
            privacy = "private"
        elif re.search(r"\bpublic\b", context, re.I):
            privacy = "public"
        activity = _ACTIVITY_RE.search(context)
        group = {
            "group_key": key,
            "url": group_url(key),
            "name": name[:200],
            "privacy": privacy,
            "member_count": parse_member_count(context),
            "activity": activity.group(0) if activity else None,
            "description": context[:500],
        }
        existing = found.get(key)
        if existing is None or (not existing["member_count"] and group["member_count"]):
            found[key] = group
    return list(found.values())


_PUNE_TERMS_RE = re.compile(
    r"\b(?:pune|pcmc|pimpri|chinchwad|hinjewadi|" +
    "|".join(r"[\s\-]*".join(re.escape(w) for w in a.lower().split()) for a in ALL_PUNE_AREAS) +
    r")\b",
    re.I,
)
_GROUP_RENTAL_RE = re.compile(
    r"\b(rent|rental|rentals|flat|flats|room|rooms|pg|flatmates?|roommates?|accommodation|"
    r"housing|bhk|tenants?|lease|no\s+broker(?:age)?|paying\s+guest|hostel|homes?)\b",
    re.I,
)
_GROUP_NEGATIVE_RE = re.compile(
    r"\b(sale|sell|selling|buy|buyers|plots?|land|resale|investment|investors|jobs?|cars?|"
    r"bikes?|matrimony|dating|loans?|commercial|office\s+space|shop)\b",
    re.I,
)
RELEVANCE_THRESHOLD = 4.0


def score_group(name: str, description: str = "", member_count: int | None = None) -> float:
    """Rough relevance of a group for finding Pune rentals. ≥ RELEVANCE_THRESHOLD is kept."""
    name = name or ""
    description = description or ""
    score = 0.0
    if _PUNE_TERMS_RE.search(name):
        score += 3
    elif _PUNE_TERMS_RE.search(description):
        score += 1
    name_terms = {m.lower() for m in _GROUP_RENTAL_RE.findall(name)}
    score += 2 * min(len(name_terms), 3)
    desc_terms = {m.lower() for m in _GROUP_RENTAL_RE.findall(description)} - name_terms
    score += 0.5 * min(len(desc_terms), 2)
    score -= 3 * len({m.lower() for m in _GROUP_NEGATIVE_RE.findall(name)})
    if member_count and member_count > 100:
        score += min(3.0, max(0.0, math.log10(member_count) - 2))
    return round(score, 2)


# ── Search queries ────────────────────────────────────────────────────────────

def build_post_queries(prefs: dict) -> list[str]:
    queries = []
    for area in prefs.get("areas") or []:
        queries.append(f"{area} pune flat for rent")
        queries.append(f"{area} pune flatmate")
    queries += [
        "pune flat for rent no brokerage",
        "pune 1bhk 2bhk rent available",
        "pune flatmate required",
        "pune room rent available",
    ]
    return queries


def build_group_queries(prefs: dict) -> list[str]:
    queries = []
    for area in prefs.get("areas") or []:
        queries.append(f"{area} pune flat rent")
        queries.append(f"{area} flatmates")
    queries += [
        "pune flat rent",
        "pune flats for rent",
        "pune flatmates",
        "pune rooms for rent",
        "pune rental no brokerage",
        "pune pg accommodation",
        "pcmc flat rent",
        "hinjewadi wakad flat rent",
    ]
    return queries
