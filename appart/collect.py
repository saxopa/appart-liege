"""Orchestrateur de collecte : interroge les sources, filtre, fusionne.

Sort en code 1 si la moisson est anormalement maigre. C'est volontaire : en
intégration continue, un échec bruyant vaut mieux qu'un tableau de bord qui se
vide en silence parce qu'un portail a commencé à bloquer le runner.
"""
from __future__ import annotations

import sys
import traceback

from .model import Listing
from .sources import immoweb
from .store import fusionner, purger

# Liège et son agglomération. Immoweb élargit déjà autour du code postal,
# mais viser plusieurs pôles couvre mieux la périphérie.
ZONES = [
    ("liege", "4000"),
    ("seraing", "4100"),
    ("herstal", "4040"),
    ("ans", "4430"),
    ("chaudfontaine", "4050"),
]

SOURCES = {
    "immoweb": lambda: [li for z in ZONES for li in immoweb.fetch(z[0], z[1])],
}

# En dessous, on considère que la collecte a échoué plutôt que réussi à vide.
SEUIL_ALERTE = 40


def collecter(sources: list[str] | None = None) -> dict:
    cibles = sources or list(SOURCES)
    trouvees: list[Listing] = []
    rapport: dict[str, object] = {}
    rejets: dict[str, int] = {}

    for nom in cibles:
        fn = SOURCES.get(nom)
        if not fn:
            rapport[nom] = "source inconnue"
            continue
        try:
            lot = fn()
            gardees = []
            for li in lot:
                motif = li.rejet()
                if motif:
                    cle = motif.split("(")[0].strip()
                    rejets[cle] = rejets.get(cle, 0) + 1
                else:
                    gardees.append(li)
            trouvees.extend(gardees)
            rapport[nom] = {"brut": len(lot), "retenues": len(gardees)}
        except Exception as e:
            rapport[nom] = f"échec: {type(e).__name__}: {e}"
            traceback.print_exc()

    resume = fusionner(trouvees)
    resume["purgees"] = purger()
    return {"par_source_collectee": rapport, "rejets": rejets,
            "recoltees_ce_run": len(trouvees), **resume}


if __name__ == "__main__":
    import json
    args = sys.argv[1:] or None
    res = collecter(args)
    print(json.dumps(res, ensure_ascii=False, indent=2))

    if res["recoltees_ce_run"] < SEUIL_ALERTE:
        print(
            f"\nERREUR : seulement {res['recoltees_ce_run']} annonces récoltées "
            f"(seuil {SEUIL_ALERTE}). Le portail bloque probablement cette IP. "
            f"Le corpus publié n'est PAS mis à jour à vide.",
            file=sys.stderr,
        )
        sys.exit(1)
