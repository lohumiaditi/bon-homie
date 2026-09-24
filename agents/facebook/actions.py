"""
Facebook page actions
---------------------
Async operations on a logged-in page from browser.open_page(). Each returns
parsed data (via parsing.py) and raises FacebookSessionExpired on a login wall.
"""

import random
from urllib.parse import quote

from agents.facebook.browser import goto, pause, scroll
from agents.facebook.parsing import (
    FB_ROOT,
    detect_membership,
    parse_feed_posts,
    parse_group_search,
    parse_marketplace,
)

# Base64 of {"recently_created":"{\"name\":\"recently_created\",\"args\":\"\"}"}
_RECENT_POSTS_FILTER = (
    "eyJyZWNlbnRseV9jcmVhdGVkIjoie1wibmFtZVwiOlwicmVjZW50bHlfY3JlYXRlZFwiLFwiYXJncFwiOlwiXCJ9In0%3D"
)

# Facebook fills post timestamp links (the permalinks) in lazily on hover.
_REVEAL_PERMALINKS_JS = """
() => {
  const links = document.querySelectorAll('div[role="article"] a[role="link"]');
  let n = 0;
  for (const a of links) {
    const href = a.getAttribute('href');
    if (!href || href === '#') {
      a.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
      a.dispatchEvent(new FocusEvent('focusin', {bubbles: true}));
      if (++n >= 200) break;
    }
  }
  return n;
}
"""


async def _feed_html(page, scrolls: int) -> str:
    await scroll(page, scrolls)
    try:
        if await page.evaluate(_REVEAL_PERMALINKS_JS):
            await page.wait_for_timeout(1_200)
    except Exception:
        pass
    return await page.content()


async def fetch_marketplace(page, budget_min: int, budget_max: int, limit: int = 80) -> list[dict]:
    url = (
        f"{FB_ROOT}/marketplace/pune/propertyrentals"
        f"?minPrice={budget_min}&maxPrice={budget_max}&daysSinceListed=7&sortBy=creation_time_descend"
    )
    await goto(page, url)
    await scroll(page, 6)
    listings = parse_marketplace(await page.content(), limit=limit)
    print(f"  [facebook] Marketplace: {len(listings)} listings")
    return listings


async def fetch_group_feed(page, url: str, max_posts: int = 40) -> tuple[str, list[dict]]:
    """(membership, newest posts) for a group."""
    sep = "&" if "?" in url else "?"
    html = await goto(page, f"{url}{sep}sorting_setting=CHRONOLOGICAL")
    membership = detect_membership(html)
    posts = parse_feed_posts(await _feed_html(page, scrolls=5), limit=max_posts)
    print(f"  [facebook] Group {url.rstrip('/').split('/')[-1]}: {len(posts)} posts ({membership})")
    return membership, posts


async def fetch_post_search(page, query: str, max_posts: int = 40) -> list[dict]:
    await goto(page, f"{FB_ROOT}/search/posts/?q={quote(query)}&filters={_RECENT_POSTS_FILTER}")
    posts = parse_feed_posts(await _feed_html(page, scrolls=3), limit=max_posts)
    print(f"  [facebook] Search '{query[:40]}': {len(posts)} posts")
    return posts


async def fetch_group_search(page, query: str) -> list[dict]:
    await goto(page, f"{FB_ROOT}/search/groups/?q={quote(query)}")
    await scroll(page, 3)
    groups = parse_group_search(await page.content())
    print(f"  [facebook] Group search '{query[:40]}': {len(groups)} groups")
    return groups


_JOIN_SELECTORS = (
    "div[aria-label='Join group']",
    "div[aria-label='Join Group']",
    "[role='button']:has-text('Join group')",
    "[role='button']:has-text('Join Group')",
)


async def join_group(page, url: str, answer: str) -> str:
    """
    Ask to join a group. Membership questions get `answer`; rule checkboxes are
    ticked. Returns 'member', 'pending', 'not_member' (couldn't click) — or the
    existing state when already a member / already requested.
    """
    state = detect_membership(await goto(page, url))
    if state in ("member", "pending"):
        return state

    for sel in _JOIN_SELECTORS:
        try:
            await page.click(sel, timeout=3_000)
            break
        except Exception:
            continue
    else:
        return "not_member"

    await page.wait_for_timeout(2_500)
    try:
        dialog = await page.wait_for_selector("div[role='dialog']", timeout=4_000)
    except Exception:
        dialog = None
    if dialog:
        for field in await dialog.query_selector_all("textarea, input[type='text']"):
            try:
                await field.fill(answer)
                await pause(300, 800)
            except Exception:
                pass
        for box in await dialog.query_selector_all("input[type='checkbox'], div[role='checkbox'][aria-checked='false']"):
            try:
                await box.click()
            except Exception:
                pass
        for sel in ("div[role='dialog'] div[aria-label='Submit']",
                    "div[role='dialog'] [role='button']:has-text('Submit')"):
            try:
                await page.click(sel, timeout=2_500)
                break
            except Exception:
                continue

    await page.wait_for_timeout(3_000)
    state = detect_membership(await page.content())
    return state if state in ("member", "pending") else "pending"


async def send_message(page, listing_url: str, message: str) -> bool:
    """Messenger DM to a Marketplace seller."""
    await goto(page, listing_url, wait_ms=3_000)
    for label in ("Message Seller", "Message seller", "Send Message"):
        try:
            await page.click(f"text={label}", timeout=4_000)
            break
        except Exception:
            continue
    else:
        return False
    try:
        await page.click("[aria-label='Message']", timeout=4_000)
        for ch in message:
            await page.keyboard.type(ch)
            await page.wait_for_timeout(random.randint(20, 80))
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2_000)
        return True
    except Exception as e:
        print(f"  [facebook] DM failed: {e}")
        return False


async def post_comment(page, post_url: str, comment: str) -> bool:
    """Comment on a group post."""
    await goto(page, post_url, wait_ms=4_000)
    for sel in ("[aria-label='Write a comment']", "[aria-label='Write a public comment']",
                "div[role='textbox'][aria-label*='comment']"):
        try:
            await page.click(sel, timeout=4_000)
        except Exception:
            continue
        for ch in comment:
            await page.keyboard.type(ch)
            await page.wait_for_timeout(random.randint(20, 70))
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2_000)
        return True
    return False
