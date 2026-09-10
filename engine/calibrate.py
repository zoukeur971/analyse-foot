"""Boucle d'apprentissage : portage de l'onglet Resultats du classeur.

Synthese, rendement par verdict, calibration par tranche, performance par
championnat, et reglages suggeres (Resultats C16 et C17).
"""
import math

TRANCHES = [
    ("33 a 40 %", 0.00, 0.40),
    ("40 a 45 %", 0.40, 0.45),
    ("45 a 50 %", 0.45, 0.50),
    ("50 a 55 %", 0.50, 0.55),
    ("55 a 60 %", 0.55, 0.60),
    ("60 a 70 %", 0.60, 0.70),
    ("70 a 100 %", 0.70, 1.01),
]
VERDICTS = ["PARI VALUE", "Pas de valeur", "Ecart suspect"]


def issue(bd, be):
    return "1" if bd > be else ("N" if bd == be else "2")


def _fav(p1, pn, p2):
    return "1" if (p1 >= pn and p1 >= p2) else ("N" if pn >= p2 else "2")


def enrichir(r):
    """Ajoute a une ligne de journal tout ce que les colonnes G a AD calculaient."""
    r = dict(r)
    r["res"] = issue(r["bd"], r["be"])
    r["vm"] = _fav(r["p1"], r["pn"], r["p2"])
    r["ok"] = 1 if r["vm"] == r["res"] else 0
    pv = {"1": r["p1"], "N": r["pn"], "2": r["p2"]}[r["res"]]
    r["ll"] = -math.log(max(1e-4, pv))
    r["brier"] = sum((p - (1.0 if k == r["res"] else 0.0)) ** 2
                     for k, p in (("1", r["p1"]), ("N", r["pn"]), ("2", r["p2"])))
    if r.get("m1"):
        r["vmar"] = _fav(r["m1"], r["mn"], r["m2"])
        r["okm"] = 1 if r["vmar"] == r["res"] else 0
        mv = {"1": r["m1"], "N": r["mn"], "2": r["m2"]}[r["res"]]
        r["llm"] = -math.log(max(1e-4, mv))
    else:
        r["vmar"], r["okm"], r["llm"] = None, None, None
    if r.get("pari") and r.get("cote"):
        r["rp"] = "Gagne" if r["pari"] == r["res"] else "Perdu"
        r["profit"] = (r["cote"] - 1) if r["rp"] == "Gagne" else -1
        if r.get("m1"):
            r["esp"] = {"1": r["m1"], "N": r["mn"], "2": r["m2"]}[r["pari"]] * r["cote"] - 1
        else:
            r["esp"] = None
    else:
        r["rp"], r["profit"], r["esp"] = None, None, None
    r["pfav"] = max(r["p1"], r["pn"], r["p2"])
    r["tranche"] = next(lab for lab, lo, hi in TRANCHES if lo <= r["pfav"] < hi)
    return r


def _moy(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def bilan(journal, params):
    """Reproduit les blocs B7:C20, F7:L10, N7:R14 et F16:L21 de l'onglet Resultats."""
    j = [enrichir(r) for r in journal]
    n = len(j)
    syn = {
        "Matchs enregistres": n,
        "Verdict modele correct": _moy([r["ok"] for r in j]),
        "Verdict marche correct": _moy([r["okm"] for r in j]),
        "Log-loss modele": _moy([r["ll"] for r in j]),
        "Log-loss marche": _moy([r["llm"] for r in j]),
        "Log-loss d'un tirage a 33 %": 1.0986,
        "Brier modele": _moy([r["brier"] for r in j]),
        "Buts par match observes": _moy([r["bd"] + r["be"] for r in j]),
        "Buts par match attendus": _moy([r["xd"] + r["xe"] for r in j]),
        "Part de victoires a domicile": _moy([1.0 if r["res"] == "1" else 0.0 for r in j]),
        "Part de matchs nuls": _moy([1.0 if r["res"] == "N" else 0.0 for r in j]),
        "Part de victoires a l'exterieur": _moy([1.0 if r["res"] == "2" else 0.0 for r in j]),
    }
    # Resultats C16 : correctif de buts, amorti par MIN(n/200,1).
    amorti = min(n / 200.0, 1.0) if n else 0.0
    bo, ba = syn["Buts par match observes"], syn["Buts par match attendus"]
    syn["Correctif de buts suggere"] = (
        params["correctif_buts"] * (1 + (bo / ba - 1) * amorti) if bo and ba else params["correctif_buts"])
    # Resultats C17 : avantage du terrain, meme amortissement.
    sd, se = sum(r["bd"] for r in j), sum(r["be"] for r in j)
    xd, xe = sum(r["xd"] for r in j), sum(r["xe"] for r in j)
    if se and xe and xd:
        ratio = ((sd / se) / (xd / xe)) ** 0.5
        syn["Avantage du terrain suggere"] = params["avantage_terrain"] * (1 + (ratio - 1) * amorti)
    else:
        syn["Avantage du terrain suggere"] = params["avantage_terrain"]

    rend = []
    for v in VERDICTS:
        sel = [r for r in j if r.get("vp") == v and r.get("rp")]
        if not sel:
            rend.append([v, 0, 0, None, 0.0, None, None])
            continue
        g = sum(1 for r in sel if r["rp"] == "Gagne")
        prof = sum(r["profit"] for r in sel)
        esp = [r["esp"] for r in sel if r["esp"] is not None]
        rend.append([v, len(sel), g, g / len(sel), prof, prof / len(sel),
                     sum(esp) if esp else None])

    cal = []
    for lab, _, _ in TRANCHES:
        sel = [r for r in j if r["tranche"] == lab]
        if not sel:
            cal.append([lab, 0, None, None, None])
            continue
        obs = _moy([r["ok"] for r in sel])
        ann = _moy([r["pfav"] for r in sel])
        cal.append([lab, len(sel), obs, ann, obs - ann])

    champ = []
    for c in sorted({r["comp"] for r in j}):
        sel = [r for r in j if r["comp"] == c]
        champ.append([c, len(sel), _moy([r["ok"] for r in sel]), _moy([r["ll"] for r in sel]),
                      _moy([r["llm"] for r in sel]),
                      _moy([r["bd"] + r["be"] for r in sel]),
                      _moy([r["xd"] + r["xe"] for r in sel])])
    champ.sort(key=lambda x: -x[1])
    return j, syn, rend, cal, champ


def balayage_poids_marche(journal):
    """Cherche le poids de marche qui minimise la log-loss sur le journal.

    Le journal ne conserve que les probabilites deja melangees, donc le balayage
    part du modele reconstitue : p_modele = (p_verdict - w*p_marche)/(1-w).
    """
    lignes = [r for r in journal if r.get("m1") and r.get("w") is not None and r["w"] < 1]
    if len(lignes) < 30:
        return None
    best, bw = None, None
    for i in range(0, 21):
        w = i / 20.0
        tot, n = 0.0, 0
        for r in lignes:
            w0 = r["w"]
            base = {}
            for k, mk in (("p1", "m1"), ("pn", "mn"), ("p2", "m2")):
                base[k] = (r[k] - w0 * r[mk]) / (1 - w0)
            p = {k: base[k] * (1 - w) + w * r[mk] for k in ("p1", "pn", "p2")}
            s = sum(p.values())
            if s <= 0:
                continue
            res = issue(r["bd"], r["be"])
            pv = {"1": p["p1"], "N": p["pn"], "2": p["p2"]}[res] / s
            tot += -math.log(max(1e-4, pv))
            n += 1
        if n and (best is None or tot / n < best):
            best, bw = tot / n, w
    return {"poids": bw, "logloss": best, "n": len(lignes)}
