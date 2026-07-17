"""
/agents/ingest_gdelt.py
=======================
Stage 1 — Data Collection: GDELT 2.0 DOC API ingester

Responsibility:
    Query the GDELT 2.0 Full-Text Search API for recent news articles matching an
    energy-corridor query and return raw_signal rows matching the §5 Stage 1 schema.

API:  https://api.gdeltproject.org/api/v2/doc/doc  (free, no key required)
Mode: ArtList (article list with metadata per article)

Rate limiting:
    GDELT throttles server-side requests with HTTP 429. This module handles 429s
    with exponential backoff (GDELT_RETRY_DELAYS) and retries up to GDELT_MAX_RETRIES
    times before returning an empty list. A mandatory inter-call delay
    (GDELT_INTER_CALL_DELAY_S) is applied between successive calls from the same run
    to stay polite. On final failure the pipeline continues — no crash.

Note: GDELT ArtList does NOT include per-article tone scores — those live in the GKG
      (Global Knowledge Graph) on BigQuery. We store the article metadata here and
      derive severity_hint from the GKG tone only if we connect BigQuery later.
      For now, raw_payload includes all available GDELT fields verbatim.
"""

import time
import uuid
import logging
from datetime import datetime, timezone

import requests


# =============================================================================
# CONFIGURATION CONSTANTS — tune without touching the function body
# =============================================================================

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Maximum articles to fetch per corridor query.
GDELT_MAX_RECORDS: int = 25

# Request timeout in seconds.
GDELT_REQUEST_TIMEOUT: int = 15

# Mandatory delay (seconds) inserted BEFORE every GDELT call within the same run.
# Prevents consecutive queries from triggering the 429 rate limit.
GDELT_INTER_CALL_DELAY_S: int = 6

# Maximum number of retry attempts on HTTP 429 (Too Many Requests).
# Set to 0 to disable retries.
GDELT_MAX_RETRIES: int = 2

# Exponential backoff delays in seconds for each retry attempt (index 0 = first retry).
# Must have at least GDELT_MAX_RETRIES entries.
GDELT_RETRY_DELAYS: list[int] = [10, 20]

# Valid corridor values accepted by the pipeline.
VALID_CORRIDORS = {"hormuz", "red_sea", "suez", "other"}


# =============================================================================
# LOGGER
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _parse_gdelt_timestamp(seendate: str) -> str:
    """
    Convert GDELT's seendate format (YYYYMMDDTHHMMSSZ) to ISO8601.
    Falls back to current UTC time if parsing fails.
    """
    try:
        # GDELT seendate: "20240715T140000Z"
        dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


def _article_to_raw_signal(article: dict, corridor: str) -> dict:
    """
    Map a single GDELT ArtList article dict to a raw_signals row.

    GDELT ArtList fields available:
        url, url_mobile, title, seendate, socialimage, domain, language, sourcecountry

    raw_payload stores all GDELT fields verbatim so Stage 2 can access them.
    """
    return {
        "id":          str(uuid.uuid4()),
        "source":      "gdelt",
        "timestamp":   _parse_gdelt_timestamp(article.get("seendate", "")),
        "corridor":    corridor,
        "raw_payload": {
            "title":         article.get("title", ""),
            "url":           article.get("url", ""),
            "seendate":      article.get("seendate", ""),
            "domain":        article.get("domain", ""),
            "language":      article.get("language", ""),
            "sourcecountry": article.get("sourcecountry", ""),
            "socialimage":   article.get("socialimage", ""),
            # tone/sentiment: not available in ArtList — would require GKG BigQuery join
            # TODO: integrate GKG tone via BigQuery API if time permits
            "tone":          None,
        },
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def _gdelt_request_with_retry(params: dict, corridor: str) -> requests.Response | None:
    """
    Execute a GDELT API GET request with exponential backoff on HTTP 429.

    Strategy:
        Attempt 1  — immediate
        Attempt 2  — wait GDELT_RETRY_DELAYS[0] seconds after 429
        Attempt 3  — wait GDELT_RETRY_DELAYS[1] seconds after 429
        After GDELT_MAX_RETRIES exhausted — return None

    Returns the successful Response object, or None on final failure.
    Logs each attempt, 429 event, backoff duration, and final outcome clearly.
    """
    for attempt in range(1, GDELT_MAX_RETRIES + 2):  # +2: attempt 1 is the initial try
        try:
            logger.info(
                "[GDELT] corridor='%s' — attempt %d/%d",
                corridor, attempt, GDELT_MAX_RETRIES + 1,
            )
            response = requests.get(
                GDELT_DOC_API_URL,
                params=params,
                timeout=GDELT_REQUEST_TIMEOUT,
            )

            if response.status_code == 429:
                if attempt <= GDELT_MAX_RETRIES:
                    delay = GDELT_RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "[GDELT] corridor='%s' — attempt %d received HTTP 429 "
                        "(Too Many Requests). Backing off %ds before retry.",
                        corridor, attempt, delay,
                    )
                    time.sleep(delay)
                    continue  # retry
                else:
                    logger.error(
                        "[GDELT] corridor='%s' — HTTP 429 on attempt %d/%d. "
                        "All retries exhausted. Returning empty list.",
                        corridor, attempt, GDELT_MAX_RETRIES + 1,
                    )
                    return None

            response.raise_for_status()
            return response  # success

        except requests.exceptions.Timeout:
            logger.error(
                "[GDELT] corridor='%s' — attempt %d timed out after %ds. "
                "Returning empty list.",
                corridor, attempt, GDELT_REQUEST_TIMEOUT,
            )
            return None
        except requests.exceptions.ConnectionError as exc:
            logger.error(
                "[GDELT] corridor='%s' — attempt %d connection error: %s. "
                "Returning empty list.",
                corridor, attempt, exc,
            )
            return None
        except requests.exceptions.HTTPError as exc:
            logger.error(
                "[GDELT] corridor='%s' — attempt %d HTTP error %s: %s. "
                "Returning empty list.",
                corridor, attempt, response.status_code, exc,
            )
            return None
        except requests.exceptions.RequestException as exc:
            logger.error(
                "[GDELT] corridor='%s' — attempt %d unexpected error: %s. "
                "Returning empty list.",
                corridor, attempt, exc,
            )
            return None

    return None  # safety fallback (should not reach here)


# =============================================================================
# PUBLIC API
# =============================================================================

def fetch_gdelt_signals(query: str, corridor: str) -> list[dict]:
    """
    Query the GDELT 2.0 DOC API and return a list of raw_signal rows.

    A mandatory inter-call delay of GDELT_INTER_CALL_DELAY_S is applied at the
    start of every call to prevent triggering the 429 rate limit on successive
    corridor queries within the same run.

    Args:
        query:    Full-text search string, e.g. "Hormuz OR 'Strait of Hormuz' oil tanker"
        corridor: Pipeline corridor label — must be one of VALID_CORRIDORS.

    Returns:
        List of raw_signal dicts matching §5 Stage 1 schema.
        Returns an empty list on any network or API error (does NOT raise).

    Example:
        signals = fetch_gdelt_signals(
            query="Hormuz OR 'Strait of Hormuz' oil tanker",
            corridor="hormuz",
        )
    """
    if corridor not in VALID_CORRIDORS:
        logger.error(
            "[GDELT] Invalid corridor '%s'. Must be one of %s. Returning empty list.",
            corridor, VALID_CORRIDORS,
        )
        return []

    # Mandatory inter-call delay — applied before every call to stay rate-limit safe
    logger.info(
        "[GDELT] Waiting %ds (inter-call delay) before querying corridor='%s'.",
        GDELT_INTER_CALL_DELAY_S, corridor,
    )
    time.sleep(GDELT_INTER_CALL_DELAY_S)

    params = {
        "query":      query,
        "mode":       "artlist",
        "maxrecords": GDELT_MAX_RECORDS,
        "format":     "json",
        "sort":       "DateDesc",   # newest first
        "timespan":   "3d",         # last 3 days — keeps data fresh for live demo
    }

    response = _gdelt_request_with_retry(params, corridor)
    if response is None:
        return []

    try:
        data = response.json()
    except ValueError as exc:
        logger.error(
            "[GDELT] Failed to parse JSON response for corridor='%s': %s. Body: %s",
            corridor, exc, response.text[:200],
        )
        return []

    articles = data.get("articles", [])
    if not articles:
        logger.warning(
            "[GDELT] No articles returned for corridor='%s' (query: %s).",
            corridor, query,
        )
        return []

    signals = [_article_to_raw_signal(article, corridor) for article in articles]
    logger.info("[GDELT] Fetched %d signal(s) for corridor='%s'.", len(signals), corridor)
    return signals
