"""Settings, read from .env once at start-up."""
import os

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

load_dotenv(override=True)

# DATABASE_URL is used when hosted online. Locally we use the .env values.
DB = os.getenv("DATABASE_URL") or make_conninfo(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME", "sabageo"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", ""),
)

MAX_PHOTO_BYTES = 10 * 1024 * 1024

# Coordinate types the website can send. Plots are always STORED as WGS84 (EPSG:4326).
# Minna is Nigeria's old survey datum; it is converted to WGS84 with the standard Nigeria shift
# (good to a few metres). 926333 = Minna / UTM 33N, added by phase_h.sql (PostGIS lacks it).
CRS_CHOICES = {
    "wgs84": 4326, "utm31": 32631, "utm32": 32632, "utm33": 32633,
    "minna": 4263, "minna_utm31": 26331, "minna_utm32": 26332, "minna_utm33": 926333,
    "minna_west": 26391, "minna_mid": 26392, "minna_east": 26393,
}
# types typed as latitude/longitude in degrees (all the others are easting/northing in metres)
GEOGRAPHIC = {"wgs84", "minna"}

# Rough box around Nigeria (west, south, east, north). Catches wrong-zone mistakes.
NIGERIA = (2.6, 4.2, 14.8, 13.95)

# Boundary tolerance. An "overlap" thinner than this along a shared boundary is rounding
# or survey noise, not encroachment (6-decimal lat/long is only exact to about 11 cm).
# Real overlaps wider than this are always flagged, whatever their area.
OVERLAP_TOLERANCE_M = float(os.getenv("OVERLAP_TOLERANCE_CM", "10")) / 100

# Token prices. These are the senior's working figures until the review committee approves real ones.
# Change them in .env (PRICE_INDIVIDUAL, PRICE_CORPORATE) without touching the code.
PLANS = {
    "individual": {
        "label": "Individual",
        "amount": float(os.getenv("PRICE_INDIVIDUAL", "15000")),
        "per": "per verification",
        "days": 30,      # the login code works for 30 days
        "plots": 1,      # one plot per payment
    },
    "corporate": {
        "label": "Corporate real estate retainer",
        "amount": float(os.getenv("PRICE_CORPORATE", "200000")),
        "per": "per month",
        "days": 30,
        "plots": None,   # no plot limit during the month
    },
}

# The site's public address, e.g. https://sabageo.onrender.com (used in QR codes and payment
# return links). When empty, the address the request came in on is used.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# Polygon Amoy test network
RPC = os.getenv("POLYGON_RPC", "https://polygon-amoy.drpc.org")
CHAIN_ID = 80002
EXPLORER_TX = "https://amoy.polygonscan.com/tx/"
