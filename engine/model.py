"""Modele de Poisson bivarie avec correction Dixon-Coles.

Portage fidele des onglets Moteur, Matchs semaine et Selections du classeur
Analyse_football_paris_sportifs.xlsx. Les formules d'origine sont citees en
commentaire au-dessus de chaque bloc.
"""
import math

KMAX = 10  # buts maximum consideres par equipe (le classeur s'arretait a 8)


def poisson(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score_matrix(lh, la, rho):
    """Matrice des scores exacts, correction Dixon-Coles sur les quatre petits scores.

    Moteur!AH145:AJ145 : tau(0,0)=1-lh*la*rho, tau(0,1)=1+lh*rho,
    tau(1,0)=1+la*rho, tau(1,1)=1-rho.
    """
    ph = [poisson(i, lh) for i in range(KMAX + 1)]
    pa = [poisson(j, la) for j in range(KMAX + 1)]
    m = [[ph[i] * pa[j] for j in range(KMAX + 1)] for i in range(KMAX + 1)]
    m[0][0] *= 1 - lh * la * rho
    m[0][1] *= 1 + lh * rho
    m[1][0] *= 1 + la * rho
    m[1][1] *= 1 - rho
    tot = sum(sum(r) for r in m)
    if tot > 0:
        m = [[v / tot for v in r] for r in m]
    return m


def markets(lh, la, rho):
    """Toutes les probabilites tirees de la matrice, normalisees comme Moteur!AK145."""
    m = score_matrix(lh, la, rho)
    p1 = pn = p2 = 0.0
    o15 = o25 = 0.0
    best, bestp = (0, 0), -1.0
    for i in range(KMAX + 1):
        for j in range(KMAX + 1):
            v = m[i][j]
            if i > j:
                p1 += v
            elif i == j:
                pn += v
            else:
                p2 += v
            if i + j >= 2:
                o15 += v
            if i + j >= 3:
                o25 += v
            if v > bestp:
                bestp, best = v, (i, j)
    ph0 = sum(m[0])
    pa0 = sum(m[i][0] for i in range(KMAX + 1))
    btts = 1 - ph0 - pa0 + m[0][0]
    return {
        "p1": p1, "pn": pn, "p2": p2,
        "o15": o15, "o25": o25, "btts": btts,
        "score": "%d - %d" % best,
    }


def lambdas(home, away, params, league_avg):
    """Matchs semaine!F et G.

    xd = moyenne_ligue * attaque(dom) * defense(ext) * avantage_terrain * correctif
    xe = moyenne_ligue * attaque(ext) * defense(dom) / avantage_terrain * correctif
    """
    ha = params["avantage_terrain"]
    corr = params["correctif_buts"]
    lh = league_avg * home["att"] * away["def"] * ha * corr
    la = league_avg * away["att"] * home["def"] / ha * corr
    return max(lh, 0.05), max(la, 0.05)


def blend_h2h(p, h2h, poids):
    """Matchs semaine!P:R — melange du modele et des confrontations directes."""
    n = h2h.get("n", 0)
    if not n:
        return p["p1"], p["pn"], p["p2"]
    w = poids
    return (
        p["p1"] * (1 - w) + w * h2h["v1"] / n,
        p["pn"] * (1 - w) + w * h2h["nul"] / n,
        p["p2"] * (1 - w) + w * h2h["v2"] / n,
    )


def devig(c1, cn, c2):
    """Matchs semaine!AE:AH — marge du bookmaker puis probabilites devigees."""
    if not (c1 and cn and c2):
        return None
    marge = 1 / c1 + 1 / cn + 1 / c2 - 1
    return {
        "marge": marge,
        "m1": (1 / c1) / (1 + marge),
        "mn": (1 / cn) / (1 + marge),
        "m2": (1 / c2) / (1 + marge),
    }


def verdict_probs(q1, qn, q2, mk, poids_marche):
    """Matchs semaine!AM:AO — melange modele / marche (Parametres C15)."""
    if not mk:
        return q1, qn, q2
    w = poids_marche
    return (
        q1 * (1 - w) + w * mk["m1"],
        qn * (1 - w) + w * mk["mn"],
        q2 * (1 - w) + w * mk["m2"],
    )


def value_bet(q1, qn, q2, c1, cn, c2, mk, params, inter_champ):
    """Matchs semaine!AI:AL — detection sur le modele seul, jamais sur le melange."""
    if not mk:
        return None
    cands = [("1", q1 * c1 - 1, q1, mk["m1"]), ("N", qn * cn - 1, qn, mk["mn"]),
             ("2", q2 * c2 - 1, q2, mk["m2"])]
    pari, edge, p, pm = max(cands, key=lambda x: x[1])
    div = p / pm if pm else None
    cote = {"1": c1, "N": cn, "2": c2}[pari]
    if div is None:
        vp = "Pas de valeur"
    elif div > params["divergence_max"]:
        vp = "Ecart suspect"
    elif edge >= params["edge_min"] and cote <= params["cote_max"] and not inter_champ:
        vp = "PARI VALUE"
    else:
        vp = "Pas de valeur"
    return {"pari": pari, "edge": edge, "div": div, "vp": vp}


def selection(row, params):
    """Onglet Selections — meilleure selection au-dessus du seuil de probabilite.

    Les probabilites sont celles du verdict (Matchs semaine AM:AO), pas du modele seul.
    Cotes doubles chances : 1/(1/ca+1/cb). Cote +1,5 but : 1/(p*(1+marge)).
    """
    p1n = row["p1"] + row["pn"]
    p12 = row["p1"] + row["p2"]
    pn2 = row["pn"] + row["p2"]
    p15 = row["o15"]
    c1, cn, c2 = row.get("c1"), row.get("cN"), row.get("c2")
    marge = row.get("marge")
    def dc(a, b):
        return 1 / (1 / a + 1 / b) if a and b else None
    c1n, c12, cn2 = dc(c1, cn), dc(c1, c2), dc(cn, c2)
    c15 = 1 / (p15 * (1 + marge)) if marge is not None and p15 > 0 else None
    opts = [
        ("1N (ne perd pas domicile)", p1n, c1n),
        ("12 (pas de nul)", p12, c12),
        ("N2 (ne perd pas exterieur)", pn2, cn2),
        ("Plus de 1,5 but", p15, c15),
    ]
    seuil = params["proba_min_selection"]
    cmin = params["cote_min_selection"]
    ok = [(lab, p, c) for lab, p, c in opts if c and p >= seuil and c >= cmin]
    out = {"p1n": p1n, "p12": p12, "pn2": pn2, "p15": p15,
           "c1n": c1n, "c12": c12, "cn2": cn2, "c15": c15,
           "lab": None, "p": None, "cote": None, "fair": None,
           "edge": None, "mise": None, "verdict": "Aucune selection a ce seuil"}
    if not ok:
        return out
    lab, p, c = max(ok, key=lambda x: x[1] * x[2] - 1)
    edge = p * c - 1
    out.update(lab=lab, p=p, cote=c, fair=1 / p, edge=edge)
    if edge >= params["edge_min_selection"]:
        out["verdict"] = "RETENU"
        out["mise"] = max(0.0, params["bankroll"] * params["kelly"] * (edge / (c - 1)))
    else:
        out["verdict"] = "Cote insuffisante"
    return out
