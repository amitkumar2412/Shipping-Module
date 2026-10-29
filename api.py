"""FastAPI REST interface for the shipping scraper database.

  uvicorn api:app --reload
"""
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from database import Store

app = FastAPI(title="Shipping Scraper API")

store = Store()


MAX_PAGE_SIZE = 10


@app.get("/mainshipdata")
def get_all_mainshipdata(
    limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Rows per page (max 10)"),
    offset: int = Query(0, ge=0, description="Row offset"),
):
    """Return all rows from mainshipdata with pagination (10 rows per page max)."""
    rows, total = store.get_all_mainshipdata(limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": rows,
    }


@app.get("/ship-inventory")
def get_ship_inventory(
    limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Rows per page (max 10)"),
    offset: int = Query(0, ge=0, description="Row offset"),
):
    """Return the slim ship-inventory projection (vessel name, voyage ports/ETA,
    current area, type/subtype, last updated) with pagination (10 rows per page max)."""
    rows, total = store.get_ship_inventory(limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": rows,
    }


@app.get("/ship-inventory/search")
def search_ship_inventory(
    q: str = Query(..., min_length=1, description="Vessel name or ship id fragment to search for"),
    limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Rows per page (max 10)"),
    offset: int = Query(0, ge=0, description="Row offset"),
):
    """Fuzzy-search the ship-inventory projection by vessel name or ship id.

    Typo-tolerant (pg_trgm similarity) and substring matching are combined,
    so "Evergren" or a partial id like "4521" both return hits. Results are
    ranked best match first.
    """
    rows, total = store.search_ship_inventory(q, limit=limit, offset=offset)
    return {
        "query": q,
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": rows,
    }
