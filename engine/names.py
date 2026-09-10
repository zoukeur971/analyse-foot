"""Normalisation des noms d'equipes entre les API et la base du classeur."""
import json
import os
import re
import unicodedata
import difflib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIAS_FILE = os.path.join(HERE, "data", "aliases.json")

# Mots de club a retirer avant comparaison.
NOISE = {
    "fc", "cf", "afc", "ac", "sc", "ss", "ssc", "as", "us", "usa", "rc", "rcd", "cd",
    "ud", "sd", "sv", "bv", "vfl", "vfb", "tsg", "tsv", "bsc", "fsv", "spvgg", "borussia",
    "club", "calcio", "de", "do", "da", "the", "1899", "1900", "1904", "1907", "1909",
    "cp", "sad", "sk", "ogc", "osc", "losc", "asse", "hsc", "nk", "cska", "ec", "se",
}

# Alias manuels : nom API -> nom de la base du classeur.
MANUAL = {
    "paris saint germain": "Paris Saint-Germain",
    "psg": "Paris Saint-Germain",
    "rc lens": "Lens",
    "losc lille": "Lille",
    "olympique lyonnais": "Lyon",
    "olympique de marseille": "Marseille",
    "as monaco": "Monaco",
    "ogc nice": "Nice",
    "stade rennais": "Rennes",
    "rennes": "Rennes",
    "stade brestois": "Brest",
    "stade de reims": "Reims",
    "fc nantes": "Nantes",
    "montpellier hsc": "Montpellier",
    "toulouse fc": "Toulouse",
    "rc strasbourg alsace": "Strasbourg",
    "aj auxerre": "Auxerre",
    "angers sco": "Angers",
    "le havre ac": "Le Havre",
    "fc lorient": "Lorient",
    "fc metz": "Metz",
    "paris fc": "Paris FC",
    "as saint etienne": "Saint-Etienne",
    "manchester united": "Manchester United",
    "manchester city": "Manchester City",
    "tottenham hotspur": "Tottenham",
    "wolverhampton wanderers": "Wolverhampton",
    "brighton hove albion": "Brighton",
    "newcastle united": "Newcastle",
    "west ham united": "West Ham",
    "nottingham forest": "Nottingham Forest",
    "leicester city": "Leicester",
    "ipswich town": "Ipswich",
    "hull city": "Hull City",
    "leeds united": "Leeds",
    "sheffield united": "Sheffield United",
    "sheffield wednesday": "Sheffield Wednesday",
    "queens park rangers": "QPR",
    "west bromwich albion": "West Bromwich",
    "athletic bilbao": "Athletic Bilbao",
    "athletic club": "Athletic Bilbao",
    "atletico madrid": "Atletico Madrid",
    "club atletico de madrid": "Atletico Madrid",
    "real madrid": "Real Madrid",
    "barcelona": "Barcelone",
    "barcelone": "Barcelone",
    "sevilla": "Seville",
    "seville": "Seville",
    "real betis balompie": "Real Betis",
    "betis": "Real Betis",
    "real sociedad": "Real Sociedad",
    "villarreal": "Villarreal",
    "valencia": "Valence",
    "valence": "Valence",
    "celta vigo": "Celta Vigo",
    "rc celta": "Celta Vigo",
    "rayo vallecano": "Rayo Vallecano",
    "deportivo alaves": "Alaves",
    "alaves": "Alaves",
    "girona": "Gerone",
    "gerone": "Gerone",
    "espanyol": "Espanyol",
    "getafe": "Getafe",
    "osasuna": "Osasuna",
    "mallorca": "Majorque",
    "majorque": "Majorque",
    "real oviedo": "Oviedo",
    "levante": "Levante",
    "elche": "Elche",
    "real valladolid": "Valladolid",
    "deportivo la coruna": "Deportivo La Corogne",
    "racing santander": "Racing Santander",
    "malaga": "Malaga",
    "internazionale": "Inter",
    "inter milan": "Inter",
    "milan": "Milan",
    "ac milan": "Milan",
    "juventus": "Juventus",
    "napoli": "Naples",
    "naples": "Naples",
    "roma": "Roma",
    "lazio": "Lazio",
    "atalanta": "Atalanta",
    "fiorentina": "Fiorentina",
    "bologna": "Bologne",
    "bologne": "Bologne",
    "torino": "Torino",
    "udinese": "Udinese",
    "genoa": "Genoa",
    "cagliari": "Cagliari",
    "lecce": "Lecce",
    "empoli": "Empoli",
    "hellas verona": "Verone",
    "verona": "Verone",
    "verone": "Verone",
    "venezia": "Venise",
    "venise": "Venise",
    "como": "Como",
    "come": "Como",
    "parma": "Parme",
    "parme": "Parme",
    "monza": "Monza",
    "sassuolo": "Sassuolo",
    "pisa": "Pise",
    "cremonese": "Cremonese",
    "bayern munchen": "Bayern Munich",
    "bayern munich": "Bayern Munich",
    "bayer 04 leverkusen": "Leverkusen",
    "bayer leverkusen": "Leverkusen",
    "borussia dortmund": "Borussia Dortmund",
    "borussia monchengladbach": "Monchengladbach",
    "monchengladbach": "Monchengladbach",
    "eintracht frankfurt": "Eintracht Francfort",
    "eintracht francfort": "Eintracht Francfort",
    "rb leipzig": "RB Leipzig",
    "vfb stuttgart": "Stuttgart",
    "sc freiburg": "Fribourg",
    "fribourg": "Fribourg",
    "tsg 1899 hoffenheim": "Hoffenheim",
    "werder bremen": "Werder Breme",
    "werder breme": "Werder Breme",
    "fc augsburg": "Augsbourg",
    "augsbourg": "Augsbourg",
    "1 fc union berlin": "Union Berlin",
    "union berlin": "Union Berlin",
    "1 fsv mainz 05": "Mayence",
    "mainz": "Mayence",
    "mayence": "Mayence",
    "1 fc koln": "Cologne",
    "cologne": "Cologne",
    "vfl wolfsburg": "Wolfsburg",
    "fc st pauli": "St Pauli",
    "holstein kiel": "Holstein Kiel",
    "fc schalke 04": "Schalke 04",
    "schalke": "Schalke 04",
    "hamburger sv": "Hambourg",
    "hambourg": "Hambourg",
    "sc paderborn 07": "Paderborn",
    "heidenheim": "Heidenheim",
    "bochum": "Bochum",
}


def _slugifier_table(d):
    """Les cles de MANUAL sont ecrites en clair : on les passe par slug()."""
    return {slug(k): v for k, v in d.items()}


def slug(name):
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " ").replace("-", " ").replace(".", " ").replace("'", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t and t not in NOISE]
    if not toks:
        toks = s.split()
    return " ".join(toks)


class Resolver:
    """Fait correspondre un nom d'API a un nom de la base, et retient ce qu'il apprend."""

    def __init__(self, base_names):
        self.base = {slug(n): n for n in base_names}
        self.learned = {}
        if os.path.exists(ALIAS_FILE):
            try:
                self.learned = json.load(open(ALIAS_FILE, encoding="utf-8"))
            except ValueError:
                self.learned = {}
        self.unmatched = set()

    def resolve(self, api_name, short_name=None):
        """Renvoie (nom_affiche, nom_base_ou_None)."""
        for cand in (api_name, short_name):
            if not cand:
                continue
            s = slug(cand)
            if s in self.learned:
                return self.learned[s], self.learned[s]
            if s in MANUAL and slug(MANUAL[s]) in self.base:
                return MANUAL[s], MANUAL[s]
            if s in self.base:
                return self.base[s], self.base[s]
        # « FC Internazionale Milano » contient « inter » : on accepte le nom de base
        # dont tous les mots figurent dans le nom de l'API, a condition qu'il soit unique.
        for cand in (short_name, api_name):
            if not cand:
                continue
            mots = slug(cand).split()
            toks = set(mots)
            inclus = sorted({b for b in list(self.base) + list(MANUAL)
                             if b and set(b.split()) <= toks})
            if inclus:
                # le plus de mots en commun d'abord ; a egalite, celui qui apparait
                # le plus tot dans le nom (« Espanyol » avant « Barcelona »)
                def rang(b):
                    return (-len(b.split()), min(mots.index(m) for m in b.split()))
                inclus.sort(key=rang)
                gagnant = inclus[0]
                # « Charlton Athletic » ne doit pas devenir « Athletic Bilbao » : un nom
                # de base d'un seul mot n'est accepte que s'il ouvre le nom de l'API.
                if len(gagnant.split()) == 1 and len(mots) > 1 and mots.index(gagnant) != 0:
                    continue
                if len(inclus) == 1 or rang(inclus[0]) < rang(inclus[1]):
                    trouve = MANUAL.get(gagnant) or self.base.get(gagnant)
                    if trouve and slug(trouve) in self.base:
                        self.learned[slug(cand)] = trouve
                        return trouve, trouve
        for cand in (short_name, api_name):
            if not cand:
                continue
            s = slug(cand)
            close = difflib.get_close_matches(s, list(self.base), n=1, cutoff=0.88)
            if close:
                found = self.base[close[0]]
                self.learned[s] = found
                return found, found
        display = short_name or api_name
        self.unmatched.add(display)
        return display, None

    def save(self):
        os.makedirs(os.path.dirname(ALIAS_FILE), exist_ok=True)
        json.dump(self.learned, open(ALIAS_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)


MANUAL = _slugifier_table(MANUAL)
