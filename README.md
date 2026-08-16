# Chercher un appart à Liège

Une page qui rassemble les annonces de location de Liège et des environs, et
les classe selon **votre** budget. Rien à installer : vous ouvrez le lien.

👉 **https://saxopa.github.io/appart-liege/**

## Comment s'en servir

1. Cliquez sur **⚙ Mon budget** en haut à droite.
2. Indiquez ce que vous pouvez payer par mois, et l'aide au logement que vous
   touchez éventuellement (mettez 0 si vous n'en avez pas — en Wallonie elle
   n'est pas automatique).
3. Cochez ce à quoi vous tenez : balcon, parking, ascenseur.
4. Fermez le panneau. Les annonces se reclassent immédiatement.

Le chiffre coloré en haut à droite de chaque annonce est une note sur 100 :
plus elle est haute, plus le bien colle à ce que vous avez indiqué. Les
raisons sont listées sous la fiche, donc vous pouvez vérifier le raisonnement
au lieu de le croire sur parole.

**Vue carte** : le bouton *Carte*, à droite des filtres. Vert = dans votre
budget avec vos critères réunis, bleu = dans le budget, orange = au-dessus de
votre part. Les filtres s'appliquent aux deux vues.

Le menu déroulant sur chaque annonce (*Nouveau*, *À visiter*, *Contacté*…)
sert à suivre où vous en êtes.

### Vos données restent chez vous

Votre budget, vos critères et vos statuts sont enregistrés **dans votre
navigateur uniquement**. Ils ne partent sur aucun serveur, ne sont visibles de
personne, et ne figurent pas dans ce dépôt. Ce qui est publié ici, ce sont
seulement les annonces — qui sont déjà publiques sur Immoweb.

Corollaire : si vous changez d'ordinateur ou videz l'historique de votre
navigateur, vos réglages sont à ressaisir.

## Sous le capot

Une collecte tourne chaque matin sur GitHub Actions, récupère les annonces et
met à jour `docs/data/listings.json`. La page est servie par GitHub Pages.
Aucun serveur à louer, aucun coût.

| Source | Accès | Note |
|---|---|---|
| **Immoweb** | JSON embarqué dans les pages de recherche | Zones : Liège, Seraing, Herstal, Ans, Chaudfontaine |
| ~~Immovlan~~ | — | Écarté : protection anti-robot active |
| ~~Zimmo~~ | — | Écarté : son `robots.txt` interdit les pages de recherche |

### Conformité

Chaque requête passe par `appart/robots.py` : lecture et respect du
`robots.txt` de l'hôte, liste d'exclusion pour les sites qui interdisent les
robots, 1,5 s minimum entre deux requêtes, et empreinte TLS de navigateur réel
via `curl_cffi`. Le `robots.txt` d'Immoweb n'interdit pas les pages de
recherche standard ; les chemins qu'il protège (`/profil/`, `/publier-une-annonce/`,
`*/recherche-avancee/*`) ne sont jamais sollicités.

### Contrôle qualité

Trois pièges de données sont traités, tous repérés parce qu'ils faussaient le
classement :

1. **Colocations** — une coloc annonce la surface du logement entier pour le
   prix d'une chambre, ce qui divise le €/m² par trois et lui ferait truster
   le haut du classement. Beaucoup n'emploient jamais le mot « colocation » et
   écrivent seulement « une chambre dans un appartement » ou « kot ». Elles
   sont détectées, signalées, et masquées par défaut.
2. **Biens qui ne sont pas des logements** — garages, caves, emplacements de
   parking loués seuls.
3. **Surfaces aberrantes** — Immoweb publie par exemple un « studio » de
   330 m². Un loyer sous 4 €/m² trahit une erreur de saisie, pas une affaire.

Les communes sont aussi canonisées : le portail écrit la même ville « Liège »,
« Liege », « LIEGE », « Liege 1 » ou « Liège Angleur » selon les annonces, ce
qui présentait une seule commune comme six et rendait le filtre inutilisable.

## Développement

```bash
uv run python -m appart.collect        # collecter
cd docs && python3 -m http.server 8777  # voir la page en local
```

La collecte sort en code 1 si elle ramène moins de 40 annonces : en
intégration continue, un échec visible vaut mieux qu'un tableau de bord vidé
en silence.

```
appart/
  model.py     annonce normalisée — ne produit que des faits, aucun score
  robots.py    garde-fou robots.txt, rythme, empreinte TLS
  store.py     JSON, déduplication, canonisation des communes
  collect.py   orchestrateur, seuil d'alerte
  sources/immoweb.py
docs/
  index.html style.css app.js   le budget et le classement vivent ici
  data/listings.json            produit par la collecte
```

Le classement est volontairement en JavaScript et non en Python : il dépend
d'un budget personnel, qui n'a donc pas à transiter par un dépôt public.
