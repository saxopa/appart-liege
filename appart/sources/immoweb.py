"""Immoweb — le portail dominant en Belgique.

Chaque page de recherche embarque ses résultats en JSON dans un attribut de
composant Vue. On ne parse donc pas le HTML des cartes : on lit directement
les données que la page se sert à elle-même.

Piège vérifié : la même page porte aussi un attribut `:results-list` qui, lui,
contient du HTML de quick-search et non les annonces. D'où l'extraction par
essai-erreur sur toutes les valeurs candidates plutôt que par position.
"""
from __future__ import annotations

import html as H
import json
import re
from datetime import datetime, timezone

from ..model import Listing
from ..robots import polite_get

BASE = "https://www.immoweb.be/fr/recherche"
# Attributs susceptibles de porter la liste, du plus fiable au moins fiable.
ATTRS = ("classifieds-list", "results", "results-list")

_EQUIPEMENTS = {
    "balcon": re.compile(r"\b(balcon|terrasse|loggia)\w*", re.I),
    "parking": re.compile(r"\b(parking|garage|emplacement de parking|carport)\w*", re.I),
    "ascenseur": re.compile(r"\bascenseur\w*", re.I),
}


def _valeurs_attribut(html: str, nom: str) -> list[str]:
    """Toutes les valeurs de l'attribut `:nom`, quel que soit le délimiteur."""
    out = []
    for m in re.finditer(rf":{re.escape(nom)}=(['\"])", html):
        delim, debut = m.group(1), m.end()
        fin = html.find(delim, debut)
        if fin > debut:
            out.append(html[debut:fin])
    return out


def extraire(html: str) -> list[dict]:
    """Renvoie la liste d'annonces embarquée dans la page, ou [] si absente."""
    for nom in ATTRS:
        for brut in sorted(_valeurs_attribut(html, nom), key=len, reverse=True):
            try:
                d = json.loads(H.unescape(brut))
                while isinstance(d, str):   # la valeur est parfois doublement encodée
                    d = json.loads(d)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(d, list) and d and isinstance(d[0], dict) and "property" in d[0]:
                return d
    return []


def _loyer(ad: dict) -> float | None:
    """Le loyer se trouve selon les annonces dans price.mainValue ou transaction.rental."""
    prix = ad.get("price") or {}
    for v in (prix.get("mainValue"), prix.get("alternativeValue"), prix.get("minRangeValue")):
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    loc = (ad.get("transaction") or {}).get("rental") or {}
    for cle in ("monthlyRentalPrice", "price"):
        v = loc.get(cle)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _to_listing(ad: dict) -> Listing:
    prop = ad.get("property") or {}
    loc = prop.get("location") or {}
    ident = str(ad.get("id") or ad.get("advertisementId") or prop.get("title"))

    titre = (prop.get("title") or "").strip()
    if not titre:
        sous_type = (prop.get("subtype") or prop.get("type") or "Bien").replace("_", " ").title()
        titre = f"{sous_type} — {loc.get('locality') or 'Liège'}"

    # Immoweb ne renvoie pas de description en page de recherche : les
    # équipements se lisent dans le titre et le sous-type uniquement.
    blob = f"{titre} {prop.get('subtype') or ''}"
    equip = {k: (True if rx.search(blob) else None) for k, rx in _EQUIPEMENTS.items()}

    rue = " ".join(str(x) for x in (loc.get("street"), loc.get("number")) if x)

    return Listing(
        uid=Listing.make_uid("immoweb", ident),
        source="immoweb",
        titre=titre[:160],
        url=f"https://www.immoweb.be/fr/annonce/{ad.get('id')}",
        loyer=_loyer(ad),
        charges=None,
        surface=prop.get("netHabitableSurface"),
        pieces=prop.get("roomCount"),
        chambres=prop.get("bedroomCount"),
        type_bien=(prop.get("subtype") or prop.get("type") or "").replace("_", " ").lower() or None,
        ville=loc.get("locality"),
        code_postal=str(loc.get("postalCode")) if loc.get("postalCode") else None,
        quartier=loc.get("district") or loc.get("propertyName"),
        province=loc.get("province"),
        adresse=rue or None,
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
        etage=loc.get("floor"),
        balcon=equip["balcon"],
        parking=equip["parking"],
        ascenseur=equip["ascenseur"],
        date_publication=(ad.get("publication") or {}).get("creationDate"),
        description="",
        photos=[m.get("url") for m in (ad.get("media") or {}).get("pictures", [])[:6]
                if isinstance(m, dict) and m.get("url")],
        contact=ad.get("customerName"),
        pro=True,  # Immoweb est un portail d'agences ; le particulier y est rare
        vu_le=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ).enrich()


def fetch(ville: str = "liege", code_postal: str = "4000",
          loyer_max: int = 1200, max_pages: int = 12) -> list[Listing]:
    """Parcourt les pages de résultats jusqu'à épuisement ou plafond."""
    out: list[Listing] = []
    vus: set[str] = set()

    for page in range(1, max_pages + 1):
        url = (f"{BASE}/appartement/a-louer/{ville}/{code_postal}"
               f"?countries=BE&maxPrice={loyer_max}&page={page}&orderBy=newest")
        r = polite_get(url)
        if r.status_code != 200:
            break
        ads = extraire(r.text)
        if not ads:
            break
        nouvelles = 0
        for ad in ads:
            try:
                li = _to_listing(ad)
            except Exception:
                continue
            if li.uid not in vus:
                vus.add(li.uid)
                out.append(li)
                nouvelles += 1
        if nouvelles == 0:      # la pagination boucle sur la même page
            break
    return out
