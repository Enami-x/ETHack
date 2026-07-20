"""
/agents/routing_advisor.py
==========================
Geopolitical Routing Advisor Agent

Responsibility:
    Assess shipping routes based on live geopolitical risk scores and crude oil
    prices (EIA Brent). Generates alternative paths with coordinates, calculates
    costs and transit times, makes recommendation decisions, and generates a
    decision walkthrough using Gemini.
"""

import os
import math
import logging
import pathlib
from datetime import datetime, timezone
from google import genai
from dotenv import load_dotenv

# Load .env
_env_path = pathlib.Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

logger = logging.getLogger(__name__)

# Model config — gemini-2.5-flash is the correct fast model
GEMINI_MODEL_NAME = "gemini-2.5-flash"


def _init_gemini() -> genai.Client | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[RoutingAdvisor] GEMINI_API_KEY not set - LLM rationale disabled.")
        return None
    return genai.Client(api_key=api_key)


_gemini_client = _init_gemini()

# ─────────────────────────────────────────────────────────────────────────────
# Port Registry
# ─────────────────────────────────────────────────────────────────────────────
PORTS: dict[str, dict] = {
    "ras_tanura": {
        "name": "Ras Tanura, Saudi Arabia (Persian Gulf)",
        "coords": [26.7, 50.1],
        "region": "Persian Gulf",
    },
    "yanbu": {
        "name": "Yanbu, Saudi Arabia (Red Sea)",
        "coords": [24.0, 38.0],
        "region": "Red Sea",
    },
    "fujairah": {
        "name": "Fujairah, UAE (Gulf of Oman)",
        "coords": [25.1, 56.4],
        "region": "Gulf of Oman",
    },
    "basrah": {
        "name": "Basrah, Iraq (Persian Gulf)",
        "coords": [30.5, 47.8],
        "region": "Persian Gulf",
    },
    "kuwait_city": {
        "name": "Kuwait City, Kuwait (Persian Gulf)",
        "coords": [29.4, 48.0],
        "region": "Persian Gulf",
    },
    "houston": {
        "name": "Houston, USA (Gulf of Mexico)",
        "coords": [29.7, -95.3],
        "region": "Gulf of Mexico",
    },
    "rotterdam": {
        "name": "Rotterdam, Netherlands (North Sea)",
        "coords": [51.9, 4.5],
        "region": "North Sea",
    },
    "singapore": {
        "name": "Singapore (Strait of Malacca)",
        "coords": [1.3, 103.8],
        "region": "Southeast Asia",
    },
    "novorossiysk": {
        "name": "Novorossiysk, Russia (Black Sea)",
        "coords": [44.7, 37.8],
        "region": "Black Sea",
    },
    "vadinar": {
        "name": "Vadinar Port, India (West Coast)",
        "coords": [22.4, 69.7],
        "region": "Indian Ocean",
    },
    "chennai": {
        "name": "Chennai Port, India (East Coast)",
        "coords": [13.1, 80.3],
        "region": "Indian Ocean",
    },
    "mumbai": {
        "name": "Mumbai (JNPT), India (West Coast)",
        "coords": [18.9, 72.9],
        "region": "Indian Ocean",
    },
}

# Fuzzy alias → canonical port ID
PORT_ALIASES: dict[str, str] = {
    # Saudi Arabia
    "ras tanura": "ras_tanura",
    "rastanura": "ras_tanura",
    "saudi arabia gulf": "ras_tanura",
    "yanbu": "yanbu",
    # UAE / Gulf of Oman
    "fujairah": "fujairah",
    "uae": "fujairah",
    # Iraq
    "basrah": "basrah",
    "basra": "basrah",
    "iraq": "basrah",
    # Kuwait
    "kuwait": "kuwait_city",
    "kuwait city": "kuwait_city",
    # USA
    "houston": "houston",
    "usa": "houston",
    "us gulf coast": "houston",
    # Netherlands
    "rotterdam": "rotterdam",
    "netherlands": "rotterdam",
    "europe": "rotterdam",
    # Singapore
    "singapore": "singapore",
    "sg": "singapore",
    # Russia
    "novorossiysk": "novorossiysk",
    "russia": "novorossiysk",
    "black sea": "novorossiysk",
    # India
    "vadinar": "vadinar",
    "india west": "vadinar",
    "chennai": "chennai",
    "india east": "chennai",
    "madras": "chennai",
    "mumbai": "mumbai",
    "bombay": "mumbai",
    "jnpt": "mumbai",
}


def resolve_port_id(name: str) -> str | None:
    """Resolve a user-typed name to a canonical port ID. Returns None if unrecognised."""
    normalised = name.strip().lower().replace("-", " ").replace("_", " ")
    if normalised in PORTS:
        return normalised
    if normalised in PORT_ALIASES:
        return PORT_ALIASES[normalised]
    # partial match fallback
    for alias, pid in PORT_ALIASES.items():
        if normalised in alias or alias in normalised:
            return pid
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Chokepoint / Waypoint Library
# ─────────────────────────────────────────────────────────────────────────────
WAYPOINTS: dict[str, list[float]] = {
    "hormuz":             [26.5, 56.3],
    "fujairah_wp":        [25.1, 56.4],
    "bab_el_mandeb":      [12.6, 43.4],
    "gulf_of_aden":       [12.0, 46.0],
    "suez_canal":         [30.5, 32.5],
    "suez_south":         [29.9, 32.5],
    "mediterranean_east": [34.0, 34.0],
    "mediterranean_mid":  [34.0, 20.0],
    "mediterranean_west": [38.0, 5.0],
    "gibraltar":          [36.0, -5.3],
    "bay_of_biscay":      [46.0, -8.0],
    "english_channel":    [50.5, 1.5],
    "north_sea_south":    [52.0, 3.5],
    "mid_atlantic":       [30.0, -45.0],
    "south_atlantic":     [-20.0, -20.0],
    "west_africa":        [15.0, -18.0],
    "cape_of_good_hope":  [-34.4, 18.5],
    "south_indian":       [-20.0, 45.0],
    "east_indian":        [-10.0, 70.0],
    "malacca_north":      [5.0, 99.0],
    "south_china_sea":    [10.0, 110.0],
    "bosphorus":          [41.0, 29.0],
    "dardanelles":        [40.2, 26.4],
    "aegean_sea":         [38.0, 25.0],
}

# Corridor risk zones for map display (center + radius label)
CORRIDOR_ZONES = {
    "hormuz":  {"label": "Strait of Hormuz", "coords": [26.5, 56.3], "radius_km": 120},
    "red_sea": {"label": "Bab-el-Mandeb / Red Sea", "coords": [12.6, 43.4], "radius_km": 200},
    "suez":    {"label": "Suez Canal", "coords": [30.5, 32.5], "radius_km": 100},
}

# Geopolitical situation text per corridor (updated periodically — mock for now)
CORRIDOR_SITUATIONS: dict[str, str] = {
    "hormuz": (
        "Strait of Hormuz remains under elevated tension following Iranian naval exercises and "
        "recent IRGC speedboat intercepts of commercial tankers. US 5th Fleet maintains active "
        "patrol presence. Transit risk is classified as significant."
    ),
    "red_sea": (
        "Houthi forces continue ballistic missile and drone attacks on commercial shipping in the "
        "Red Sea and Gulf of Aden. The MSC and other major carriers have diverted via Cape of Good Hope. "
        "War-risk insurance premiums in this corridor are at multi-year highs."
    ),
    "suez": (
        "Suez Canal transit is operational with Egyptian authorities maintaining normal scheduling. "
        "However, approach through the Red Sea and Bab-el-Mandeb remains the primary risk vector for "
        "southbound and northbound vessels. Convoy operations available."
    ),
    "black_sea": (
        "Black Sea operations remain constrained following Russia–Ukraine conflict. The UN-brokered "
        "grain corridor has lapsed. Bosphorus transit is unaffected for non-Russian-flagged vessels."
    ),
    "malacca": (
        "Strait of Malacca sees routine piracy incidents but no state-level threat. Singapore Coast Guard "
        "and regional navies maintain active interdiction. Risk is low compared to Middle East corridors."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Route Graph
# Each entry defines a segment of a route path between two port groups.
# We build full routes by composing segments based on geographic logic.
# ─────────────────────────────────────────────────────────────────────────────

def _gulf_to_indian_routes(origin_id: str, dest_id: str) -> list[dict]:
    """Routes from Persian Gulf / Red Sea origins to Indian subcontinent destinations."""
    op = PORTS[origin_id]["coords"]
    dp = PORTS[dest_id]["coords"]

    dest_wp = []
    if dest_id in ("chennai",):
        dest_wp = [[dp[0] + 2, dp[1] - 3]]  # approach waypoint
    elif dest_id in ("mumbai",):
        dest_wp = [[dp[0] - 1, dp[1] - 2]]

    routes = []

    # ── Route A: Via Strait of Hormuz (if origin is Persian Gulf) ─────────
    if PORTS[origin_id]["region"] == "Persian Gulf":
        routes.append({
            "id": f"{origin_id[:3]}_{dest_id[:3]}_hormuz",
            "name": f"Standard Route — Strait of Hormuz → Indian Ocean",
            "corridors_crossed": ["hormuz"],
            "base_days": round(1200 / 350 + 0.5, 1),  # ~1200 NM
            "base_distance_nm": 1200 + int(abs(dp[1] - 70) * 15),
            "transit_toll_usd": 0,
            "waypoints": [op, WAYPOINTS["hormuz"], WAYPOINTS["fujairah_wp"]] + dest_wp + [dp],
        })

    # ── Route B: Via Red Sea / Bab-el-Mandeb ─────────────────────────────
    if PORTS[origin_id]["region"] in ("Persian Gulf", "Red Sea"):
        yanbu = PORTS["yanbu"]["coords"]
        mid = [yanbu] if origin_id != "yanbu" else []
        routes.append({
            "id": f"{origin_id[:3]}_{dest_id[:3]}_redsea",
            "name": "Divert — East-West Pipeline / Red Sea → Bab-el-Mandeb",
            "corridors_crossed": ["hormuz", "red_sea"] if PORTS[origin_id]["region"] == "Persian Gulf" else ["red_sea"],
            "base_days": round(2300 / 350 + 0.8, 1),
            "base_distance_nm": 2300 + int(abs(dp[1] - 70) * 15),
            "transit_toll_usd": 85_000,
            "waypoints": [op] + mid + [WAYPOINTS["bab_el_mandeb"], WAYPOINTS["gulf_of_aden"]] + dest_wp + [dp],
        })

    # ── Route C: Cape of Good Hope (ultra-long bypass) ───────────────────
    routes.append({
        "id": f"{origin_id[:3]}_{dest_id[:3]}_cape",
        "name": "Long Bypass — Cape of Good Hope (Hormuz + Red Sea free)",
        "corridors_crossed": [],
        "base_days": round(9500 / 350 + 1.5, 1),
        "base_distance_nm": 9500,
        "transit_toll_usd": 0,
        "waypoints": [
            op,
            WAYPOINTS["west_africa"],
            WAYPOINTS["cape_of_good_hope"],
            WAYPOINTS["south_indian"],
            WAYPOINTS["east_indian"],
        ] + dest_wp + [dp],
    })

    return routes


def _gulf_to_europe_routes(origin_id: str, dest_id: str) -> list[dict]:
    """Routes from Persian Gulf / Red Sea to European ports."""
    op = PORTS[origin_id]["coords"]
    dp = PORTS[dest_id]["coords"]

    routes = []

    # ── Route A: Strait of Hormuz → Red Sea → Suez Canal → Mediterranean ──
    pre = []
    if PORTS[origin_id]["region"] == "Persian Gulf":
        pre = [WAYPOINTS["hormuz"], WAYPOINTS["fujairah_wp"]]
        corridor_list = ["hormuz", "red_sea", "suez"]
        nm = 6400
    else:
        corridor_list = ["red_sea", "suez"]
        nm = 5000

    routes.append({
        "id": f"{origin_id[:3]}_{dest_id[:3]}_suez",
        "name": "Suez Canal Route — Red Sea → Mediterranean",
        "corridors_crossed": corridor_list,
        "base_days": round(nm / 350 + 1.0, 1),
        "base_distance_nm": nm,
        "transit_toll_usd": 380_000,
        "waypoints": [op] + pre + [
            WAYPOINTS["bab_el_mandeb"],
            WAYPOINTS["suez_south"],
            WAYPOINTS["suez_canal"],
            WAYPOINTS["mediterranean_east"],
            WAYPOINTS["mediterranean_mid"],
            WAYPOINTS["mediterranean_west"],
            WAYPOINTS["gibraltar"],
            WAYPOINTS["bay_of_biscay"],
            dp,
        ],
    })

    # ── Route B: Cape of Good Hope → Atlantic ─────────────────────────────
    routes.append({
        "id": f"{origin_id[:3]}_{dest_id[:3]}_cape",
        "name": "Cape of Good Hope Bypass — Avoids Hormuz & Suez",
        "corridors_crossed": [],
        "base_days": round(11800 / 350 + 2.0, 1),
        "base_distance_nm": 11_800,
        "transit_toll_usd": 0,
        "waypoints": [
            op,
            WAYPOINTS["west_africa"],
            WAYPOINTS["cape_of_good_hope"],
            WAYPOINTS["south_atlantic"],
            WAYPOINTS["mid_atlantic"],
            WAYPOINTS["gibraltar"],
            WAYPOINTS["bay_of_biscay"],
            dp,
        ],
    })

    return routes


def _gulf_to_houston_routes(origin_id: str, dest_id: str) -> list[dict]:
    """Routes from Persian Gulf / Red Sea to US Gulf Coast (Houston)."""
    op = PORTS[origin_id]["coords"]
    dp = PORTS[dest_id]["coords"]

    pre_suez = [WAYPOINTS["hormuz"]] if PORTS[origin_id]["region"] == "Persian Gulf" else []
    corridor_suez = ["hormuz", "red_sea", "suez"] if PORTS[origin_id]["region"] == "Persian Gulf" else ["red_sea", "suez"]

    routes = [
        {
            "id": f"{origin_id[:3]}_hou_suez",
            "name": "Suez Canal → Mediterranean → Atlantic",
            "corridors_crossed": corridor_suez,
            "base_days": round(9200 / 350 + 2.0, 1),
            "base_distance_nm": 9_200,
            "transit_toll_usd": 380_000,
            "waypoints": [op] + pre_suez + [
                WAYPOINTS["bab_el_mandeb"],
                WAYPOINTS["suez_south"],
                WAYPOINTS["suez_canal"],
                WAYPOINTS["mediterranean_mid"],
                WAYPOINTS["gibraltar"],
                WAYPOINTS["mid_atlantic"],
                dp,
            ],
        },
        {
            "id": f"{origin_id[:3]}_hou_cape",
            "name": "Cape of Good Hope → South Atlantic",
            "corridors_crossed": [],
            "base_days": round(12800 / 350 + 2.5, 1),
            "base_distance_nm": 12_800,
            "transit_toll_usd": 0,
            "waypoints": [
                op,
                WAYPOINTS["cape_of_good_hope"],
                WAYPOINTS["south_atlantic"],
                WAYPOINTS["mid_atlantic"],
                dp,
            ],
        },
    ]
    return routes


def _black_sea_routes(origin_id: str, dest_id: str) -> list[dict]:
    """Routes from Novorossiysk (Black Sea) to any destination."""
    op = PORTS[origin_id]["coords"]
    dp = PORTS[dest_id]["coords"]
    dest_region = PORTS[dest_id]["region"]

    bosphorus_leg = [op, WAYPOINTS["bosphorus"], WAYPOINTS["dardanelles"], WAYPOINTS["aegean_sea"]]

    if dest_region in ("Indian Ocean",):
        return [
            {
                "id": f"nov_{dest_id[:3]}_suez",
                "name": "Bosphorus → Suez Canal → Indian Ocean",
                "corridors_crossed": ["red_sea", "suez"],
                "base_days": round(5500 / 350 + 1.5, 1),
                "base_distance_nm": 5_500,
                "transit_toll_usd": 320_000,
                "waypoints": bosphorus_leg + [
                    WAYPOINTS["mediterranean_east"],
                    WAYPOINTS["suez_canal"],
                    WAYPOINTS["bab_el_mandeb"],
                    WAYPOINTS["gulf_of_aden"],
                    dp,
                ],
            },
            {
                "id": f"nov_{dest_id[:3]}_cape",
                "name": "Bosphorus → Cape of Good Hope (Long Bypass)",
                "corridors_crossed": [],
                "base_days": round(14000 / 350 + 3.0, 1),
                "base_distance_nm": 14_000,
                "transit_toll_usd": 0,
                "waypoints": bosphorus_leg + [
                    WAYPOINTS["gibraltar"],
                    WAYPOINTS["west_africa"],
                    WAYPOINTS["cape_of_good_hope"],
                    WAYPOINTS["south_indian"],
                    dp,
                ],
            },
        ]

    if dest_region in ("North Sea",):
        return [
            {
                "id": f"nov_{dest_id[:3]}_direct",
                "name": "Bosphorus → Mediterranean → Atlantic → North Sea",
                "corridors_crossed": [],
                "base_days": round(3800 / 350 + 1.0, 1),
                "base_distance_nm": 3_800,
                "transit_toll_usd": 50_000,
                "waypoints": bosphorus_leg + [
                    WAYPOINTS["mediterranean_mid"],
                    WAYPOINTS["gibraltar"],
                    WAYPOINTS["bay_of_biscay"],
                    WAYPOINTS["english_channel"],
                    dp,
                ],
            },
        ]

    # Default for gulf / US destinations
    return [
        {
            "id": f"nov_{dest_id[:3]}_suez",
            "name": "Bosphorus → Suez → Destination",
            "corridors_crossed": ["red_sea", "suez"],
            "base_days": round(6000 / 350 + 1.5, 1),
            "base_distance_nm": 6_000,
            "transit_toll_usd": 320_000,
            "waypoints": bosphorus_leg + [
                WAYPOINTS["mediterranean_east"],
                WAYPOINTS["suez_canal"],
                WAYPOINTS["bab_el_mandeb"],
                dp,
            ],
        },
    ]


def _singapore_routes(origin_id: str, dest_id: str) -> list[dict]:
    """Routes from/to Singapore."""
    op = PORTS[origin_id]["coords"]
    dp = PORTS[dest_id]["coords"]

    if PORTS[dest_id]["region"] in ("Indian Ocean",) or dest_id in ("vadinar", "mumbai", "chennai"):
        return [
            {
                "id": f"sgp_{dest_id[:3]}_malacca",
                "name": "Strait of Malacca → Indian Ocean",
                "corridors_crossed": ["malacca"],
                "base_days": round(2800 / 350 + 0.5, 1),
                "base_distance_nm": 2_800,
                "transit_toll_usd": 10_000,
                "waypoints": [op, WAYPOINTS["malacca_north"], WAYPOINTS["east_indian"], dp],
            }
        ]

    if PORTS[dest_id]["region"] in ("Persian Gulf", "Red Sea"):
        return [
            {
                "id": f"sgp_{dest_id[:3]}_malacca",
                "name": "Malacca → Indian Ocean → Gulf of Oman",
                "corridors_crossed": ["malacca", "hormuz"],
                "base_days": round(4200 / 350 + 1.0, 1),
                "base_distance_nm": 4_200,
                "transit_toll_usd": 10_000,
                "waypoints": [
                    op,
                    WAYPOINTS["malacca_north"],
                    WAYPOINTS["east_indian"],
                    WAYPOINTS["gulf_of_aden"],
                    WAYPOINTS["hormuz"],
                    dp,
                ],
            }
        ]

    # Europe / US via Suez
    return [
        {
            "id": f"sgp_{dest_id[:3]}_suez",
            "name": "Malacca → Indian Ocean → Suez Canal",
            "corridors_crossed": ["malacca", "red_sea", "suez"],
            "base_days": round(8200 / 350 + 2.0, 1),
            "base_distance_nm": 8_200,
            "transit_toll_usd": 390_000,
            "waypoints": [
                op,
                WAYPOINTS["malacca_north"],
                WAYPOINTS["gulf_of_aden"],
                WAYPOINTS["bab_el_mandeb"],
                WAYPOINTS["suez_canal"],
                WAYPOINTS["mediterranean_mid"],
                WAYPOINTS["gibraltar"],
                dp,
            ],
        },
    ]


def _get_routes(origin_id: str, dest_id: str) -> list[dict]:
    """
    Dynamic route builder — returns a list of candidate route dicts for any
    supported origin → destination combination.
    """
    if origin_id == dest_id:
        raise ValueError("Origin and destination must be different ports.")

    o_region = PORTS[origin_id]["region"]
    d_region = PORTS[dest_id]["region"]

    # Reverse lookup helper — build from dest perspective if needed
    if origin_id == "singapore" or dest_id == "singapore":
        # Normalise so Singapore is always origin
        if dest_id == "singapore":
            routes = _singapore_routes(dest_id, origin_id)
            # Reverse waypoints for each route
            for r in routes:
                r["waypoints"] = list(reversed(r["waypoints"]))
        else:
            routes = _singapore_routes(origin_id, dest_id)
        return routes

    if origin_id == "novorossiysk" or dest_id == "novorossiysk":
        if dest_id == "novorossiysk":
            routes = _black_sea_routes(dest_id, origin_id)
            for r in routes:
                r["waypoints"] = list(reversed(r["waypoints"]))
        else:
            routes = _black_sea_routes(origin_id, dest_id)
        return routes

    # Gulf → Indian
    if o_region in ("Persian Gulf", "Red Sea") and d_region == "Indian Ocean":
        return _gulf_to_indian_routes(origin_id, dest_id)

    # Indian → Gulf (reverse)
    if o_region == "Indian Ocean" and d_region in ("Persian Gulf", "Red Sea"):
        routes = _gulf_to_indian_routes(dest_id, origin_id)
        for r in routes:
            r["waypoints"] = list(reversed(r["waypoints"]))
        return routes

    # Gulf / Indian → Europe (Rotterdam)
    if o_region in ("Persian Gulf", "Red Sea", "Indian Ocean") and d_region == "North Sea":
        return _gulf_to_europe_routes(origin_id, dest_id)

    # Europe → Gulf / Indian (reverse)
    if o_region == "North Sea" and d_region in ("Persian Gulf", "Red Sea", "Indian Ocean"):
        routes = _gulf_to_europe_routes(dest_id, origin_id)
        for r in routes:
            r["waypoints"] = list(reversed(r["waypoints"]))
        return routes

    # Gulf / Indian → Houston
    if o_region in ("Persian Gulf", "Red Sea", "Indian Ocean") and d_region == "Gulf of Mexico":
        return _gulf_to_houston_routes(origin_id, dest_id)

    # Houston → Gulf / Indian (reverse)
    if o_region == "Gulf of Mexico" and d_region in ("Persian Gulf", "Red Sea", "Indian Ocean"):
        routes = _gulf_to_houston_routes(dest_id, origin_id)
        for r in routes:
            r["waypoints"] = list(reversed(r["waypoints"]))
        return routes

    # Houston ↔ Rotterdam
    if set([o_region, d_region]) == {"Gulf of Mexico", "North Sea"}:
        op = PORTS[origin_id]["coords"]
        dp = PORTS[dest_id]["coords"]
        return [
            {
                "id": f"hou_rot_direct",
                "name": "Direct Transatlantic Route",
                "corridors_crossed": [],
                "base_days": round(4500 / 350 + 1.0, 1),
                "base_distance_nm": 4_500,
                "transit_toll_usd": 0,
                "waypoints": [op, WAYPOINTS["mid_atlantic"], dp],
            },
            {
                "id": f"hou_rot_azores",
                "name": "Azores Refuelling Stop Route",
                "corridors_crossed": [],
                "base_days": round(4700 / 350 + 1.5, 1),
                "base_distance_nm": 4_700,
                "transit_toll_usd": 15_000,
                "waypoints": [op, [37.7, -25.5], dp],
            },
        ]

    # Gulf of Oman special (Fujairah)
    if o_region == "Gulf of Oman":
        # Treat as equivalent to Persian Gulf for routing
        modified_origin = {**PORTS[origin_id], "region": "Persian Gulf"}
        temp = dict(PORTS)
        temp[origin_id] = modified_origin
        old_ports = PORTS.copy()
        PORTS.update(temp)
        try:
            routes = _get_routes(origin_id, dest_id)
        finally:
            PORTS.update(old_ports)
        return routes

    # Fallback — generic direct route
    op = PORTS[origin_id]["coords"]
    dp = PORTS[dest_id]["coords"]
    dist = int(math.sqrt((op[0] - dp[0]) ** 2 + (op[1] - dp[1]) ** 2) * 60)
    return [
        {
            "id": f"{origin_id[:3]}_{dest_id[:3]}_direct",
            "name": "Direct Ocean Route",
            "corridors_crossed": [],
            "base_days": round(dist / 350 + 1.0, 1),
            "base_distance_nm": dist,
            "transit_toll_usd": 0,
            "waypoints": [op, dp],
        }
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Main Assessment Function
# ─────────────────────────────────────────────────────────────────────────────

def assess_routes(
    origin_id: str,
    dest_id: str,
    risk_scores: dict,   # e.g. {"hormuz": 0.35, "red_sea": 0.72}
    brent_price: float,
) -> dict:
    """
    Assess geopolitical risks and cost impacts for alternative paths.

    Returns:
        {
          "origin": {id, name, coords},
          "destination": {id, name, coords},
          "brent_crude_usd": float,
          "corridor_zones": list,          ← for map risk overlays
          "options": [
             {
               id, name, distance_nm, days, corridors_crossed,
               risk_score, fuel_cost_usd, toll_cost_usd,
               insurance_premium_usd, total_cost_usd,
               recommendation, waypoints, geopolitical_context
             }, ...
          ],
          "decision_rationale_markdown": str
        }
    """
    # Resolve aliases
    origin_id = resolve_port_id(origin_id) or origin_id
    dest_id   = resolve_port_id(dest_id)   or dest_id

    if origin_id not in PORTS:
        raise ValueError(
            f"Unknown origin '{origin_id}'. "
            f"Available: {', '.join(PORTS.keys())}"
        )
    if dest_id not in PORTS:
        raise ValueError(
            f"Unknown destination '{dest_id}'. "
            f"Available: {', '.join(PORTS.keys())}"
        )

    routes = _get_routes(origin_id, dest_id)
    if not routes:
        raise ValueError(f"No routing paths found between {origin_id} and {dest_id}.")

    assessed_options = []

    # VLCC cost model constants
    # - Fuel: 75 tons/day of HSFO. HSFO ≈ Brent × 6.8 USD/ton
    # - Ops:  $45,000/day (charter, crew, lube)
    # - Cargo: 1 million barrels ≈ $80M base value (for insurance calculation)
    cargo_value_usd    = 80_000_000
    daily_ops_cost     = 45_000
    fuel_daily_tons    = 75
    ton_fuel_cost      = brent_price * 6.8

    for r in routes:
        # ── Geopolitical risk ───────────────────────────────────────────
        max_corridor_risk = 0.0
        risk_detail: dict[str, float] = {}
        for corridor in r["corridors_crossed"]:
            score = risk_scores.get(corridor, 0.25)   # default 0.25 if no live data
            risk_detail[corridor] = round(score, 3)
            max_corridor_risk = max(max_corridor_risk, score)

        # ── Financial model ─────────────────────────────────────────────
        fuel_total  = fuel_daily_tons * ton_fuel_cost * r["base_days"]
        ops_total   = daily_ops_cost  * r["base_days"]
        toll_cost   = r["transit_toll_usd"]

        # War-risk insurance: exponential scaling on corridor risk
        base_insurance     = cargo_value_usd * 0.0005          # 0.05% standard
        war_risk_insurance = 0.0
        if max_corridor_risk > 0.1:
            war_risk_insurance = (
                cargo_value_usd * 0.0015 * math.exp(3.5 * max_corridor_risk - 1)
            )
        total_insurance = base_insurance + war_risk_insurance
        total_cost      = fuel_total + ops_total + toll_cost + total_insurance

        # ── Geopolitical context summary for this route ─────────────────
        geo_ctx_parts = []
        for corridor in r["corridors_crossed"]:
            situation = CORRIDOR_SITUATIONS.get(corridor, "No specific advisory at this time.")
            geo_ctx_parts.append(f"**{CORRIDOR_ZONES.get(corridor, {}).get('label', corridor)}**: {situation}")
        geopolitical_context = "\n\n".join(geo_ctx_parts) if geo_ctx_parts else (
            "This route does not cross any high-risk chokepoints. Standard maritime conditions apply."
        )

        assessed_options.append({
            "id":                    r["id"],
            "name":                  r["name"],
            "distance_nm":           r["base_distance_nm"],
            "days":                  round(r["base_days"], 1),
            "corridors_crossed":     r["corridors_crossed"],
            "risk_score":            round(max_corridor_risk, 3),
            "risk_detail":           risk_detail,
            "fuel_cost_usd":         round(fuel_total, 0),
            "toll_cost_usd":         round(toll_cost, 0),
            "insurance_premium_usd": round(total_insurance, 0),
            "ops_cost_usd":          round(ops_total, 0),
            "total_cost_usd":        round(total_cost, 0),
            "waypoints":             r["waypoints"],
            "geopolitical_context":  geopolitical_context,
        })

    # ── Sort + label recommendations ────────────────────────────────────────
    high_risk_present = any(o["risk_score"] > 0.65 for o in assessed_options)

    if len(assessed_options) > 1:
        if high_risk_present:
            assessed_options.sort(key=lambda o: (o["risk_score"], o["total_cost_usd"]))
        else:
            assessed_options.sort(key=lambda o: (o["total_cost_usd"], o["risk_score"]))

    for i, opt in enumerate(assessed_options):
        if i == 0:
            opt["recommendation"] = "highly_recommended"
        elif opt["risk_score"] > 0.65:
            opt["recommendation"] = "not_recommended"
        else:
            opt["recommendation"] = "conditional"

    # ── Generate Gemini decision narrative ──────────────────────────────────
    rationale = _generate_rationale(
        PORTS[origin_id]["name"],
        PORTS[dest_id]["name"],
        brent_price,
        risk_scores,
        assessed_options,
    )

    # ── Build corridor zones list for map overlays ───────────────────────────
    active_corridors = set()
    for opt in assessed_options:
        active_corridors.update(opt["corridors_crossed"])

    corridor_zones = []
    for cid, zone in CORRIDOR_ZONES.items():
        corridor_zones.append({
            "id":        cid,
            "label":     zone["label"],
            "coords":    zone["coords"],
            "radius_km": zone["radius_km"],
            "risk":      risk_scores.get(cid, 0.25),
            "situation": CORRIDOR_SITUATIONS.get(cid, ""),
        })

    return {
        "origin": {
            "id":     origin_id,
            "name":   PORTS[origin_id]["name"],
            "coords": PORTS[origin_id]["coords"],
            "region": PORTS[origin_id]["region"],
        },
        "destination": {
            "id":     dest_id,
            "name":   PORTS[dest_id]["name"],
            "coords": PORTS[dest_id]["coords"],
            "region": PORTS[dest_id]["region"],
        },
        "brent_crude_usd":           brent_price,
        "corridor_zones":            corridor_zones,
        "options":                   assessed_options,
        "decision_rationale_markdown": rationale,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Narrative Generator
# ─────────────────────────────────────────────────────────────────────────────

def _generate_rationale(
    origin: str,
    destination: str,
    brent: float,
    risk_scores: dict,
    options: list[dict],
) -> str:
    """Uses Gemini to explain the geopolitical trade-offs between routes."""
    if _gemini_client is None:
        return _fallback_rationale(origin, destination, brent, options)

    summary_details = []
    for o in options:
        rec_str = {
            "highly_recommended": "✅ HIGHLY RECOMMENDED",
            "conditional":        "⚠️ CONDITIONAL",
            "not_recommended":    "❌ NOT RECOMMENDED",
        }.get(o["recommendation"], o["recommendation"])

        corridor_risks = ", ".join(
            f"{c}: {v:.2f}" for c, v in o["risk_detail"].items()
        ) or "No high-risk corridors"

        summary_details.append(
            f"- **Route**: {o['name']}\n"
            f"  Distance: {o['distance_nm']:,} NM | Transit: {o['days']} days\n"
            f"  Corridor Risk Scores: {corridor_risks}\n"
            f"  Composite Risk: {o['risk_score']:.3f}/1.0\n"
            f"  Fuel: ${o['fuel_cost_usd']:,.0f} | Ops: ${o['ops_cost_usd']:,.0f} "
            f"| Tolls: ${o['toll_cost_usd']:,.0f} | Insurance: ${o['insurance_premium_usd']:,.0f}\n"
            f"  **Total Cost: ${o['total_cost_usd']:,.0f}**\n"
            f"  Status: {rec_str}\n"
        )

    risk_ctx = "\n".join(
        f"- {k}: {v:.3f}/1.0" for k, v in risk_scores.items()
    )

    prompt = (
        f"You are a senior maritime operations and geopolitical energy security analyst "
        f"advising an executive committee on crude oil cargo routing.\n\n"
        f"**Voyage**: 1,000,000 barrels of crude oil from **{origin}** to **{destination}**.\n"
        f"**Current Brent Crude Spot Price**: ${brent:.2f}/bbl\n\n"
        f"**Live Geopolitical Risk Scores (0–1.0 scale)**:\n{risk_ctx}\n\n"
        f"**Candidate Routes**:\n{''.join(summary_details)}\n\n"
        f"Write a professional executive decision walkthrough in clean markdown. Include:\n"
        f"1. **Executive Summary** (2-3 sentences, state the recommendation and primary reason)\n"
        f"2. **Geopolitical Risk Assessment** (explain the specific threats in each risk corridor "
        f"— Houthi attacks in Red Sea, IRGC seizures in Hormuz, sanctions exposure, etc.)\n"
        f"3. **Financial Analysis** (compare routes on fuel, insurance escalation due to war-risk, "
        f"toll costs; use specific dollar figures from the data above)\n"
        f"4. **Decision Rationale** (explain trade-off logic: why paying extra is/isn't justified, "
        f"what the risk-adjusted cost per barrel is)\n"
        f"5. **Key Risks & Monitoring Triggers** (what would change this recommendation)\n\n"
        f"Use professional language. Be specific and reference the actual numbers."
    )

    try:
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        logger.warning("[RoutingAdvisor] Gemini rationalisation failed: %s", exc)
        return _fallback_rationale(origin, destination, brent, options)


def _fallback_rationale(
    origin: str,
    destination: str,
    brent: float,
    options: list[dict],
) -> str:
    """Markdown fallback report when Gemini is unavailable."""
    rec = next((o for o in options if o["recommendation"] == "highly_recommended"), options[0])
    others = [o for o in options if o["recommendation"] != "highly_recommended"]

    alt_section = ""
    for alt in others:
        rec_label = "Conditional" if alt["recommendation"] == "conditional" else "Not Recommended"
        cost_diff = alt["total_cost_usd"] - rec["total_cost_usd"]
        diff_str = f"+${abs(cost_diff):,.0f} more" if cost_diff > 0 else f"${abs(cost_diff):,.0f} cheaper"
        alt_section += (
            f"### Alternative: {alt['name']} ({rec_label})\n"
            f"- Total cost: **${alt['total_cost_usd']:,.0f}** ({diff_str})\n"
            f"- Risk score: **{alt['risk_score']:.3f}** | Transit: {alt['days']} days\n"
            f"- Corridors: {', '.join(alt['corridors_crossed']) or 'none'}\n\n"
        )

    risk_per_bbl = rec["total_cost_usd"] / 1_000_000

    return (
        f"## Executive Summary\n\n"
        f"Based on current geopolitical conditions and Brent crude at **${brent:.2f}/bbl**, "
        f"we recommend routing via **{rec['name']}**. "
        f"This option delivers the optimal balance of transit risk and total voyage cost.\n\n"
        f"## Financial Analysis\n\n"
        f"| Cost Component | Amount |\n"
        f"|---|---|\n"
        f"| Fuel (VLCC HSFO) | ${rec['fuel_cost_usd']:,.0f} |\n"
        f"| Operational (crew, charter) | ${rec['ops_cost_usd']:,.0f} |\n"
        f"| Transit Tolls | ${rec['toll_cost_usd']:,.0f} |\n"
        f"| War-Risk Insurance | ${rec['insurance_premium_usd']:,.0f} |\n"
        f"| **Total Voyage Cost** | **${rec['total_cost_usd']:,.0f}** |\n"
        f"| Cost per barrel | ${risk_per_bbl:.2f}/bbl |\n\n"
        f"## Decision Rationale\n\n"
        f"- **Distance**: {rec['distance_nm']:,} NM · **Transit**: {rec['days']} days\n"
        f"- **Geopolitical Risk Score**: {rec['risk_score']:.3f}/1.0 "
        f"({'Low' if rec['risk_score'] < 0.4 else 'Medium' if rec['risk_score'] < 0.7 else 'High'} risk)\n"
        f"- Corridors transited: {', '.join(rec['corridors_crossed']) or 'No high-risk chokepoints'}\n\n"
        f"{alt_section}"
        f"---\n"
        f"*LLM rationale offline — set `GEMINI_API_KEY` to enable AI-generated decision walkthrough.*"
    )
