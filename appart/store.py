"""Stockage JSON : déduplication inter-portails et métadonnées de collecte.

Le fichier produit est destiné à un dépôt public : il ne contient que des
faits d'annonce. Les statuts de suivi et les préférences vivent dans le
navigateur, pas ici.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .model import Listing, LOYER_PLAFOND_DUR


def _cle_ville(nom: str) -> str:
    """Clé de regroupement : sans accent, sans casse, sans numéro de secteur.

    Immoweb écrit la même commune « Liège », « Liege », « LIEGE », « Liege 1 »
    ou « Liège 2 » selon les annonces. Sans cette clé, une seule ville se
    présente comme cinq et le filtre par commune devient inutilisable.
    """
    s = unicodedata.normalize("NFKD", nom or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+\d+$", "", s.strip().lower())
    return re.sub(r"[^a-z]+", " ", s).strip()


def canoniser_villes(rows: list[dict]) -> int:
    """Fusionne les variantes d'écriture d'une même commune. Renvoie le nombre corrigé.

    Détache aussi le secteur quand le portail écrit « Liège Angleur » : la
    commune devient Liège et Angleur passe en quartier, ce qui est l'info utile.
    """
    groupes: dict[str, Counter] = {}
    for r in rows:
        if r.get("ville"):
            groupes.setdefault(_cle_ville(r["ville"]), Counter())[r["ville"]] += 1

    # Forme d'affichage retenue : la plus fréquente, en préférant les accents
    canon = {
        cle: max(c, key=lambda v: (c[v], any(ch in v for ch in "éèêëàâîïôûù"), -len(v)))
        for cle, c in groupes.items()
    }
    cles_connues = set(canon)

    corriges = 0
    for r in rows:
        v = r.get("ville")
        if not v:
            continue
        cle = _cle_ville(v)

        # « Liège Angleur » : commune connue suivie d'un secteur. On découpe dès
        # qu'un préfixe désigne une commune nettement plus représentée — sinon
        # « Liège Angleur » resterait une commune à part entière face à « Liège ».
        mots = cle.split()
        if len(mots) > 1:
            miens = sum(groupes.get(cle, Counter()).values())
            for n in range(len(mots) - 1, 0, -1):
                base = " ".join(mots[:n])
                if base in cles_connues and sum(groupes[base].values()) > miens:
                    if not r.get("quartier"):
                        r["quartier"] = " ".join(v.split()[n:]).strip() or None
                    cle = base
                    break

        nouveau = canon.get(cle, v)
        if nouveau != v:
            r["ville"] = nouveau
            corriges += 1
    return corriges

RACINE = Path(__file__).resolve().parent.parent
FICHIER = RACINE / "docs" / "data" / "listings.json"


def _cle_doublon(li: Listing | dict) -> str:
    """Deux annonces du même bien sur deux portails : même prix, surface, CP."""
    g = (lambda k: getattr(li, k, None)) if isinstance(li, Listing) else li.get
    return f"{round(g('loyer') or 0)}|{round(g('surface') or 0)}|{g('code_postal') or ''}"


def charger() -> dict:
    if FICHIER.exists():
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    return {"meta": {}, "listings": []}


def sauver(payload: dict) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def fusionner(nouvelles: Iterable[Listing]) -> dict:
    """Fusionne un lot dans le corpus, en conservant la date de première vue."""
    base = charger()
    par_uid = {l["uid"]: l for l in base["listings"]}
    par_cle = {_cle_doublon(l): l for l in base["listings"]}

    ajouts = maj = 0
    for li in nouvelles:
        d = li.to_dict()
        ancien = par_uid.get(li.uid) or par_cle.get(_cle_doublon(li))
        if ancien:
            d["vu_le_premier"] = ancien.get("vu_le_premier", d["vu_le"])
            ancien.update(d)
            maj += 1
        else:
            d["vu_le_premier"] = d["vu_le"]
            base["listings"].append(d)
            par_uid[li.uid] = d
            par_cle[_cle_doublon(li)] = d
            ajouts += 1

    villes_corrigees = canoniser_villes(base["listings"])

    # Tri par fraîcheur : le classement par pertinence se fait côté navigateur,
    # puisqu'il dépend d'un budget qu'on ne connaît pas ici.
    base["listings"].sort(key=lambda l: l.get("vu_le_premier") or "", reverse=True)

    base["meta"] = {
        "derniere_maj": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(base["listings"]),
        "loyer_plafond_collecte": LOYER_PLAFOND_DUR,
        "par_source": _compte(base["listings"], "source"),
        "par_ville": _compte(base["listings"], "ville"),
        "avec_position": sum(1 for l in base["listings"] if l.get("lat") is not None),
        "colocations": sum(1 for l in base["listings"] if l.get("colocation")),
    }
    sauver(base)
    return {"ajouts": ajouts, "mises_a_jour": maj, **base["meta"]}


def _compte(rows: list[dict], champ: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[r.get(champ) or "?"] = out.get(r.get(champ) or "?", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def purger(jours: int = 45) -> int:
    """Retire les annonces plus vues depuis N jours. Renvoie le nombre retiré."""
    from datetime import timedelta
    base = charger()
    limite = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    avant = len(base["listings"])
    base["listings"] = [l for l in base["listings"] if (l.get("vu_le") or "") >= limite]
    retires = avant - len(base["listings"])
    if retires:
        base["meta"]["total"] = len(base["listings"])
        sauver(base)
    return retires
