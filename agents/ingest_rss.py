"""
/agents/ingest_rss.py
=====================
Stage 1 — Data Collection: RSS feed ingester

Responsibility:
    Fetch recent articles from curated RSS feeds, filter by date (last 3 days) and
    corridor relevance (keyword matching), and return raw_signal rows matching the
    §5 Stage 1 schema.

Source: Curated list of energy, maritime, and geopolitical RSS feeds.
Format: Standard RSS/Atom XML (parsed via feedparser).
"""

import time
import uuid
import logging
from datetime import datetime, timezone, timedelta

import feedparser

# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Curated, verified live RSS feeds
RSS_FEEDS = {
    "gcaptain": "https://gcaptain.com/feed/",
    "oilprice": "https://oilprice.com/rss/main",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "bbc_me": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
}

# Maximum age of articles to ingest (days)
MAX_AGE_DAYS: int = 3

# Delay (seconds) between fetching different feeds to be polite
INTER_FEED_DELAY_S: int = 1

# Keyword matching sets for corridor relevance (case-insensitive)
CORRIDOR_KEYWORDS = {
    "hormuz": [
        "hormuz", 
        "strait of hormuz", 
        "persian gulf", 
        "iran tanker", 
        "iranian tanker", 
        "oman gulf", 
        "gulf of oman"
    ],
    "red_sea": [
        "red sea", 
        "houthi", 
        "bab el-mandeb", 
        "yemen tanker", 
        "suez", 
        "gulf of aden"
    ],
    "suez": [
        "suez canal",
        "ever given",
        "egypt transit"
    ]
}

# =============================================================================
# LOGGER
# =============================================================================
logger = logging.getLogger(__name__)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _parse_published_date(entry) -> datetime:
    """Extract and parse published date from a feedparser entry, returning UTC datetime."""
    # feedparser standardizes dates into a 9-tuple time struct in `published_parsed`
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        return datetime.fromtimestamp(time.mktime(entry.published_parsed), timezone.utc)
    return datetime.now(timezone.utc)


def _is_recent(pub_date: datetime) -> bool:
    """Check if the article was published within MAX_AGE_DAYS."""
    age = datetime.now(timezone.utc) - pub_date
    return age <= timedelta(days=MAX_AGE_DAYS)


def _infer_corridors(title: str, summary: str) -> list[str]:
    """Return a list of matched corridors based on keyword search in title and summary."""
    text = (title + " " + summary).lower()
    matched = []
    
    for corridor, keywords in CORRIDOR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(corridor)
            
    return matched


def _entry_to_raw_signal(feed_name: str, entry, corridor: str, pub_date: datetime) -> dict:
    """Map a feed entry to a raw_signals record."""
    title = getattr(entry, 'title', '')
    link = getattr(entry, 'link', '')
    summary = getattr(entry, 'summary', '')
    
    return {
        "id":          str(uuid.uuid4()),
        "source":      "rss",
        "timestamp":   pub_date.isoformat(),
        "corridor":    corridor,
        "raw_payload": {
            "feed_name": feed_name,
            "title":     title,
            "link":      link,
            "published": pub_date.isoformat(),
            "summary":   summary,
        },
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def fetch_rss_signals(target_corridor: str) -> list[dict]:
    """
    Fetch RSS feeds and return signals relevant to the target_corridor.

    Args:
        target_corridor: e.g., "hormuz", "red_sea". If "other", returns signals 
                         that didn't match any specific corridor.

    Returns:
        List of raw_signal dicts matching §5 Stage 1 schema.
    """
    signals = []
    
    for feed_name, feed_url in RSS_FEEDS.items():
        logger.info("[RSS] Fetching feed: %s (%s)", feed_name, feed_url)
        
        try:
            # feedparser handles download and parsing safely without crashing
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and hasattr(feed.bozo_exception, 'getMessage'):
                # bozo = 1 indicates poorly formed XML or network issues
                logger.warning(
                    "[RSS] Feed '%s' returned bozo exception: %s. Skipping.", 
                    feed_name, feed.bozo_exception
                )
                continue
                
            if feed.status and feed.status >= 400:
                logger.warning(
                    "[RSS] Feed '%s' returned HTTP %s. Skipping.", 
                    feed_name, feed.status
                )
                continue
                
        except Exception as exc:
            logger.warning("[RSS] Unexpected error fetching '%s': %s. Skipping.", feed_name, exc)
            continue
            
        entries = feed.entries
        logger.info("[RSS] %s returned %d entries.", feed_name, len(entries))
        
        for entry in entries:
            pub_date = _parse_published_date(entry)
            
            if not _is_recent(pub_date):
                continue
                
            title = getattr(entry, 'title', '')
            summary = getattr(entry, 'summary', '')
            matched_corridors = _infer_corridors(title, summary)
            
            # Decide if this entry belongs in the target_corridor
            # If target is specific (e.g. "hormuz"), it must be in matched_corridors.
            # If target is "other", it should NOT match any specific corridor.
            is_match = False
            if target_corridor in CORRIDOR_KEYWORDS:
                if target_corridor in matched_corridors:
                    is_match = True
            elif target_corridor == "other":
                if not matched_corridors:
                    is_match = True
                    
            if is_match:
                signals.append(_entry_to_raw_signal(feed_name, entry, target_corridor, pub_date))
                
        # Polite delay between feeds
        time.sleep(INTER_FEED_DELAY_S)
        
    logger.info("[RSS] Fetched %d total signal(s) for corridor='%s'.", len(signals), target_corridor)
    return signals
