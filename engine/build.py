# -*- coding: utf-8 -*-
"""Chaine complete de mise a jour, en remplacement du classeur.

1. relever les resultats des rencontres jouees et les archiver avec la prediction
   figee au moment ou elle a ete faite
2. recalculer les forces d'attaque et de defense de chaque equipe
3. recalculer la calibration et, si elle est activee, ajuster les parametres
4. recuperer les rencontres des sept prochains jours et leurs cotes
5. ecrire docs/data.json, que le site lit au chargement
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import model
from engine.calibrate import bilan, balayage_poids_marche, issue
from engine.names import Resolver
from engine.sources import COMPETITIONS, LIGUES, FootballData, OddsApi

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RACINE, "data")
DOCS = os.path.join(RACINE, "docs")
FENETRE = 7          # jours de rencontres a venir
RETOUR = 21          # jours de recul pour ramasser les resultats
K_LISSAGE = 6.0      # matchs fictifs a la moyenne de la ligue pour une equipe sans base


def lire(nom, defaut):
    p = os.path.join(DATA, nom)
    if not os.path.exists(p):
        return defaut
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def ecrire(nom, obj):
    with open(os.path.join(DATA, nom), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def log(*a):
    print(*a, flush=True)


def saison_courante(code):
    """Annee de depart de la saison en cours, au format attendu par football-data."""
    auj = dt.date.today()
    return auj.year if auj.month >= 7 or code == "BSA" else auj.year - 1


def base_saison_precedente(fd, res, base, cache):
    """Construit une base statistique pour les championnats qui n'en ont pas.

    Les cinq grands championnats sont fournis avec le depot (saison 2025-26 saisie a
    la main). Pour les autres, la saison precedente de l'API fait l'affaire : sans
    elle, une equipe d'Eredivisie partirait a la force moyenne de sa ligue.
    """
    besoin = []
    for code in LIGUES:
        nom = COMPETITIONS[code]["nom"]
        connues = sum(1 for v in base.values() if v.get("league") == nom and (v.get("mp") or 0) > 0)
        if connues < 8:
            besoin.append(code)
    if not besoin:
        return cache
    saison = saison_courante("PL") - 1
    faits = dict(cache.get("_faits") or {})
    besoin = [c for c in besoin if faits.get(c) != saison]
    if not besoin:
        return cache
    neuf = {k: v for k, v in cache.items() if k not in ("_saison", "_faits")}
    for code in besoin:
        ms = fd.matches(code, season=saison, status="FINISHED")
        log("  base %s saison %s : %d rencontres" % (code, saison, len(ms)))
        faits[code] = saison          # meme vide : on ne redemande pas chaque jour
        stats = {}
        for m in ms:
            p = FootballData.parse(m, code)
            if p["bd"] is None:
                continue
            d, _ = res.resolve(p["dom_api"], p["dom_court"])
            e, _ = res.resolve(p["ext_api"], p["ext_court"])
            for nom, pour, contre in ((d, p["bd"], p["be"]), (e, p["be"], p["bd"])):
                t = stats.setdefault(nom, {"league": COMPETITIONS[code]["nom"], "mp": 0,
                                           "gf": 0, "ga": 0, "adj_att": 1, "adj_def": 1})
                t["mp"] += 1; t["gf"] += pour; t["ga"] += contre
        neuf.update(stats)
    neuf["_saison"] = saison
    neuf["_faits"] = faits
    return neuf


# ----------------------------------------------------------------- forces
def forces(base, forme, params):
    """Equipes!K, L, M : moyenne de ligue, force d'attaque, force de defense."""
    equipes = {}
    noms = set(base) | set(forme)
    for n in noms:
        b = base.get(n, {})
        f = forme.get(n, {})
        equipes[n] = {
            "ligue": b.get("league") or f.get("ligue"),
            "base_mp": b.get("mp") or 0, "base_gf": b.get("gf") or 0, "base_ga": b.get("ga") or 0,
            "adj_att": b.get("adj_att", 1) or 1, "adj_def": b.get("adj_def", 1) or 1,
            "mp": f.get("mp", 0), "gf": f.get("gf", 0), "ga": f.get("ga", 0),
        }
    moy = {}
    for lig in {e["ligue"] for e in equipes.values() if e["ligue"]}:
        gr = [e for e in equipes.values() if e["ligue"] == lig]
        bmp, bgf = sum(e["base_mp"] for e in gr), sum(e["base_gf"] for e in gr)
        if bmp >= 100:                     # base de saison complete disponible
            moy[lig] = bgf / bmp
        else:
            mp, gf = sum(e["mp"] for e in gr), sum(e["gf"] for e in gr)
            moy[lig] = gf / mp if mp >= 20 else 1.40
    w_max = params["poids_forme"]
    for n, e in equipes.items():
        lg = moy.get(e["ligue"], 1.40)
        w = w_max * min(e["mp"] / 6.0, 1.0) if e["mp"] else 0.0
        if e["base_mp"]:
            att = (e["base_gf"] / e["base_mp"]) * (1 - w) + (w * e["gf"] / e["mp"] if e["mp"] else 0)
            dfn = (e["base_ga"] / e["base_mp"]) * (1 - w) + (w * e["ga"] / e["mp"] if e["mp"] else 0)
        else:                              # equipe sans base : lissage vers la moyenne
            att = (e["gf"] + K_LISSAGE * lg) / (e["mp"] + K_LISSAGE)
            dfn = (e["ga"] + K_LISSAGE * lg) / (e["mp"] + K_LISSAGE)
        e["att"] = att / lg * e["adj_att"]
        e["def"] = dfn / lg * e["adj_def"]
        e["moy_ligue"] = lg
    return equipes, moy


def borne(suggere, actuel, pas_max, mini, maxi):
    """Limite un reglage : au plus pas_max de variation par passage, et jamais hors bornes."""
    if suggere is None:
        return actuel
    delta = max(-pas_max, min(pas_max, suggere - actuel))
    return max(mini, min(maxi, actuel + delta))


def stats_h2h(h2h, dom, ext):
    n = v1 = nul = v2 = 0
    for r in h2h:
        if r["dom"] == dom and r["ext"] == ext:
            n += 1
            v1 += r["bd"] > r["be"]; nul += r["bd"] == r["be"]; v2 += r["bd"] < r["be"]
        elif r["dom"] == ext and r["ext"] == dom:
            n += 1
            v1 += r["be"] > r["bd"]; nul += r["bd"] == r["be"]; v2 += r["be"] < r["bd"]
    return {"n": n, "v1": v1, "nul": nul, "v2": v2}


# ----------------------------------------------------------------- rencontre
def calcul(m, equipes, moy, h2h, params, cotes):
    dom, ext = m["dom"], m["ext"]
    ed, ee = equipes.get(dom), equipes.get(ext)
    if not ed or not ee:
        return None
    lg = moy.get(ed["ligue"], 1.40)
    lh, la = model.lambdas(ed, ee, params, lg)
    mk_model = model.markets(lh, la, params["rho"])
    h = stats_h2h(h2h, dom, ext)
    q1, qn, q2 = model.blend_h2h(mk_model, h, params["poids_h2h"])
    c1, cN, c2 = (cotes or {}).get("c1"), (cotes or {}).get("cN"), (cotes or {}).get("c2")
    mkt = model.devig(c1, cN, c2)
    p1, pn, p2 = model.verdict_probs(q1, qn, q2, mkt, params["poids_marche"])
    inter = ed["ligue"] != ee["ligue"]
    pmax = max(p1, pn, p2)
    conf = "Inter-champ." if inter else ("Elevee" if pmax >= 0.55 else ("Moyenne" if pmax >= 0.45 else "Faible"))
    verdict = ("Victoire " + dom) if (p1 >= pn and p1 >= p2) else ("Match nul" if pn >= p2 else "Victoire " + ext)
    vb = model.value_bet(q1, qn, q2, c1, cN, c2, mkt, params, inter) or {}
    r = {
        "date": m["date"], "heure": m["heure"], "comp": m["comp"], "dom": dom, "ext": ext,
        "xd": lh, "xe": la,
        "p1": p1, "pn": pn, "p2": p2,
        "q1": q1, "qn": qn, "q2": q2,
        "verdict": verdict, "conf": conf, "score": mk_model["score"],
        "o25": mk_model["o25"], "o15": mk_model["o15"], "btts": mk_model["btts"],
        "c1": c1, "cN": cN, "c2": c2,
        "m1": (mkt or {}).get("m1"), "mn": (mkt or {}).get("mn"), "m2": (mkt or {}).get("m2"),
        "marge": (mkt or {}).get("marge"),
        "pari": vb.get("pari"), "edge": vb.get("edge"), "div": vb.get("div"),
        "vp": vb.get("vp") or "Pas de cote",
        "src": (cotes or {}).get("source"),
        "id": m.get("id"),
    }
    return r


# ----------------------------------------------------------------- pipeline
def principal():
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    cle_cotes = os.environ.get("ODDS_API_KEY", "").strip()
    if not token:
        raise SystemExit("Secret FOOTBALL_DATA_TOKEN absent : impossible de recuperer les matchs.")

    params = lire("params.json", {})
    base = lire("teams_base.json", {})
    base_auto = lire("teams_base_auto.json", {})
    for n, v in base_auto.items():
        if not n.startswith("_"):
            base.setdefault(n, v)
    journal = lire("results.json", [])
    h2h = lire("h2h.json", [])
    etat = lire("state.json", {"pending": {}, "vus": []})
    etat.setdefault("pending", {})
    etat.setdefault("vus", [])

    fd = FootballData(token, log=log)
    odds = OddsApi(cle_cotes, log=log)
    res = Resolver(list(base.keys()))

    aujourd = dt.date.today()
    depuis = (aujourd - dt.timedelta(days=RETOUR)).isoformat()
    jusqu = (aujourd + dt.timedelta(days=FENETRE)).isoformat()

    # --- 1. saison en cours : forme de chaque equipe + resultats recents
    forme, recents, a_venir = {}, [], []
    for code in COMPETITIONS:
        est_ligue = COMPETITIONS[code]["type"] == "ligue"
        brut = fd.matches(code, dateFrom=depuis, dateTo=jusqu)
        saison = fd.matches(code, status="FINISHED") if est_ligue else []
        log("%-4s %3d rencontres dans la fenetre, %3d jouees cette saison" % (code, len(brut), len(saison)))
        for m in saison:
            p = FootballData.parse(m, code)
            if p["bd"] is None:
                continue
            d, _ = res.resolve(p["dom_api"], p["dom_court"])
            e, _ = res.resolve(p["ext_api"], p["ext_court"])
            for nom, pour, contre in ((d, p["bd"], p["be"]), (e, p["be"], p["bd"])):
                f = forme.setdefault(nom, {"mp": 0, "gf": 0, "ga": 0, "ligue": COMPETITIONS[code]["nom"]})
                f["mp"] += 1; f["gf"] += pour; f["ga"] += contre
        for m in brut:
            p = FootballData.parse(m, code)
            p["dom"], _ = res.resolve(p["dom_api"], p["dom_court"])
            p["ext"], _ = res.resolve(p["ext_api"], p["ext_court"])
            if p["statut"] == "FINISHED" and p["bd"] is not None:
                recents.append(p)
            elif p["statut"] in ("SCHEDULED", "TIMED") and p["date"] >= aujourd.isoformat():
                a_venir.append(p)

    # base statistique des championnats absents du depot (Eredivisie, Championship...)
    base_auto = base_saison_precedente(fd, res, base, base_auto)
    ecrire("teams_base_auto.json", base_auto)
    for n, v in base_auto.items():
        if not n.startswith("_"):
            base.setdefault(n, v)

    # equipes qui n'ont encore joue aucun match : force neutre plutot que rencontre ignoree
    for p in a_venir:
        if COMPETITIONS[p["code"]]["type"] != "ligue":
            continue
        for nom in (p["dom"], p["ext"]):
            forme.setdefault(nom, {"mp": 0, "gf": 0, "ga": 0, "ligue": p["comp"]})

    # --- 2. archivage des rencontres jouees, avec la prediction figee
    nouvelles = 0
    for p in recents:
        cle = str(p["id"])
        if cle in etat["vus"]:
            continue
        etat["vus"].append(cle)
        h2h.append({"saison": etat.get("saison", ""), "comp": p["comp"], "dom": p["dom"],
                    "ext": p["ext"], "bd": p["bd"], "be": p["be"]})
        pred = etat["pending"].pop(cle, None)
        if not pred:
            continue                        # jamais annoncee : rien a calibrer
        journal.append({
            "date": p["date"], "comp": p["comp"], "dom": p["dom"], "ext": p["ext"],
            "bd": p["bd"], "be": p["be"],
            "xd": pred["xd"], "xe": pred["xe"],
            "p1": pred["p1"], "pn": pred["pn"], "p2": pred["p2"],
            "m1": pred.get("m1"), "mn": pred.get("mn"), "m2": pred.get("m2"),
            "pari": pred.get("pari"), "cote": pred.get("cote_jouee"), "vp": pred.get("vp"),
            "w": pred.get("w", params["poids_marche"]),
        })
        nouvelles += 1
    etat["vus"] = etat["vus"][-4000:]
    log("%d rencontres archivees dans le journal (%d au total)" % (nouvelles, len(journal)))

    # --- 3. calibration et reglages
    journal.sort(key=lambda r: (r["date"], r["dom"]))
    _, syn, rend, cal, champ = bilan(journal, params)
    # Le reglage ne bouge que lorsque de nouveaux resultats sont entres : applique a
    # chaque passage sur le meme journal, la formule de Resultats C16 se composerait
    # avec elle-meme et deriverait sans qu'aucune information nouvelle ne l'ait justifie.
    if params.get("auto_calibration") and nouvelles and syn["Matchs enregistres"] >= 20:
        avant = (params["correctif_buts"], params["avantage_terrain"])
        params["correctif_buts"] = round(borne(syn["Correctif de buts suggere"],
                                               params["correctif_buts"], 0.03, 0.80, 1.25), 4)
        params["avantage_terrain"] = round(borne(syn["Avantage du terrain suggere"],
                                                 params["avantage_terrain"], 0.03, 1.00, 1.25), 4)
        if avant != (params["correctif_buts"], params["avantage_terrain"]):
            params.setdefault("historique", []).append({
                "date": aujourd.isoformat(), "n": syn["Matchs enregistres"],
                "correctif_buts": params["correctif_buts"],
                "avantage_terrain": params["avantage_terrain"]})
            params["historique"] = params["historique"][-60:]
            log("Parametres ajustes : correctif de buts %.4f, avantage du terrain %.4f"
                % (params["correctif_buts"], params["avantage_terrain"]))
    sweep = balayage_poids_marche(journal)
    if sweep:
        log("Poids de marche optimal sur le journal : %.2f (log-loss %.4f, %d matchs)"
            % (sweep["poids"], sweep["logloss"], sweep["n"]))
        if params.get("auto_poids_marche") and sweep["n"] >= 150:
            cible = sweep["poids"]
            actuel = params["poids_marche"]
            params["poids_marche"] = round(actuel + max(-0.05, min(0.05, cible - actuel)), 3)

    # --- 4. forces des equipes, avec les resultats de la veille inclus
    equipes, moy = forces(base, forme, params)
    log("%d equipes, %d championnats" % (len(equipes), len(moy)))

    # --- 5. cotes des rencontres a venir
    par_comp = {}
    for p in a_venir:
        par_comp.setdefault(p["code"], []).append(p)
    cotes = {}
    for code, liste in par_comp.items():
        sport = COMPETITIONS[code]["odds"]
        if not sport or not cle_cotes:
            continue
        evs = odds.h2h(sport)
        for ev in evs:
            prix = OddsApi.extract(ev)
            if not prix:
                continue
            d, _ = res.resolve(ev.get("home_team"))
            e, _ = res.resolve(ev.get("away_team"))
            cotes[(d, e, (ev.get("commence_time") or "")[:10])] = prix
            cotes.setdefault((d, e), prix)
    if odds.restant is not None:
        log("Credits the-odds-api restants ce mois : %s" % odds.restant)
    log("%d rencontres a venir, cotes relevees pour %d d'entre elles"
        % (len(a_venir), sum(1 for p in a_venir
                             if (p["dom"], p["ext"], p["date"]) in cotes or (p["dom"], p["ext"]) in cotes)))

    # --- 6. calcul de chaque rencontre + memorisation de la prediction
    a_venir.sort(key=lambda p: (p["date"], p["heure"] or "", p["comp"]))
    upcoming, sel = [], []
    sans_equipe = set()
    for p in a_venir:
        c = cotes.get((p["dom"], p["ext"], p["date"])) or cotes.get((p["dom"], p["ext"]))
        r = calcul(p, equipes, moy, h2h, params, c)
        if not r:
            sans_equipe.add(p["dom"] if p["dom"] not in equipes else p["ext"])
            continue
        s = model.selection(r, params)
        r_public = {k: v for k, v in r.items() if k != "id"}
        upcoming.append(r_public)
        sel.append(dict(date=r["date"], heure=r["heure"], comp=r["comp"],
                        match=r["dom"] + " - " + r["ext"], **s))
        cote_jouee = {"1": r["c1"], "N": r["cN"], "2": r["c2"]}.get(r.get("pari"))
        etat["pending"][str(p["id"])] = {
            "xd": r["xd"], "xe": r["xe"], "p1": r["p1"], "pn": r["pn"], "p2": r["p2"],
            "m1": r["m1"], "mn": r["mn"], "m2": r["m2"], "pari": r.get("pari"),
            "cote_jouee": cote_jouee, "vp": r["vp"], "w": params["poids_marche"] if r["m1"] else 0,
        }
    if sans_equipe:
        log("Equipes inconnues, rencontres ignorees : " + ", ".join(sorted(sans_equipe)[:15]))

    retenues = [s for s in sel if s["verdict"] == "RETENU"]
    selsyn = {
        "retenues": len(retenues),
        "seuil_n": len([s for s in sel if s["verdict"] in ("RETENU", "Cote insuffisante")]),
        "taux": (sum(s["p"] for s in retenues) / len(retenues)) if retenues else None,
        "cote": (sum(s["cote"] for s in retenues) / len(retenues)) if retenues else None,
        "edge": (sum(s["edge"] for s in retenues) / len(retenues)) if retenues else None,
        "mise": sum(s["mise"] or 0 for s in retenues),
        "gain": sum((s["mise"] or 0) * s["edge"] for s in retenues),
    }

    journal_enrichi, syn, rend, cal, champ = bilan(journal, params)
    sortie = {
        "meta": {
            "maj": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
            "fenetre": FENETRE,
            "debut": aujourd.isoformat(),
            "fin": (aujourd + dt.timedelta(days=FENETRE)).isoformat(),
            "competitions": sorted({r["comp"] for r in upcoming}),
            "params": {k: v for k, v in params.items() if k != "historique"},
            "cotes": sum(1 for r in upcoming if r.get("c1")),
        },
        "upcoming": upcoming,
        "sel": sel,
        "selsyn": selsyn,
        "results": [{k: v for k, v in r.items() if k in (
            "date", "comp", "dom", "ext", "bd", "be", "res", "xd", "xe", "p1", "pn", "p2",
            "m1", "mn", "m2", "vm", "ok", "vmar", "okm", "pari", "cote", "vp", "rp", "profit")}
            for r in journal_enrichi],
        "syn": syn, "rend": rend, "cal": cal, "champ": champ,
    }
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, separators=(",", ":"))

    etat["maj"] = sortie["meta"]["maj"]
    etat["pending"] = {k: v for k, v in list(etat["pending"].items())[-800:]}
    ecrire("params.json", params)
    ecrire("results.json", journal)
    ecrire("h2h.json", h2h[-1200:])
    ecrire("state.json", etat)
    if forme:
        ecrire("forme.json", forme)
    res.save()
    log("docs/data.json ecrit : %d rencontres a venir, %d matchs joues, %d selections retenues"
        % (len(upcoming), len(journal), selsyn["retenues"]))
    return sortie


if __name__ == "__main__":
    principal()
