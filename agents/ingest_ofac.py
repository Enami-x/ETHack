"""
/agents/ingest_ofac.py
======================
Stage 1 — Data Collection: OFAC SDN (Specially Designated Nationals) ingester

Responsibility:
    Download the OFAC SDN list CSV from the public Treasury.gov URL, filter for
    entries relevant to Iranian petroleum/shipping sanctions, and return raw_signal
    rows matching the §5 Stage 1 schema in ARCHITECTURE.md.

Source:  https://www.treasury.gov/ofac/downloads/sdn.csv  (public, no key required)
Format:  CSV with NO header row — columns are positional per dat_spec.txt

SDN.CSV column order (from dat_spec.txt, updated 2023-09-25):
    0  ent_num     — unique record identifier
    1  SDN_Name    — name of the SDN entity
    2  SDN_Type    — entity type (e.g. "individual", "entity", "vessel")
    3  Program     — sanctions program name(s), pipe-separated
    4  Title       — individual title
    5  Call_Sign   — vessel call sign
    6  Vess_type   — vessel type
    7  Tonnage     — vessel tonnage
    8  GRT         — gross registered tonnage
    9  Vess_flag   — vessel flag country
    10 Vess_owner  — vessel owner
    11 Remarks     — free-text remarks

Null values are encoded as "-0-" in OFAC's format — these are stripped on read.

Filtering design (precision over recall):
    The previous keyword-only filter matched ~4,282 entries (including Cuba cargo
    vessels, etc.) because terms like "PETROLEUM" and "SHIPPING" are common across
    many non-energy sanctions programmes. The new design uses a two-stage filter:

    STAGE A — Program code allowlist (PRIMARY filter):
        Only keep entries whose Program field contains at least one code from
        IRAN_PETROLEUM_PROGRAMS (see constants below). These are the specific OFAC
        programme codes for Iranian energy/shipping sanctions.
        Source: OFAC Programme Code Key (https://ofac.treasury.gov/sanctions-list-service)
        and the following US Treasury Executive Orders:
          - EO 13846 (2018): reimposed Iran energy/petroleum sanctions post-JCPOA
          - EO 13902 (2020): Iranian petroleum and petrochemical sector
          - EO 13382 (2005): WMD proliferators — frequently used for IRGC entities
          - Iran Threat Reduction and Syria Human Rights Act (ITRA, 2012)

    STAGE B — Type/remarks secondary filter (WITHIN program-matched entries):
        Keep entries where SDN_Type is "vessel" OR remarks contain at least one
        petroleum/shipping keyword from SECONDARY_REMARKS_TERMS.
        This removes individual human designees under Iran sanctions who have no
        direct petroleum/shipping nexus.

Expected result: tens to low hundreds of high-precision vessel/entity signals.
"""

import csv
import io
import re
import uuid
import logging
import pathlib
from datetime import datetime, timezone, timedelta

import requests


# =============================================================================
# CONFIGURATION CONSTANTS — tune without touching the function body
# =============================================================================

OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"

# Local cache path — only re-downloaded if older than CACHE_TTL_HOURS.
CACHE_DIR  = pathlib.Path(__file__).parent.parent / "cache"
CACHE_FILE = CACHE_DIR / "ofac_sdn.csv"
CACHE_TTL_HOURS: int = 24

# Request timeout in seconds.
OFAC_REQUEST_TIMEOUT: int = 30

# ---------------------------------------------------------------------------
# PRIMARY FILTER — OFAC programme codes for Iranian petroleum/shipping sanctions
#
# Source: OFAC Sanctions List Service programme code key
#         https://ofac.treasury.gov/sanctions-list-service
#         https://ofac.treasury.gov/faqs/topic/1541
#
# Included programmes:
#   IRAN-EO13846   — EO 13846 (Aug 2018): reimposed petroleum/shipping/financial
#                    sanctions on Iran following JCPOA withdrawal. Primary authority
#                    for Iranian crude oil tanker designations 2018-present.
#   IRAN-EO13902   — EO 13902 (Jan 2020): targets Iranian petroleum, petrochemical,
#                    construction, mining, and manufacturing sectors.
#   NPWMD          — Non-Proliferation of Weapons of Mass Destruction (EO 13382):
#                    frequently used for IRGC-affiliated shipping/energy entities.
#   IRGC           — Islamic Revolutionary Guard Corps: designated under multiple
#                    authorities; IRGC controls significant Iranian shipping/port assets.
#   IRAN-TRA       — Iran Threat Reduction and Syria Human Rights Act (2012):
#                    targets Iranian petroleum export revenues and energy sector.
#   IFSR           — Iranian Financial Sanctions Regulations (31 CFR 561):
#                    targets financial institutions facilitating Iran petroleum trade.
# ---------------------------------------------------------------------------
IRAN_PETROLEUM_PROGRAMS: list[str] = [
    "IRAN-EO13846",   # PRIMARY: petroleum/shipping/financial; post-JCPOA tanker sanctions
    "IRAN-EO13902",   # petroleum & petrochemical sector
    "NPWMD",          # WMD proliferators — covers IRGC shipping/energy network
    "IRGC",           # IRGC shipping, port, and energy asset designations
    "IRAN-TRA",       # Iran Threat Reduction Act — petroleum revenue sanctions
    "IFSR",           # Iranian Financial Sanctions Regs — petroleum trade finance
]

# ---------------------------------------------------------------------------
# SECONDARY FILTER — whole-word terms searched in Remarks field WITHIN
# program-matched entries. Removes human designees (individuals, entities)
# with no direct petroleum/maritime nexus.
#
# IMPORTANT: matching uses re.search with \b word boundaries so that e.g.
#   PORT  does NOT match inside "Passport"
#   OIL   does NOT match inside "Foil" or "Spoil"
#   IMO   does NOT match inside "Emir"
# Only whole-word occurrences count.
# ---------------------------------------------------------------------------
SECONDARY_REMARKS_TERMS: list[str] = [
    "TANKER",        # explicit vessel mention
    "VESSEL",        # generic vessel
    "PETROLEUM",     # petroleum sector
    "CRUDE",         # crude oil
    "LNG",           # liquified natural gas
    "MARITIME",      # maritime industry
    "SHIPPING",      # shipping operations
    "IMO",           # IMO number present → confirmed vessel record
    "MMSI",          # MMSI → vessel transponder identifier
    "CARGO",         # cargo operations
    "PETROCHEMICAL", # petrochemical sector
    # NOTE: "OIL" and "PORT" deliberately REMOVED — too short and substring-prone.
    # "OIL" matched inside words like FOIL/COIL; "PORT" matched inside "Passport".
    # Re-add only if word-boundary matching is verified sufficient for these.
]

# Pre-compiled word-boundary regex pattern for the secondary terms (case-insensitive).
# Built once at module load — O(1) per check instead of O(n) re-compilation.
_SECONDARY_PATTERN: re.Pattern = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in SECONDARY_REMARKS_TERMS) + r")\b",
    re.IGNORECASE,
)

# SDN.CSV column names (positional — file has no header row).
SDN_COLUMNS = [
    "ent_num", "SDN_Name", "SDN_Type", "Program", "Title",
    "Call_Sign", "Vess_type", "Tonnage", "GRT", "Vess_flag",
    "Vess_owner", "Remarks",
]

# OFAC null sentinel value
OFAC_NULL = "-0-"

# Corridor inference:
# If Program contains any IRAN_PROGRAM_CORRIDOR_TERMS → "hormuz"
# Extend this dict as Houthi / Red Sea designations are added.
CORRIDOR_INFERENCE_MAP: dict[str, list[str]] = {
    "hormuz": ["IRAN", "IRGC", "NPWMD", "IFSR"],
}


# =============================================================================
# LOGGER
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _clean(value: str) -> str:
    """Strip whitespace and replace OFAC null sentinel with empty string."""
    v = value.strip()
    return "" if v == OFAC_NULL else v


def _matches_program(row: dict) -> bool:
    """
    PRIMARY FILTER: Return True if the SDN row's Program field contains
    at least one code from IRAN_PETROLEUM_PROGRAMS (case-insensitive prefix match).
    OFAC encodes multiple programs as "IRAN-EO13846] [IRAN-EO13902" etc.
    """
    program_field = row.get("Program", "").upper()
    return any(code.upper() in program_field for code in IRAN_PETROLEUM_PROGRAMS)


def _matches_secondary(row: dict) -> tuple[bool, str]:
    """
    SECONDARY FILTER (applied WITHIN program-matched rows):
    Return (True, reason) if SDN_Type is 'vessel' OR the Remarks field
    contains a whole-word petroleum/shipping keyword from SECONDARY_REMARKS_TERMS.
    Return (False, "") otherwise.

    Uses pre-compiled word-boundary regex (_SECONDARY_PATTERN) to prevent
    substring false positives (e.g. PORT inside Passport, OIL inside Foil).
    """
    sdn_type = _clean(row.get("SDN_Type", "")).lower()
    if sdn_type == "vessel":
        return True, "sdn_type=vessel"

    remarks = row.get("Remarks", "")
    m = _SECONDARY_PATTERN.search(remarks)
    if m:
        return True, f"remarks keyword: {m.group(0).upper()}"

    return False, ""


def _infer_corridor(row: dict) -> str:
    """
    Infer pipeline corridor from the SDN entry's Program field.
    Default: 'other' — upgrade as additional corridor programs are added.
    """
    program_upper = row.get("Program", "").upper()
    for corridor, terms in CORRIDOR_INFERENCE_MAP.items():
        if any(t in program_upper for t in terms):
            return corridor
    return "other"


def _row_to_raw_signal(row: dict) -> dict:
    """Map one filtered SDN row to a raw_signals record."""
    return {
        "id":       str(uuid.uuid4()),
        "source":   "ofac",
        # OFAC SDN.CSV does not include individual designation timestamps.
        # Use ingestion time as the best available proxy.
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "corridor": _infer_corridor(row),
        "raw_payload": {
            "ent_num":    _clean(row.get("ent_num", "")),
            "name":       _clean(row.get("SDN_Name", "")),
            "sdn_type":   _clean(row.get("SDN_Type", "")),
            "program":    _clean(row.get("Program", "")),
            "call_sign":  _clean(row.get("Call_Sign", "")),
            "vess_type":  _clean(row.get("Vess_type", "")),
            "vess_flag":  _clean(row.get("Vess_flag", "")),
            "vess_owner": _clean(row.get("Vess_owner", "")),
            "remarks":    _clean(row.get("Remarks", "")),
        },
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def _cache_is_fresh() -> bool:
    """Return True if the cached CSV exists and is younger than CACHE_TTL_HOURS."""
    if not CACHE_FILE.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(
        CACHE_FILE.stat().st_mtime, tz=timezone.utc
    )
    return age < timedelta(hours=CACHE_TTL_HOURS)


def _download_sdn_csv() -> str | None:
    """
    Download the OFAC SDN CSV from Treasury.gov.
    Returns the raw CSV text, or None on failure.
    """
    logger.info("[OFAC] Downloading SDN list from %s", OFAC_SDN_URL)
    try:
        response = requests.get(OFAC_SDN_URL, timeout=OFAC_REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.content.decode("latin-1")
    except requests.exceptions.Timeout:
        logger.error("[OFAC] Download timed out after %ds.", OFAC_REQUEST_TIMEOUT)
    except requests.exceptions.ConnectionError as exc:
        logger.error("[OFAC] Connection error: %s", exc)
    except requests.exceptions.HTTPError as exc:
        logger.error("[OFAC] HTTP error %s: %s", response.status_code, exc)
    except requests.exceptions.RequestException as exc:
        logger.error("[OFAC] Unexpected request error: %s", exc)
    return None


def _load_csv_text(csv_text: str) -> list[dict]:
    """Parse the SDN CSV text (no header) into a list of row dicts."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = []
    for raw_row in reader:
        padded = (raw_row + [""] * len(SDN_COLUMNS))[: len(SDN_COLUMNS)]
        rows.append(dict(zip(SDN_COLUMNS, padded)))
    return rows


# =============================================================================
# PUBLIC API
# =============================================================================

def fetch_ofac_signals() -> list[dict]:
    """
    Fetch and filter OFAC SDN entries for Iranian petroleum/shipping sanctions.

    Two-stage filtering for high precision:
        Stage A (Program codes): keep only entries under IRAN_PETROLEUM_PROGRAMS
        Stage B (Remarks/type):  within those, keep vessels or petroleum-related entries

    Caching behaviour:
        - If cache/ofac_sdn.csv exists and is < CACHE_TTL_HOURS old, uses it.
        - Otherwise, downloads fresh from Treasury.gov and saves to cache.

    Returns:
        List of raw_signal dicts matching §5 Stage 1 schema.
        Returns an empty list on any download or parse failure (does NOT raise).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load from cache or download ---
    if _cache_is_fresh():
        logger.info("[OFAC] Using cached SDN list: %s", CACHE_FILE)
        try:
            csv_text = CACHE_FILE.read_text(encoding="latin-1")
        except OSError as exc:
            logger.error("[OFAC] Failed to read cache: %s. Will re-download.", exc)
            csv_text = None
    else:
        csv_text = _download_sdn_csv()
        if csv_text is not None:
            try:
                CACHE_FILE.write_text(csv_text, encoding="latin-1")
                logger.info("[OFAC] Saved SDN list to cache: %s", CACHE_FILE)
            except OSError as exc:
                logger.warning("[OFAC] Failed to write cache: %s", exc)

    if csv_text is None:
        logger.error("[OFAC] No SDN data available. Returning empty list.")
        return []

    # --- Parse ---
    try:
        all_rows = _load_csv_text(csv_text)
    except Exception as exc:
        logger.error("[OFAC] CSV parse error: %s. Returning empty list.", exc)
        return []

    total = len(all_rows)

    # --- Stage A: program code filter ---
    program_matched = [r for r in all_rows if _matches_program(r)]

    logger.info(
        "[OFAC] Secondary filter keyword list (whole-word, case-insensitive):\n        %s",
        ", ".join(SECONDARY_REMARKS_TERMS),
    )

    # --- Stage B: vessel/remarks secondary filter (word-boundary regex) ---
    matched_with_reasons = [
        (r, reason)
        for r in program_matched
        for passed, reason in [_matches_secondary(r)]
        if passed
    ]
    final_matched = [r for r, _ in matched_with_reasons]
    match_reasons = {r.get("ent_num", ""): reason for r, reason in matched_with_reasons}

    signals = [_row_to_raw_signal(row) for row in final_matched]

    logger.info(
        "[OFAC] Precision filter results: "
        "%d total SDN entries → %d program-matched (Iran/petroleum) → "
        "%d vessel/petroleum-relevant (word-boundary filter) → %d signals produced.",
        total, len(program_matched), len(final_matched), len(signals),
    )
    return signals, match_reasons
