"""Acces aux deux API : football-data.org (calendriers, resultats) et
the-odds-api.com (cotes Betclic France). Aucune dependance externe."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

FD_BASE = "https://api.football-data.org/v4"
ODDS_BASE = "https://api.the-odds-api.com/v4"

# Les 13 competitions du plan gratuit de football-data.org.
COMPETITIONS = {
    "FL1": {"nom": "Ligue 1", "type": "ligue", "odds": "soccer_france_ligue_one"},
    "PL": {"nom": "Premier League", "type": "ligue", "odds": "soccer_epl"},
    "PD": {"nom": "Liga", "type": "ligue", "odds": "soccer_spain_la_liga"},
    "SA": {"nom": "Serie A", "type": "ligue", "odds": "soccer_italy_serie_a"},
    "BL1": {"nom": "Bundesliga", "type": "ligue", "odds": "soccer_germany_bundesliga"},
    "DED": {"nom": "Eredivisie", "type": "ligue", "odds": "soccer_netherlands_eredivisie"},
    "PPL": {"nom": "Primeira Liga", "type": "ligue", "odds": "soccer_portugal_primeira_liga"},
    "ELC": {"nom": "Championship", "type": "ligue", "odds": "soccer_efl_champ"},
    "BSA": {"nom": "Brasileirao", "type": "ligue", "odds": "soccer_brazil_campeonato"},
    "CLI": {"nom": "Copa Libertadores", "type": "ligue", "odds": "soccer_conmebol_copa_libertadores"},
    "CL": {"nom": "Ligue des Champions", "type": "coupe", "odds": "soccer_uefa_champs_league"},
    "EC": {"nom": "Championnat d'Europe", "type": "coupe", "odds": "soccer_uefa_european_championship"},
    "WC": {"nom": "Coupe du Monde", "type": "coupe", "odds": "soccer_fifa_world_cup"},
}

LIGUES = [c for c, v in COMPETITIONS.items() if v["type"] == "ligue"]


class ApiError(Exception):
    pass


ENTETES = {}   # dernieres en-tetes de reponse (quota de the-odds-api)


def _get(url, headers=None, retries=3):
    last = None
    for essai in range(retries):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                ENTETES.clear()
                ENTETES.update({k.lower(): v for k, v in r.headers.items()})
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")[:300]
            last = ApiError("HTTP %s sur %s : %s" % (e.code, url.split("?")[0], corps))
            if e.code == 429:            # quota par minute
                time.sleep(20 + 20 * essai)
                continue
            if e.code in (403, 404):     # ressource hors plan gratuit : inutile d'insister
                raise last
            time.sleep(4 * (essai + 1))
        except Exception as e:           # reseau
            last = ApiError("%s sur %s" % (e, url.split("?")[0]))
            time.sleep(4 * (essai + 1))
    raise last


class FootballData:
    """Calendriers et resultats. Plan gratuit : 10 appels par minute."""

    def __init__(self, token, pause=7.0, log=print):
        self.headers = {"X-Auth-Token": token}
        self.pause = pause
        self.log = log
        self._t = 0.0

    def _wait(self):
        delta = time.time() - self._t
        if delta < self.pause:
            time.sleep(self.pause - delta)
        self._t = time.time()

    def matches(self, code, **params):
        self._wait()
        url = "%s/competitions/%s/matches" % (FD_BASE, code)
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
        try:
            data = _get(url, self.headers)
        except ApiError as e:
            self.log("  football-data %s indisponible : %s" % (code, e))
            return []
        return data.get("matches", [])

    @staticmethod
    def parse(m, code):
        """Aplatit une rencontre de l'API."""
        utc = m.get("utcDate") or ""
        score = (m.get("score") or {}).get("fullTime") or {}
        return {
            "id": m.get("id"),
            "code": code,
            "comp": COMPETITIONS[code]["nom"],
            "utc": utc,
            "date": utc[:10],
            "heure": utc[11:16],
            "statut": m.get("status"),
            "dom_api": (m.get("homeTeam") or {}).get("name"),
            "dom_court": (m.get("homeTeam") or {}).get("shortName"),
            "ext_api": (m.get("awayTeam") or {}).get("name"),
            "ext_court": (m.get("awayTeam") or {}).get("shortName"),
            "bd": score.get("home"),
            "be": score.get("away"),
        }


class OddsApi:
    """Cotes 1N2. Plan gratuit : 500 credits par mois, 1 credit par appel."""

    def __init__(self, key, log=print):
        self.key = key
        self.log = log
        self.restant = None

    def h2h(self, sport_key):
        if not self.key:
            return []
        url = "%s/sports/%s/odds/?%s" % (ODDS_BASE, sport_key, urllib.parse.urlencode({
            # une seule region : le quota gratuit se compte en marches x regions.
            "apiKey": self.key, "regions": "eu", "markets": "h2h",
            "oddsFormat": "decimal", "dateFormat": "iso"}))
        try:
            data = _get(url)
        except ApiError as e:
            self.log("  cotes %s indisponibles : %s" % (sport_key, e))
            return []
        self.restant = ENTETES.get("x-requests-remaining", self.restant)
        return data

    @staticmethod
    def extract(event, prefere="betclic_fr"):
        """Cotes 1N2 : Betclic si presente, sinon mediane des bookmakers europeens."""
        dom, ext = event.get("home_team"), event.get("away_team")
        releves = []
        for bk in event.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                prix = {}
                for out in mk.get("outcomes", []):
                    nom = out.get("name")
                    if nom == dom:
                        prix["1"] = out.get("price")
                    elif nom == ext:
                        prix["2"] = out.get("price")
                    elif nom == "Draw":
                        prix["N"] = out.get("price")
                if len(prix) == 3:
                    releves.append((bk.get("key"), prix))
        if not releves:
            return None
        for cle, prix in releves:
            if cle == prefere:
                return {"c1": prix["1"], "cN": prix["N"], "c2": prix["2"], "source": "Betclic"}
        med = {}
        for issue in ("1", "N", "2"):
            vals = sorted(p[issue] for _, p in releves)
            med[issue] = vals[len(vals) // 2]
        return {"c1": med["1"], "cN": med["N"], "c2": med["2"],
                "source": "mediane de %d bookmakers" % len(releves)}
