'use strict';

/* Le corpus publié ne contient que des faits d'annonce. Tout ce qui touche au
   budget, aux critères et au suivi est calculé ici, dans le navigateur, à
   partir de réglages qui ne quittent jamais cette machine. */

const STATUTS = {
  nouveau:   'Nouveau',
  a_visiter: 'À visiter',
  contacte:  'Contacté',
  visite:    'Visité',
  refuse:    'Refusé',
  pris:      'Pris !',
};

const CLE_STATUTS  = 'appart-liege:statuts';
const CLE_REGLAGES = 'appart-liege:reglages';

const DEFAUTS = {
  budget: 700,        // ce que la personne peut sortir de sa poche
  aide: 0,            // en Wallonie l'aide au logement n'est pas automatique
  surfaceMin: 0,
  chambresMin: 1,
  refLoyer: null,     // logement actuel, pour comparaison
  refSurface: null,
  balcon: false,      // « ce à quoi je tiens » — pondère, ne filtre pas
  parking: false,
  ascenseur: false,
};

let CORPUS = { meta: {}, listings: [] };
let reglages = { ...DEFAUTS, ...lire(CLE_REGLAGES, {}) };
let statuts = lire(CLE_STATUTS, {});

const $ = (s) => document.querySelector(s);
const eur = (n) => n == null ? '—' : Math.round(n).toLocaleString('fr-BE') + ' €';
const statutDe = (l) => statuts[l.uid] ?? 'nouveau';

function lire(cle, defaut) {
  try { return JSON.parse(localStorage.getItem(cle)) ?? defaut; }
  catch { return defaut; }
}
function ecrire(cle, val) { localStorage.setItem(cle, JSON.stringify(val)); }

/* ---------- scoring ----------
   Porté depuis la version Python. La différence tient à ce qu'il est rejoué
   à chaque changement de réglage, au lieu d'être figé dans le fichier. */

function evaluer(l) {
  const pts = [];
  const why = [];
  const budget = reglages.budget || 0;
  const part = l.loyer == null ? null : l.loyer - (reglages.aide || 0);
  const refEurM2 = (reglages.refLoyer && reglages.refSurface)
    ? reglages.refLoyer / reglages.refSurface : null;

  let total = 0;

  // Budget — critère dominant (45 pts)
  if (part != null && budget > 0) {
    if (part <= 0) { total += 45; why.push("loyer entièrement couvert par l'aide"); }
    else if (part <= budget) {
      total += 25 + 20 * (1 - part / budget);
      why.push(`votre part : ${Math.round(part)} € (≤ ${budget})`);
    } else {
      const trop = part - budget;
      total += Math.max(0, 20 - trop / 5);
      why.push(`⚠ dépasse de ${Math.round(trop)} €/mois`);
    }
  }

  // Rapport qualité-prix face au logement actuel (20 pts)
  if (l.eur_m2 && refEurM2) {
    if (l.eur_m2 <= refEurM2) {
      total += 20;
      why.push(`${l.eur_m2} €/m² — mieux qu'aujourd'hui (${refEurM2.toFixed(1)})`);
    } else {
      total += Math.max(0, 20 - (l.eur_m2 - refEurM2) * 2.5);
    }
  } else if (l.eur_m2) {
    // Sans référence, on situe par rapport au marché liégeois (~12 €/m²)
    total += l.eur_m2 <= 12 ? 15 : Math.max(0, 15 - (l.eur_m2 - 12) * 2);
  }

  // Surface (10 pts)
  if (l.colocation) {
    why.push('⚠ colocation — la surface annoncée est celle du logement entier');
  } else if (l.surface) {
    const cible = reglages.refSurface || reglages.surfaceMin || 35;
    if (l.surface >= cible) { total += 10; why.push(`${Math.round(l.surface)} m²`); }
    else if (l.surface >= cible * 0.7) total += 5;
    else { total -= 5; why.push(`petit (${Math.round(l.surface)} m²)`); }
  }

  // Chambres
  if (reglages.chambresMin && l.chambres != null) {
    if (l.chambres >= reglages.chambresMin) { total += 4; }
    else { total -= 12; why.push(`✗ ${l.chambres} chambre(s), il en faut ${reglages.chambresMin}`); }
  }

  // Ce à quoi la personne tient (25 pts)
  if (reglages.balcon) {
    if (l.balcon === true) { total += 14; why.push('balcon/terrasse'); }
    else if (l.balcon === false) { total -= 10; why.push('✗ pas de balcon'); }
  } else if (l.balcon === true) { total += 4; why.push('balcon/terrasse'); }

  if (reglages.parking) {
    if (l.parking === true) { total += 6; why.push('parking'); }
  } else if (l.parking === true) { total += 2; }

  if (reglages.ascenseur) {
    if (l.ascenseur === true) { total += 5; why.push('ascenseur'); }
  } else if (l.ascenseur === true) { total += 2; }

  // Divers
  if (l.meuble) { total += 3; why.push('meublé'); }
  if (l.pro === false) { total += 4; why.push('particulier (pas de frais d\'agence)'); }
  if (l.dpe && 'FG'.includes(l.dpe)) { total -= 6; why.push(`PEB ${l.dpe} — charges élevées`); }

  return {
    part,
    score: Math.round(Math.max(0, Math.min(100, total)) * 10) / 10,
    raisons: why,
  };
}

/** Recalcule part/score/raisons sur tout le corpus. Appelé à chaque réglage. */
function reevaluer() {
  for (const l of CORPUS.listings) Object.assign(l, evaluer(l));
}

/* ---------- chargement ---------- */
async function init() {
  try {
    const r = await fetch('data/listings.json', { cache: 'no-store' });
    CORPUS = await r.json();
  } catch {
    $('#grille').innerHTML =
      `<p class="vide">Impossible de charger les annonces.<br>
       Si vous ouvrez le fichier depuis votre disque, servez plutôt le dossier
       en HTTP : <code>python3 -m http.server</code>.</p>`;
    return;
  }
  reevaluer();
  peuplerSelects();
  appliquerReglagesAuFormulaire();
  brancherEvenements();
  rendreBudget();
  basculerVue(location.hash === '#carte' ? 'carte' : 'liste', false);
}

function peuplerSelects() {
  $('#f-statut').append(...Object.entries(STATUTS).map(([k, v]) => new Option(v, k)));
  const parVille = {};
  for (const l of CORPUS.listings) if (l.ville) parVille[l.ville] = (parVille[l.ville] || 0) + 1;
  $('#f-ville').append(...Object.entries(parVille)
    .sort((a, b) => b[1] - a[1])
    .map(([v, n]) => new Option(`${v} (${n})`, v)));
}

function rendreBudget() {
  const m = CORPUS.meta || {};
  const d = m.derniere_maj ? new Date(m.derniere_maj) : null;
  $('#maj').textContent = d
    ? `annonces à jour du ${d.toLocaleDateString('fr-BE')}`
    : '';

  const dansBudget = CORPUS.listings.filter(l => l.part != null && l.part <= reglages.budget).length;
  const cases = [
    ['Ma part max', eur(reglages.budget), false],
    ['Aide déduite', eur(reglages.aide), false],
    ['Loyer visé', eur(reglages.budget + (reglages.aide || 0)), true],
    ['Annonces', m.total ?? CORPUS.listings.length, false],
    ['Dans le budget', dansBudget, true],
  ];
  $('#budget').innerHTML = cases.map(([lib, val, bon]) =>
    `<div><span class="lib">${lib}</span><span class="val${bon ? ' bon' : ''}">${val}</span></div>`).join('');

  $('#f-loyer').placeholder = reglages.budget + (reglages.aide || 0);
  $('#f-rac').placeholder = reglages.budget;
  $('#f-surface').placeholder = reglages.surfaceMin || 0;
}

/* ---------- réglages ---------- */
const CHAMPS_REGLAGES = {
  '#r-budget': 'budget', '#r-aide': 'aide', '#r-surface': 'surfaceMin',
  '#r-chambres': 'chambresMin', '#r-ref-loyer': 'refLoyer', '#r-ref-surface': 'refSurface',
  '#r-balcon': 'balcon', '#r-parking': 'parking', '#r-ascenseur': 'ascenseur',
};

function appliquerReglagesAuFormulaire() {
  for (const [sel, cle] of Object.entries(CHAMPS_REGLAGES)) {
    const el = $(sel);
    if (el.type === 'checkbox') el.checked = !!reglages[cle];
    else el.value = reglages[cle] ?? '';
  }
}

function lireReglagesDepuisFormulaire() {
  for (const [sel, cle] of Object.entries(CHAMPS_REGLAGES)) {
    const el = $(sel);
    if (el.type === 'checkbox') reglages[cle] = el.checked;
    else reglages[cle] = el.value === '' ? (DEFAUTS[cle] ?? null) : Number(el.value);
  }
  ecrire(CLE_REGLAGES, reglages);
  reevaluer();
  rendreBudget();
  rendre();
}

/* ---------- filtrage ---------- */
function filtrer() {
  const v = (s) => $(s).value.trim();
  const n = (s) => v(s) === '' ? null : Number(v(s));
  const c = (s) => $(s).checked;

  const loyerMax = n('#f-loyer'), partMax = n('#f-rac'), surfMin = n('#f-surface');
  const ville = v('#f-ville'), st = v('#f-statut');
  let rx = null;
  if (v('#f-texte')) { try { rx = new RegExp(v('#f-texte'), 'i'); } catch {} }

  const out = CORPUS.listings.filter(l => {
    if (loyerMax != null && (l.loyer ?? Infinity) > loyerMax) return false;
    if (partMax != null && (l.part ?? Infinity) > partMax) return false;
    if (surfMin != null && (l.surface ?? 0) < surfMin) return false;
    if (c('#f-balcon') && l.balcon !== true) return false;
    if (c('#f-parking') && l.parking !== true) return false;
    if (c('#f-ascenseur') && l.ascenseur !== true) return false;
    if (!c('#f-coloc') && l.colocation) return false;
    if (ville && l.ville !== ville) return false;
    const stat = statutDe(l);
    if (st && stat !== st) return false;
    if (!st && c('#f-masquer-refus') && stat === 'refuse') return false;
    if (rx && !rx.test(`${l.titre} ${l.quartier || ''} ${l.adresse || ''} ${l.code_postal || ''} ${l.ville || ''}`)) return false;
    return true;
  });

  const cles = {
    score:   (l) => -(l.score ?? 0),
    rac:     (l) => l.part ?? Infinity,
    surface: (l) => -(l.surface ?? 0),
    eur_m2:  (l) => l.eur_m2 ?? Infinity,
    recent:  (l) => -(new Date(l.date_publication || l.vu_le_premier || 0).getTime() || 0),
  };
  return out.sort((a, b) => cles[v('#f-tri')](a) - cles[v('#f-tri')](b));
}

/* ---------- rendu liste ---------- */
function puce(valeur, libelle) {
  if (valeur === true)  return `<span class="puce oui">✓ ${libelle}</span>`;
  if (valeur === false) return `<span class="puce non">✗ ${libelle}</span>`;
  return `<span class="puce">? ${libelle}</span>`;
}

function carte(l) {
  const stat = statutDe(l);
  const depasse = (l.part ?? Infinity) > reglages.budget;
  const classeScore = l.score >= 65 ? ' haut' : (l.score < 40 ? ' bas' : '');

  return `
  <article class="carte ${stat}">
    <div class="carte-haut">
      <h2 class="titre">${escape(l.titre)}</h2>
      <span class="score${classeScore}">${l.score}</span>
    </div>

    <div class="chiffres">
      <div><span class="lib">Loyer</span><span class="val">${eur(l.loyer)}</span></div>
      <div><span class="lib">Votre part</span><span class="val${depasse ? ' alerte' : ' bon'}">${eur(l.part)}</span></div>
      <div><span class="lib">Surface</span><span class="val">${l.surface ? Math.round(l.surface) + ' m²' : '—'}</span></div>
      <div><span class="lib">€/m²</span><span class="val">${l.eur_m2 ?? '—'}</span></div>
    </div>

    <p class="lieu">${escape([
      l.ville,
      // Immoweb répète souvent la commune en guise de quartier : on n'affiche
      // le quartier que s'il apporte réellement une information de plus.
      (l.quartier && l.quartier !== l.ville) ? l.quartier : null,
      l.code_postal,
      l.chambres != null ? `${l.chambres} ch.` : null,
      l.etage != null ? `étage ${l.etage}` : null,
    ].filter(Boolean).join(' · ')) || '—'}</p>

    <div class="puces">
      ${puce(l.balcon, 'balcon')}
      ${puce(l.parking, 'parking')}
      ${puce(l.ascenseur, 'ascenseur')}
      ${l.meuble ? '<span class="puce oui">meublé</span>' : ''}
      ${l.pro === false ? '<span class="puce oui">particulier</span>' : ''}
      ${l.dpe ? `<span class="puce${'FG'.includes(l.dpe) ? ' alerte' : ''}">PEB ${escape(l.dpe)}</span>` : ''}
      ${l.colocation ? '<span class="puce alerte">colocation</span>' : ''}
    </div>

    ${l.raisons?.length ? `<ul class="raisons">${l.raisons.slice(0, 4).map(r => `<li>${escape(r)}</li>`).join('')}</ul>` : ''}

    <div class="carte-bas">
      ${l.url ? `<a class="lien" href="${escape(l.url)}" target="_blank" rel="noopener">Voir l'annonce</a>` : ''}
      <select class="statut" data-uid="${escape(l.uid)}" aria-label="Statut">
        ${Object.entries(STATUTS).map(([k, v]) =>
          `<option value="${k}"${k === stat ? ' selected' : ''}>${v}</option>`).join('')}
      </select>
    </div>
  </article>`;
}

function rendre() {
  const liste = filtrer();
  const dans = liste.filter(l => (l.part ?? Infinity) <= reglages.budget).length;
  $('#compteur').innerHTML =
    `<b>${liste.length}</b> annonce${liste.length > 1 ? 's' : ''} affichée${liste.length > 1 ? 's' : ''}` +
    ` — dont <b>${dans}</b> sous ${eur(reglages.budget)} de votre poche` +
    ` · ${CORPUS.listings.length} au total`;

  if (vue === 'carte') return rendreCarte(liste);

  $('#grille').innerHTML = liste.length
    ? liste.map(carte).join('')
    : '<p class="vide">Aucune annonce ne correspond. Relâchez un filtre.</p>';

  $('#grille').querySelectorAll('.statut').forEach(sel =>
    sel.addEventListener('change', (e) => {
      statuts[e.target.dataset.uid] = e.target.value;
      ecrire(CLE_STATUTS, statuts);
      rendre();
    }));
}

/* ---------- carte ---------- */
let vue = 'liste';
let carteLeaflet = null;
let coucheMarqueurs = null;

function couleur(l) {
  if ((l.part ?? Infinity) > reglages.budget) return '#d08700';
  const exigences = ['balcon', 'parking', 'ascenseur'].filter(k => reglages[k]);
  const toutes = exigences.every(k => l[k] === true);
  return (exigences.length && toutes) ? '#1a9c5c' : (exigences.length ? '#2b7fe0' : '#1a9c5c');
}

function bulle(l) {
  const depasse = (l.part ?? Infinity) > reglages.budget;
  const puces = [
    l.balcon === true && 'balcon', l.parking === true && 'parking',
    l.ascenseur === true && 'ascenseur', l.meuble && 'meublé',
    l.colocation && 'colocation',
  ].filter(Boolean);
  return `
    <div class="bulle-titre">${escape(l.titre)}</div>
    <div class="bulle-chiffres">
      <b>${eur(l.loyer)}</b> ·
      <span class="bulle-rac${depasse ? ' depasse' : ''}">${eur(l.part)} pour vous</span>
      ${l.surface ? ` · ${Math.round(l.surface)} m²` : ''}${l.eur_m2 ? ` · ${l.eur_m2} €/m²` : ''}
    </div>
    <div class="bulle-lieu">${escape([l.ville, l.quartier, l.code_postal].filter(Boolean).join(' · '))}</div>
    ${puces.length ? `<div class="bulle-puces">${puces.map(p => `<span>${p}</span>`).join('')}</div>` : ''}
    ${l.url ? `<a href="${escape(l.url)}" target="_blank" rel="noopener">Voir l'annonce ↗</a>` : ''}`;
}

function rendreCarte(liste) {
  if (!carteLeaflet) {
    // preferCanvas : plusieurs centaines de marqueurs restent fluides
    carteLeaflet = L.map('carte', { preferCanvas: true }).setView([50.6326, 5.5797], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(carteLeaflet);
  }
  if (coucheMarqueurs) coucheMarqueurs.remove();

  const situees = liste.filter(l => l.lat != null && l.lon != null);
  coucheMarqueurs = L.layerGroup(situees.map(l =>
    L.circleMarker([l.lat, l.lon], {
      radius: 5 + Math.min(5, (l.score ?? 0) / 20),
      color: '#fff', weight: 1.5, opacity: .85,
      fillColor: couleur(l), fillOpacity: .85,
    }).bindPopup(bulle(l), { maxWidth: 300 }))).addTo(carteLeaflet);

  const manquantes = liste.length - situees.length;
  $('#hors-carte').textContent = manquantes ? `${manquantes} sans position` : '';
  if (situees.length) {
    carteLeaflet.fitBounds(L.latLngBounds(situees.map(l => [l.lat, l.lon])).pad(0.06));
  }
  // Le conteneur était masqué à l'initialisation : sans invalidateSize,
  // Leaflet calcule des dimensions nulles et n'affiche aucune tuile.
  setTimeout(() => carteLeaflet.invalidateSize(), 0);
}

function basculerVue(cible, majHash = true) {
  vue = cible;
  const c = cible === 'carte';
  if (majHash) history.replaceState(null, '', c ? '#carte' : '#liste');
  $('#grille').hidden = c;
  $('#bloc-carte').hidden = !c;
  $('#vue-liste').classList.toggle('active', !c);
  $('#vue-carte').classList.toggle('active', c);
  $('#vue-liste').setAttribute('aria-pressed', String(!c));
  $('#vue-carte').setAttribute('aria-pressed', String(c));
  rendre();
}

/* ---------- interactions ---------- */
function brancherEvenements() {
  const horsVues = (fn) => (e) => { if (!e.target.closest('.vues')) fn(); };
  $('#filtres').addEventListener('input', horsVues(rendre));
  $('#filtres').addEventListener('change', horsVues(rendre));
  $('#vue-liste').addEventListener('click', () => basculerVue('liste'));
  $('#vue-carte').addEventListener('click', () => basculerVue('carte'));

  $('#reglages').addEventListener('input', lireReglagesDepuisFormulaire);
  $('#reglages').addEventListener('change', lireReglagesDepuisFormulaire);
  $('#ouvrir-reglages').addEventListener('click', () => { $('#reglages').hidden = false; });
  $('#fermer-reglages').addEventListener('click', () => { $('#reglages').hidden = true; });
  $('#reset-reglages').addEventListener('click', () => {
    reglages = { ...DEFAUTS };
    ecrire(CLE_REGLAGES, reglages);
    appliquerReglagesAuFormulaire();
    reevaluer(); rendreBudget(); rendre();
  });

  $('#reset').addEventListener('click', () => {
    $('#filtres').querySelectorAll('input').forEach(i => {
      if (i.type === 'checkbox') i.checked = (i.id === 'f-masquer-refus');
      else i.value = '';
    });
    $('#filtres').querySelectorAll('select').forEach(s => s.selectedIndex = 0);
    rendre();
  });

  $('#export').addEventListener('click', () => {
    const cols = ['score', 'titre', 'loyer', 'part', 'surface', 'eur_m2', 'chambres',
                  'ville', 'quartier', 'code_postal', 'balcon', 'parking', 'ascenseur', 'url'];
    const csv = [cols.join(';'), ...filtrer().map(l =>
      cols.map(k => `"${String(l[k] ?? '').replace(/"/g, '""')}"`).join(';'))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `apparts-liege-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  });
}

function escape(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

init();
