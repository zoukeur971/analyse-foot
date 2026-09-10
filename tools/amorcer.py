# -*- coding: utf-8 -*-
"""Genere un docs/data.json de depart a partir des rencontres deja connues,
pour que le site affiche quelque chose avant le premier passage du job."""
import datetime as dt
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
from engine.build import forces, calcul, DATA, DOCS       # noqa: E402
from engine import model                                   # noqa: E402
from engine.calibrate import bilan                         # noqa: E402


def main(source):
    params = json.load(open(os.path.join(DATA, "params.json"), encoding="utf-8"))
    base = json.load(open(os.path.join(DATA, "teams_base.json"), encoding="utf-8"))
    h2h = json.load(open(os.path.join(DATA, "h2h.json"), encoding="utf-8"))
    journal = json.load(open(os.path.join(DATA, "results.json"), encoding="utf-8"))
    forme = json.load(open(os.path.join(DATA, "forme.json"), encoding="utf-8"))
    fixtures = json.load(open(source, encoding="utf-8"))
    eq, moy = forces(base, forme, params)
    upcoming, sel = [], []
    for f in fixtures:
        r = calcul(f, eq, moy, h2h, params, f.get("cotes"))
        if not r:
            continue
        s = model.selection(r, params)
        upcoming.append({k: v for k, v in r.items() if k != "id"})
        sel.append(dict(date=r["date"], heure=r["heure"], comp=r["comp"],
                        match=r["dom"] + " - " + r["ext"], **s))
    ret = [s for s in sel if s["verdict"] == "RETENU"]
    journal_enrichi, syn, rend, cal, champ = bilan(journal, params)
    out = {
        "meta": {"maj": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                 "fenetre": 7, "debut": min(u["date"] for u in upcoming),
                 "fin": max(u["date"] for u in upcoming),
                 "competitions": sorted({u["comp"] for u in upcoming}),
                 "params": {k: v for k, v in params.items() if k != "historique"},
                 "cotes": sum(1 for u in upcoming if u.get("c1")), "amorce": True},
        "upcoming": upcoming, "sel": sel,
        "selsyn": {"retenues": len(ret),
                   "seuil_n": len([s for s in sel if s["verdict"] in ("RETENU", "Cote insuffisante")]),
                   "taux": sum(s["p"] for s in ret) / len(ret) if ret else None,
                   "cote": sum(s["cote"] for s in ret) / len(ret) if ret else None,
                   "edge": sum(s["edge"] for s in ret) / len(ret) if ret else None,
                   "mise": sum(s["mise"] or 0 for s in ret),
                   "gain": sum((s["mise"] or 0) * s["edge"] for s in ret)},
        "results": [{k: v for k, v in r.items() if k in (
            "date", "comp", "dom", "ext", "bd", "be", "res", "xd", "xe", "p1", "pn", "p2",
            "m1", "mn", "m2", "vm", "ok", "vmar", "okm", "pari", "cote", "vp", "rp", "profit")}
            for r in journal_enrichi],
        "syn": syn, "rend": rend, "cal": cal, "champ": champ,
    }
    os.makedirs(DOCS, exist_ok=True)
    json.dump(out, open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print("docs/data.json :", len(upcoming), "rencontres,", len(journal), "matchs joues")


if __name__ == "__main__":
    main(sys.argv[1])
