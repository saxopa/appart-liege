"""Annonce normalisée, source-agnostique.

Ce module ne produit que des **faits** : loyer, surface, équipements,
coordonnées. Aucun budget, aucun score, aucune préférence — tout cela vit dans
le navigateur (`web/app.js`) et ne quitte jamais l'ordinateur de qui consulte
la page. C'est ce qui permet de publier `listings.json` dans un dépôt public
sans y exposer la situation financière de personne.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any

# Plafond de collecte : au-delà on n'indexe pas, pour garder le JSON utile.
# Ce n'est pas un budget, c'est une borne technique — le filtrage réel se fait
# côté navigateur.
LOYER_PLAFOND_DUR = 1400
LOYER_PLANCHER_DUR = 200

_BALCON = re.compile(r"\b(balcon|loggia|terrasse|terasse)\w*", re.I)
_PARKING = re.compile(r"\b(parking|garage|stationnement|emplacement|carport|box\s+ferm)\w*", re.I)
_ASCENSEUR = re.compile(r"\bascenseur\w*", re.I)
_NEG = re.compile(r"\b(sans|pas de|aucun[e]?)\s+(balcon|terrasse|parking|garage|ascenseur)", re.I)

# Une colocation annonce la surface du logement entier pour le prix d'une
# chambre : sans ce garde-fou le €/m² est faux d'un facteur trois. Beaucoup
# d'annonces ne disent jamais « colocation » et écrivent seulement « une
# chambre dans un appartement ». En Belgique s'ajoute le « kot », le logement
# étudiant partagé.
_COLOC = re.compile(
    r"\b(?:"
    r"coloc\w*|room\s*mate|par\s+chambre|kot\b|kots\b|studentenkamer|"
    r"chambres?\s+(?:meubl\w+\s+)?(?:disponibles?|à\s+louer|dans\s+(?:un|le|cet)\b)|"
    r"loue\s+(?:une\s+)?chambre|location\s+d[e']\s*une\s+chambre|"
    r"une\s+chambre\s+est\s+disponible"
    r")\b",
    re.I,
)


def _detect(pattern: re.Pattern, *texts: str | None) -> bool | None:
    """True si mentionné positivement, False si nié, None si silence."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    for neg in _NEG.finditer(blob):
        if pattern.search(neg.group(2)):
            return False
    return True if pattern.search(blob) else None


@dataclass
class Listing:
    uid: str
    source: str
    titre: str
    url: str
    loyer: float | None = None            # € / mois
    charges: float | None = None
    charges_comprises: bool | None = None
    surface: float | None = None          # m²
    pieces: int | None = None
    chambres: int | None = None
    type_bien: str | None = None
    ville: str | None = None
    code_postal: str | None = None
    quartier: str | None = None
    province: str | None = None
    adresse: str | None = None
    lat: float | None = None
    lon: float | None = None
    etage: int | None = None
    balcon: bool | None = None
    parking: bool | None = None
    ascenseur: bool | None = None
    meuble: bool | None = None
    cave: bool | None = None
    colocation: bool = False
    dpe: str | None = None
    depot_garantie: float | None = None
    date_dispo: str | None = None
    date_publication: str | None = None
    description: str = ""
    photos: list[str] = field(default_factory=list)
    contact: str | None = None
    pro: bool | None = None
    # Seul champ dérivé conservé : c'est un fait, pas un jugement.
    eur_m2: float | None = None
    vu_le: str | None = None

    @staticmethod
    def make_uid(source: str, ident: str) -> str:
        return f"{source}:{hashlib.sha1(ident.encode()).hexdigest()[:12]}"

    def enrich(self) -> "Listing":
        """Complète ce qui se déduit du texte libre. N'évalue rien."""
        # Les portails écrivent « Liège », « LIEGE » ou « liège  » : sans
        # normalisation le regroupement par commune éclate en doublons.
        if self.ville:
            v = re.sub(r"\s+", " ", self.ville).strip(" -–,")
            self.ville = v.title() if (v.isupper() or v.islower()) else v
        if self.quartier:
            self.quartier = re.sub(r"\s+", " ", self.quartier).strip()

        blob = (self.titre, self.description)
        self.colocation = bool(_COLOC.search(" ".join(t for t in blob if t)))

        if self.balcon is None:
            self.balcon = _detect(_BALCON, *blob)
        if self.parking is None:
            self.parking = _detect(_PARKING, *blob)
        if self.ascenseur is None:
            self.ascenseur = _detect(_ASCENSEUR, *blob)

        # En colocation la surface annoncée est celle du logement entier :
        # en tirer un €/m² serait trompeur.
        if self.loyer and self.surface and not self.colocation:
            self.eur_m2 = round(self.loyer / self.surface, 2)

        return self

    def rejet(self) -> str | None:
        """Motif d'exclusion du corpus, ou None si l'annonce est exploitable.

        Filtre deux choses : les biens qui ne sont pas des logements (boxes,
        caves, places de parking louées seules) et les valeurs si basses
        qu'elles trahissent une erreur d'extraction plutôt qu'une bonne affaire.
        """
        blob = f"{self.titre} {self.type_bien or ''}".lower()
        if re.search(r"\b(coworking|co-?working|espace\s+de\s+travail|bureau\s+partag)", blob):
            return "espace de travail, pas un logement"
        if re.search(r"\b(garage|box[eé]?|parking|cave|cellier|local\s+commercial|bureau|entrep[oô]t)\b", blob) \
           and not re.search(r"\b(appartement|studio|flat|maison|logement|pi[eè]ce|chambre)\b", blob):
            return "pas un logement"
        if self.loyer is None:
            return "loyer inconnu"
        if self.loyer < LOYER_PLANCHER_DUR:
            return f"loyer implausible ({self.loyer:.0f} €)"
        if self.eur_m2 is not None and self.eur_m2 < 4:
            return f"€/m² implausible ({self.eur_m2:.1f}) — extraction douteuse"
        if self.loyer > LOYER_PLAFOND_DUR:
            return f"hors plafond ({self.loyer:.0f} € > {LOYER_PLAFOND_DUR} €)"
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
