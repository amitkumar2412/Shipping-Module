"""Fetches vessel data from MarineTraffic's JSON endpoints (the same ones the vessel page calls)."""
import random
import time

from curl_cffi import requests

BASE = "https://www.marinetraffic.com"
VESSEL_ENDPOINTS = ("general", "summary", "position", "voyage")


class ScrapeError(Exception):
    pass


class MarineTrafficClient:
    def __init__(self, retries=3, backoff=5.0):
        self.retries = retries
        self.backoff = backoff
        self._port_cache = {}
        self._new_session()

    def _new_session(self):
        # Chrome TLS fingerprint impersonation is what gets us past Cloudflare.
        self.session = requests.Session(impersonate="chrome")
        self._warmed = set()

    def _warm_up(self, ship_id):
        """Load the HTML page once so the session carries Cloudflare cookies, like a real visit."""
        if ship_id in self._warmed:
            return
        self.session.get(self._page_url(ship_id), timeout=30)
        self._warmed.add(ship_id)

    @staticmethod
    def _page_url(ship_id):
        return f"{BASE}/en/ais/details/ships/shipid:{ship_id}"

    def _get_json(self, path, ship_id):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self._page_url(ship_id),
        }
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                self._warm_up(ship_id)
                r = self.session.get(BASE + path, headers=headers, timeout=30)
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    return r.json()
                if r.status_code == 404:
                    raise ScrapeError(f"{path}: 404 not found (wrong ship id?)")
                last = f"HTTP {r.status_code}"
                if r.status_code in (403, 429, 503):
                    self._new_session()  # blocked or rate limited: start fresh
            except ScrapeError:
                raise
            except Exception as e:  # network errors
                last = repr(e)
            time.sleep(self.backoff * attempt + random.uniform(0, 2))
        raise ScrapeError(f"{path}: failed after {self.retries} attempts ({last})")

    def get_port(self, port_id, ship_id):
        if port_id is None:
            return None
        if port_id not in self._port_cache:
            self._port_cache[port_id] = self._get_json(f"/en/ports/{port_id}/general", ship_id)
        return self._port_cache[port_id]

    def fetch_vessel(self, ship_id):
        """Returns {'general':..., 'summary':..., 'position':..., 'voyage':..., 'ports': {...}}."""
        data = {}
        for ep in VESSEL_ENDPOINTS:
            data[ep] = self._get_json(f"/en/vessels/{ship_id}/{ep}", ship_id)
            time.sleep(random.uniform(0.5, 1.5))
        voyage = data["voyage"] or {}
        ports = {}
        for key in ("departurePortId", "arrivalPortId", "previousDeparturePortId"):
            pid = voyage.get(key)
            if pid is not None:
                try:
                    ports[pid] = self.get_port(pid, ship_id)
                except ScrapeError:
                    ports[pid] = None
        data["ports"] = ports
        return data
