"""
Facebook integration
--------------------
  parsing.py  pure text/HTML parsing (posts, marketplace cards, group search)
  session.py  which Facebook session to use: a user's connected account,
              FB_COOKIES_JSON, .fb_cookies.json, or an email/password login
  store.py    Supabase persistence (connections, group catalog, leads)
  browser.py  Camoufox browser lifecycle + login-wall detection
  actions.py  page-level operations (scrape feed, search groups, join group)

Entry points live elsewhere:
  agents/scrapers/facebook_agent.py  scrape_facebook() for the search pipeline
  agents/fb_groups_agent.py          group discovery + lead harvesting agent
"""
