# PrediCare TPA — Architecture des écrans et spécifications UI/UX

> **Objet** : spécification de référence pour l'interface des quatre rôles du
> CDC, écrite pour être implémentée directement dans `apps/web`.
>
> **Date** : 20/10/2026 · **Version** : 1
>
> **Périmètre** : `apps/web` uniquement (React 18 + TypeScript + Vite). Aucune
> dépendance externe n'est ajoutée : la CSP de la passerelle interdit tout
> chargement depuis un domaine tiers, donc ni police, ni icône, ni librairie
> de graphiques distants.
>
> **Ce document ne décrit pas une refonte de cero** : il spécifie l'état
> cible à partir de ce qui existe déjà, écran par écran.

---

## 0. État des lieux : ce que le code contient déjà

| Route | Écran existant | Composants réels | Points faibles à traiter |
| --- | --- | --- | --- |
| `/connexion` | `LoginPage` | hero, formulaire, comptes de démo | pas d'état « mot de passe oublié », pas de spinner sur le submit |
| `/` | `HomePage` | hero, 2 cartes | page vide de contenu, sert de redirect |
| `/assure` | `AssurePage` | 2 onglets (remboursements, assistant) | pas de graphe, pas de synthèse, chat sans sources visibles |
| `/professionnel` | `ProPage` | 4 onglets (dépôt, lot, suivi, ordonnance) | pas de KPI, pas de tri de tableau, pagination par bouton |
| `/gestionnaire` | `ManagerPage` | file + détail SHAP + décision | liste non priorisée, pas de raccourcis, pas de « transferer » |
| `/administration` | `AdminPage` | 7 onglets | onglets larges, observabilité sans sparkline |
| `/compte` | `AccountPage` | formulaire mot de passe | — |

Briques réutilisables déjà présentes : `Carte`, `Badge`, `Champ`, `Erreur`,
`Succes`, `Vide`, `Chargement`, `ShapList`, `SchemaProjet`, `Guards`, `Shell`.

**Ce document ajoute** : un socle de tokens, une navigation latérale, une
bibliothèque de composants métier (KPI, tableau, waterfall SHAP, drawer,
timeline), et quatre tableaux de bord.

---

## 1. Fondations visuelles

### 1.1 Décision structurante : Tailwind ou pas ?

Le brief suggère Tailwind. **Recommandation : ne pas l'introduire maintenant.**

Motifs :
- le projet n'a qu'une feuille de style (`styles.css`, ~1 000 lignes) avec un
  système de variables CSS déjà cohérent ; Tailwind imposerait un build
  supplémentaire, une dépendance, et une réécriture des 7 écrans ;
- la CSP interdit les CDN, mais Tailwind se builderait localement — le
  risque est donc ailleurs : le temps, à quelques jours de la soutenance ;
- l Newtonsoft d'un framework ne se voit pas dans le rendu : c'est le
  **système de tokens** qui produit l'identité visuelle.

Ce qui est réellement demandé — « Stripe / Linear / Datadog » — tient en
quatre points : une **palette sémantique** (pas des couleurs décoratives),
une **échelle typographique** courte, des **densités de tableau** tenues, et
un **usage parcimonieux** de la couleur (la couleur porte un sens, pas de la
décoration).

> Si Tailwind est imposé plus tard, les tokens ci-dessous se traduisent
> mécaniquement en thème Tailwind ; le plan de composants reste valide.

### 1.2 Palette : table de correspondance

La palette existante est **teal**. La palette demandée est **bleu
institutionnel**. Le bleu est la recommandation (registre assurance,
conforme au CDC « institutionnel de confiance »), mais le changement est
localisé à huit lignes de CSS.

| Rôle | Actuel | Cible | Usage |
| --- | --- | --- | --- |
| Encre / fond de page | `#0e1a27` | `#0f172a` (slate 900) | titres, texte principal |
| Texte secondaire | `#5b6776` | `#475569` (slate 600) | labels, aides |
| Bordure | `#dde3eb` | `#e2e8f0` (slate 200) | séparateurs, contours |
| Surface | `#ffffff` | `#ffffff` | cartes |
| Fond de page | `#f0f4f8` | `#f8fafc` (slate 50) | arrière-plan applicatif |
| **Primaire** | `#0f766e` (teal) | **`#2563eb`** (blue 600) | actions, liens, focus |
| Primaire foncé | `#0b5c56` | `#1d4ed8` (blue 700) | survol |
| Primaire clair | `#e6f4f2` | `#eff6ff` (blue 50) | fonds selected, badges info |
| **Alerte / fraude** | `#b42318` | **`#dc2626`** (red 600) | score élevé, rejet |
| Alerte claire | `#fee4e2` | `#fef2f2` (red 50) | fonds de badge |
| **Succès / validé** | `#067647` | **`#059669`** (emerald 600) | remboursement validé |
| Succès clair | `#dcfae6` | `#ecfdf5` (emerald 50) | fonds de badge |
| Avertissement | *(absent)* | **`#d97706`** (amber 600) | dossier en attente, seuil proche |
| Avertissement clair | — | `#fffbeb` | fond de badge |

**Règle d'emploi de la couleur** (c'est ce qui fait « Datadog » plutôt que
« arc-en-ciel ») :

- le **rouge** est réservé au risque avéré (score au-dessus du seuil, fraude
  confirmée, rejet) ;
- l'**ambre** est réservé à l'attente et au doute (dossier en cours, seuil
  approché, dérive moyenne) ;
- le **vert** est réservé à l'argent confirmé et à l'état sain ;
- le **bleu** est réservé à la navigation et aux actions, jamais à un état
  métier ;
- une ligne de tableau ne porte **qu'une** pastille de statut, jamais trois.

### 1.3 Fichier de tokens

`apps/web/src/styles.css`, bloc `:root` — à remplacer par :

```css
:root {
  /* --- Surfaces ------------------------------------------------------ */
  --fond: #f8fafc;
  --fond-degrade: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
  --surface: #ffffff;
  --surface-2: #f8fafc;          /* en-têtes de tableau, lignes alternées */
  --surface-3: #f1f5f9;          /* survol de ligne, fonds de contrôle */

  /* --- Encre --------------------------------------------------------- */
  --encre: #0f172a;              /* slate 900 */
  --encre-douce: #475569;        /* slate 600 */
  --encre-faible: #94a3b8;       /* slate 400, métadonnées */

  /* --- Traits -------------------------------------------------------- */
  --bord: #e2e8f0;               /* slate 200 */
  --bord-fonce: #cbd5e1;         /* slate 300 */
  --focus: #2563eb;              /* anneau de focus, 2 px + offset */

  /* --- Sémantique ---------------------------------------------------- */
  --primaire: #2563eb;
  --primaire-fonce: #1d4ed8;
  --primaire-clair: #eff6ff;
  --alerte: #dc2626;
  --alerte-fonce: #b91c1c;
  --alerte-clair: #fef2f2;
  --ok: #059669;
  --ok-fonce: #047857;
  --ok-clair: #ecfdf5;
  --avert: #d97706;
  --avert-fonce: #b45309;
  --avert-clair: #fffbeb;
  --info: #2563eb;
  --info-clair: #eff6ff;

  /* --- Forme --------------------------------------------------------- */
  --rayon: 10px;                 /* cartes, contrôles */
  --rayon-sm: 6px;               /* badges, pastilles */
  --rayon-lg: 14px;              /* modales, drawers */
  --ombre-1: 0 1px 2px rgba(15, 23, 42, .06);
  --ombre-2: 0 1px 3px rgba(15, 23, 42, .08), 0 8px 24px rgba(15, 23, 42, .06);
  --ombre-3: 0 12px 48px rgba(15, 23, 42, .18);

  /* --- Rythme -------------------------------------------------------- */
  --espace-1: 4px;
  --espace-2: 8px;
  --espace-3: 12px;
  --espace-4: 16px;
  --espace-5: 24px;
  --espace-6: 32px;
  --espace-7: 48px;

  /* --- Typographie --------------------------------------------------- */
  --police: "Inter var", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
  --police-mono: "Cascadia Mono", ui-monospace, "SF Mono", Consolas, monospace;
  --taille-xs: 0.75rem;   /* 12 px — métadonnées */
  --taille-sm: 0.8125rem; /* 13 px — libellés de tableau */
  --taille-base: 0.875rem;/* 14 px — corps de tableau */
  --taille-md: 0.9375rem;/* 15 px — corps de texte */
  --taille-lg: 1.125rem;  /* 18 px — titre de carte */
  --taille-xl: 1.375rem;  /* 22 px — titre de page */
  --taille-2xl: 1.75rem;  /* 28 px — chiffre de KPI */
  --interligne: 1.5;
  --interligne-dense: 1.35;

  --transition: 140ms cubic-bezier(.4, 0, .2, 1);
  --focus-anneau: 0 0 0 2px var(--surface), 0 0 0 4px var(--focus);
}
```

> `Inter` n'est pas chargée depuis un CDN : soit la police système est
> conservée, soit un `.woff2` est versionné dans `apps/web/public/polices/`
> et déclaré en `@font-face` local. La CSP (`font-src 'self'`) l'autorise.

### 1.4 Mode sombre

Le mode sombre ne demande **aucun composant supplémentaire** : il suffit de
redéclarer les tokens sous `[data-theme="dark"]`. Il est à n'activer qu'après
le reste.

```css
[data-theme='dark'] {
  --fond: #0b1220;
  --fond-degrade: linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
  --surface: #111c31;
  --surface-2: #16223a;
  --surface-3: #1e2b45;
  --encre: #e2e8f0;
  --encre-douce: #94a3b8;
  --encre-faible: #64748b;
  --bord: #22304d;
  --bord-fonce: #334155;
  --primaire-clair: #14264d;
  --alerte-clair: #3b1418;
  --ok-clair: #0c2a22;
  --avert-clair: #33240b;
  --info-clair: #14264d;
}
```

### 1.5 Icônes — registre SVG inline

Aucune fonte d'icônes (CSP). Un registre de tracés SVG, 20 px, `stroke`
heritée de la couleur du texte :

```tsx
// apps/web/src/components/Icone.tsx
import type { SVGProps } from 'react'

/**
 * Tracés d'icônes en SVG inline.
 *
 * Aucune police d'icônes n'est chargée : la CSP de la passerelle
 * (`font-src 'self'`) l'interdirait, et une police rasterisée n'est pas
 * accessible au lecteur d'écran. Chaque icône est donc un `path` dont le
 * nom est decoratif (`aria-hidden`) ou porteur de sens (via un `title`).
 */
const TRACES: Record<string, string> = {
  depot: 'M4 16V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8M4 16h16M9 16V6h6v10M2 16h20v3H2z',
  alerte: 'M12 3 2 20h20L12 3zm0 6v6m0 3h.01',
  facture: 'M6 2h9l5 5v15H6zM15 2v5h5M9 12h6M9 16h6',
  assure: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-8 9a8 8 0 0 1 16 0',
  reglages: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm8-3a8 8 0 0 0-.2-1.7l2-1.5-2-3.4-2.4 1a8 8 0 0 0-3-1.7L14 1h-4l-.4 2.7a8 8 0 0 0-3 1.7l-2.4-1-2 3.4 2 1.5a8.2 8.2 0 0 0 0 3.4l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 3 1.7L10 23h4l.4-2.7a8 8 0 0 0 3-1.7l2.4 1 2-3.4-2-1.5c.13-.55.2-1.12.2-1.7z',
  tableau: 'M3 4h18v16H3zM3 9h18M9 9v11',
  chat: 'M4 5h16v11H9l-5 4z',
  bi: 'M4 20V10m5 10V4m5 16v-7m5 7V8',
  historique: 'M12 8v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4',
}

export function Icone({
  nom,
  taille = 18,
  ...props
}: { nom: keyof typeof TRACES | string; taille?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={taille}
      height={taille}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <path d={TRACES[nom] ?? TRACES.facture} />
    </svg>
  )
}
```

### 1.6 Graphiques — SVG inline, sans librairie

Un composant unique, `Graphique`, rend une série de barres ou une courbe.
Aucune dépendance : c'est 60 lignes de SVG et cela passe la CSP.

```tsx
// apps/web/src/components/Graphique.tsx
interface Point {
  etiquette: string
  valeur: number
}

/**
 * Histogramme simple, en SVG inline.
 *
 * Pas de librairie de graphiques : la CSP de la passerelle interdit tout
 * chargement distant, et un bundle de 200 ko pour quatre barres ne se
 * justifie pas. Le SVG est aussi plus accessible : chaque barre porte son
 * étiquette dans le DOM.
 */
export function Barres({
  donnees,
  hauteur = 120,
  format = (v) => String(v),
}: {
  donnees: Point[]
  hauteur?: number
  format?: (valeur: number) => string
}) {
  const maximum = Math.max(...donnees.map((point) => point.valeur), 1)
  return (
    <ul className="barres" style={{ ['--hauteur' as string]: `${hauteur}px` }}>
      {donnees.map((point) => (
        <li key={point.etiquette}>
          <span className="barres-valeur">{format(point.valeur)}</span>
          <span
            className="barres-piste"
            role="img"
            aria-label={`${point.etiquette} : ${format(point.valeur)}`}
          >
            <span
              className="barres-remplissage"
              style={{ height: `${(point.valeur / maximum) * 100}%` }}
            />
          </span>
          <span className="barres-etiquette">{point.etiquette}</span>
        </li>
      ))}
    </ul>
  )
}
```

---

## 2. Architecture de l'information

### 2.1 Navigation : de la barre haute à la barre latérale

L'état actuel est une barre de navigation horizontale (`.nav`). Pour quatre
rôles dont deux manipulateurs de tableaux denses (gestionnaire,
administrateur), la barre horizontale ne tient pas : elle oblige à un
défilement et n'héberge pas les actions contextuelles.

**Cible : barre latérale à gauche (240 px, repliable à 64 px) + barre de
contexte en haut.**

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  BARRE DE CONTEXTE (56 px)                                                  │
│  ● PrediCare TPA   ›  File d'alertes        [Rechercher… ⌘K]   [RAV] [Avatar]│
├────────────────┬─────────────────────────────────────────────────────────────┤
│  SIDEBAR       │  ZONE DE CONTENU                                         │
│  (240 px)      │                                                             │
│                │  ┌───────────────────────────────────────────────────────┐  │
│  ▸ Vue d'ensemble│  │  Titre de page                    [Actions] [ ⋯ ]   │  │
│  ▸ File        │  ├───────────────────────────────────────────────────────┤  │
│  ▸ Historique  │  │                                                        │  │
│  ▸ …           │  │  Contenu                                              │  │
│                │  │                                                        │  │
│  ───────────   │  └───────────────────────────────────────────────────────┘  │
│  Mon compte    │                                                             │
└────────────────┴─────────────────────────────────────────────────────────────┘
```

`Shell.tsx` devient :

```tsx
// apps/web/src/components/Shell.tsx  (extrait)
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Icone } from './Icone'

interface Espace {
  chemin: string
  libelle: string
  icone: string
  roles: Role[]
}

/** Espaces visibles par rôle. Le premier est la page d'accueil du rôle. */
const ESPACES: Espace[] = [
  { chemin: '/assure', libelle: 'Mes remboursements', icone: 'assure', roles: ['assure'] },
  { chemin: '/professionnel', libelle: 'Depot', icone: 'depot', roles: ['professionnel_sante'] },
  { chemin: '/gestionnaire', libelle: 'Alertes', icone: 'alerte', roles: ['gestionnaire'] },
  { chemin: '/administration', libelle: 'Pilotage', icone: 'bi', roles: ['administrateur'] },
  { chemin: '/compte', libelle: 'Mon compte', icone: 'reglages', roles: [] }, // visible de tous
]

export function Shell() {
  const { profile, deconnexion } = useAuth()
  const navigate = useNavigate()
  if (profile === null) return null

  const visibles = ESPACES.filter((espace) =>
    espace.roles.length === 0 ? true : peut(profile, ...espace.roles),
  )

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Navigation principale">
        <NavLink to="/" className="marque">
          <span className="marque-point" aria-hidden="true" />
          PrediCare
        </NavLink>
        <nav className="sidebar-nav">
          {visibles.map((espace) => (
            <NavLink
              key={espace.chemin}
              to={espace.chemin}
              className={({ isActive }) => (isActive ? 'sidebar-lien actif' : 'sidebar-lien')}
            >
              <Icone nom={espace.icone} />
              <span>{espace.libelle}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-pied">
          <button type="button" className="sidebar-lien" onClick={deconnexion}>
            <Icone nom="historique" />
            <span>Se deconnecter</span>
          </button>
        </div>
      </aside>

      <div className="app-corps">
        <header className="barre-contexte">
          <span className="fil-ariane">PrediCare / {ROLE_LABELS[profile.role]}</span>
          <div className="utilisateur">
            <span className="badge info">{ROLE_LABELS[profile.role]}</span>
            <span className="utilisateur-nom">{profile.display_name ?? profile.subject}</span>
          </div>
        </header>
        <main className="contenu" id="contenu">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
```

CSS associé (à ajouter) :

```css
.app { display: grid; grid-template-columns: 240px 1fr; min-height: 100vh; }
.app-corps { display: flex; flex-direction: column; min-width: 0; }
.sidebar {
  background: var(--surface); border-right: 1px solid var(--bord);
  display: flex; flex-direction: column; padding: var(--espace-4) var(--espace-3); gap: var(--espace-5);
  position: sticky; top: 0; height: 100vh;
}
.sidebar-nav { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.sidebar-lien {
  align-items: center; background: none; border: 0; border-radius: var(--rayon-sm);
  color: var(--encre-douce); display: flex; gap: var(--espace-3);
  font: inherit; padding: 9px var(--espace-3); text-align: left; width: 100%;
  text-decoration: none; cursor: pointer;
}
.sidebar-lien:hover { background: var(--surface-3); color: var(--encre); }
.sidebar-lien.actif { background: var(--primaire-clair); color: var(--primaire-fonce); font-weight: 600; }
.sidebar-lien:focus-visible { outline: none; box-shadow: var(--focus-anneau); }
.barre-contexte {
  align-items: center; background: var(--surface); border-bottom: 1px solid var(--bord);
  display: flex; height: 56px; justify-content: space-between; padding: 0 var(--espace-5);
  position: sticky; top: 0; z-index: 20;
}
.contenu { padding: var(--espace-6); max-width: 1440px; width: 100%; }

@media (max-width: 900px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { flex-direction: row; height: auto; position: static; overflow-x: auto; }
  .sidebar-nav { flex-direction: row; }
  .sidebar-lien span { display: none; }
}
```

### 2.2 Carte de navigation par rôle

| Rôle | Navigation latérale | Page d'accueil |
| --- | --- | --- |
| Assuré | Mes remboursements · Assistant · Mon compte | `/assure` |
| Professionnel | Vue d'ensemble · Dépôt de facture · Suivi · Ordonnances · Mon compte | `/professionnel` |
| Gestionnaire | Centre d'alertes · Historique · Mon compte | `/gestionnaire` |
| Administrateur | Pilotage BI · Supervision · Configuration · Journal · Comptes · Mon compte | `/administration` |

Le changement de route d'accueil par rôle se fait par `ACCUEIL[role]`
(déjà présent dans `api/types.ts`).

### 2.3 États transverses

Trois états doivent exister pour **tout** bloc de données, sans exception.
C'est la règle qui fait la différence entre une démo et un produit.

| État | Rendu | Composant |
| --- | --- | --- |
| Chargement | squelette à la place du contenu, **jamais** un texte « Chargement... » | `<Squelette />` |
| Vide | illustration + explication + action possible | `<EtatVide />` |
| Erreur | message métier + action « Réessayer » | `<ErreurBloc />` |

```tsx
// apps/web/src/components/ui.tsx  (ajouts)
/** Squelette de chargement : occupe la place du contenu à venir. */
export function Squelette({ lignes = 3, hauteur = 20 }: { lignes?: number; hauteur?: number }) {
  return (
    <div className="squelette" aria-hidden="true">
      {Array.from({ length: lignes }, (_, index) => (
        <span key={index} className="squelette-barre" style={{ height: `${hauteur}px` }} />
      ))}
      <span className="visuellement-cache">Chargement en cours…</span>
    </div>
  )
}

/** État vide : jamais un simple tiret, toujours une explication + une action. */
export function EtatVide({
  titre,
  texte,
  action,
}: {
  titre: string
  texte: string
  action?: ReactNode
}) {
  return (
    <div className="etat-vide">
      <p className="etat-vide-titre">{titre}</p>
      <p className="etat-vide-texte">{texte}</p>
      {action}
    </div>
  )
}
```

---

## 3. Composants métier à créer

| Composant | Rôle | Remplace / complète |
| --- | --- | --- |
| `Kpi` | tuile de chiffre-clé | nouveau |
| `Pastille` (statut métier) | badge normalisé sur le statut métier | complète `Badge` |
| `Tableau` | tableau dense, trié, filtrable, paginé | nouveau |
| `Waterfall` | explicabilité SHAP en cascade | remplace `ShapList` |
| `Tiroir` (drawer) | panneau latéral (chat, détail) | nouveau |
| `Chronologie` | journal d'audit / historique | nouveau |
| `Pagination` | pagination serveur | nouveau |
| `Infobulle` | aide contextuelle | nouveau |
| `Bandeau` (toast) | retour d'action non bloquant | nouveau |

### 3.1 `Kpi` — la tuile de chiffre

```tsx
// apps/web/src/components/Kpi.tsx
import type { ReactNode } from 'react'
import { Icone } from './Icone'

export type TonKpi = 'neutre' | 'ok' | 'alerte' | 'avert' | 'info'

/**
 * Tuile d'indicateur clé.
 *
 * Un KPI n'est pas décoratif : il porte un TITRE, une VALEUR, une
 * COMPARAISON (variation ou contexte) et une SPARKLINE. Sans la
 * comparaison, un chiffre isolé n'apprend rien : « 84 632 factures » ne
 * dit pas si c'est bon ou mauvais.
 */
export function Kpi({
  titre,
  valeur,
  unite,
  contexte,
  ton = 'neutre',
  icone,
  serie,
  onClick,
}: {
  titre: string
  valeur: string | number
  unite?: string
  contexte?: ReactNode
  ton?: TonKpi
  icone?: string
  serie?: number[]
  onClick?: () => void
}) {
  const Balise = onClick ? 'button' : 'div'
  return (
    <Balise className={`kpi kpi-${ton}`} onClick={onClick} type={onClick ? 'button' : undefined}>
      <span className="kpi-tete">
        <span className="kpi-libelle">{titre}</span>
        {icone !== undefined && <Icone nom={icone} taille={16} />}
      </span>
      <span className="kpi-valeur">
        {valeur}
        {unite !== undefined && <span className="kpi-unite">{unite}</span>}
      </span>
      {serie !== undefined && serie.length > 1 && <Sparkline valeurs={serie} ton={ton} />}
      {contexte !== undefined && <span className="kpi-contexte">{contexte}</span>}
    </Balise>
  )
}

/** Micro-courbe d'évolution, en SVG inline (8 points suffisent à une tendance). */
function Sparkline({ valeurs, ton }: { valeurs: number[]; ton: TonKpi }) {
  const max = Math.max(...valeurs)
  const min = Math.min(...valeurs)
  const etendue = max - min || 1
  const points = valeurs
    .map((valeur, index) => {
      const x = (index / (valeurs.length - 1)) * 100
      const y = 28 - ((valeur - min) / etendue) * 24
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
  return (
    <svg className="sparkline" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" strokeWidth="2" strokeLinecap="round" />
      <style>{`.sparkline polyline { stroke: var(--${ton === 'neutre' ? 'primaire' : ton}); }`}</style>
    </svg>
  )
}
```

### 3.2 `Pastille` — badge métier normalisé

Les statuts viennent de trois mondes différents (`PAYEE`, `recue`,
`fraude_confirmee`). Le front doit les **unifier** en six tons.

```tsx
// apps/web/src/components/Pastille.tsx
import { Badge } from './ui'

/**
 * Statut métier normalisé.
 *
 * La base porte des statuts heterogenes (`PAYEE` vient du seed, `recue`
 * vient du front, `fraude_confirmee` vient de la decision du gestionnaire).
 * L'utilisateur, lui, ne veut voir que six etats. Cette table est le
 * SEUL endroit du front qui connait la correspondance.
 */
const ETATS: Record<string, { libelle: string; ton: 'neutre' | 'ok' | 'alerte' | 'avert' | 'info' }> = {
  payee: { libelle: 'Remboursé', ton: 'ok' },
  en_cours: { libelle: 'En cours', ton: 'avert' },
  recue: { libelle: 'Reçue', ton: 'info' },
  rejetee: { libelle: 'Rejetée', ton: 'alerte' },
  fraude_confirmee: { libelle: 'Fraude confirmée', ton: 'alerte' },
  piece_demandee: { libelle: 'Pièce demandée', ton: 'avert' },
}

export function Pastille({ statut }: { statut: string }) {
  const etat = ETATS[statut.trim().toLowerCase()]
  if (etat === undefined) {
    return <Badge ton="neutre">{statut || '—'}</Badge>
  }
  return <Badge ton={etat.ton}>{etat.libelle}</Badge>
}
```

> Ce composant remplace les deux tables locales `STATUTS` d'`AssurePage` et
> `libelleStatut` : une seule source de vérité.

### 3.3 `Waterfall` — explicabilité SHAP

Le `ShapList` actuel est une liste de barres divergentes. Pour un
gestionnaire, la lecture attendue est : **« cette facture a été signalée
parce que le montant unitaire était 8× la moyenne, +0.31 de score »**.

```tsx
// apps/web/src/components/Waterfall.tsx
import type { ShapContribution } from '../api/types'

/**
 * Explicabilité en cascade : le score de base, puis la contribution de
 * chaque variable, puis le score final.
 *
 * Une barre divergente est plus lisible qu'un graphique en cascade
 * complexe, mais elle manque l'essentiel : le chemin qui va du score de
 * base au score obtenu. On montre donc les deux : la cascade en haut (le
 * raisonnement), la liste détaillée en dessous (les chiffres).
 */
export function Waterfall({
  score,
  seuil,
  contributions,
}: {
  score: number
  seuil: number
  contributions: ShapContribution[]
}) {
  const base = contributions.reduce((somme, c) => somme + c.base_value, 0)
  let courant = base
  const etapes = contributions.map((contribution) => {
    const debut = courant
    courant += contribution.shap_value
    return { debut, fin: courant, contribution }
  })

  return (
    <figure className="waterfall">
      <figcaption className="waterfall-legende">
        Score de base du modèle <strong>{base.toFixed(3)}</strong> → score_obtenu{' '}
        <strong>{score.toFixed(3)}</strong> (seuil {seuil.toFixed(3)})
      </figcaption>
      <ol className="waterfall-pas">
        {etapes.map(({ debut, fin, contribution }) => (
          <li
            key={contribution.feature}
            className={contribution.shap_value >= 0 ? 'pousse_vers_fraude' : 'pousse_vers_legitime'}
          >
            <span className="waterfall-libelle">{contribution.human_readable}</span>
            <span className="waterfall-bloc" aria-hidden="true">
              <span
                className="waterfall-rect"
                style={{
                  left: `${Math.min(debut, fin) * 100}%`,
                  width: `${Math.abs(fin - debut) * 100}%`,
                }}
              />
            </span>
            <span className="waterfall-valeur">
              {contribution.shap_value >= 0 ? '+' : ''}
              {contribution.shap_value.toFixed(3)}
            </span>
            <span className="waterfall-valeur-brute">
              {contribution.value} → {contribution.base_value.toFixed(2)}
            </span>
          </li>
        ))}
      </ol>
    </figure>
  )
}
```

### 3.4 `Tiroir` — panneau latéral (chat assistant, détail d'alerte)

```tsx
// apps/web/src/components/Tiroir.tsx
import { useEffect, useRef, type ReactNode } from 'react'

/**
 * Panneau latéral ancré à droite.
 *
 * Sert au chat de l'assistant et au détail d'une alerte. Deux exigences :
 * le focus doit y entrer à l'ouverture et y revenir à la fermeture
 * (WCAG 2.1), et `Échap` doit refermer (comportement attendu partout).
 */
export function Tiroir({
  ouvert,
  titre,
  sousTitre,
  onFermer,
  children,
  pied,
}: {
  ouvert: boolean
  titre: string
  sousTitre?: string
  onFermer: () => void
  children: ReactNode
  pied?: ReactNode
}) {
  const panneau = useRef<HTMLDivElement>(null)
  const declencheur = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!ouvert) return
    declencheur.current = document.activeElement as HTMLElement
    panneau.current?.focus()
    const surTouche = (evenement: KeyboardEvent) => {
      if (evenement.key === 'Escape') onFermer()
    }
    document.addEventListener('keydown', surTouche)
    return () => {
      document.removeEventListener('keydown', surTouche)
      declencheur.current?.focus()
    }
  }, [ouvert, onFermer])

  if (!ouvert) return null

  return (
    <div className="tiroir-fond" onClick={onFermer} aria-hidden="true" />
    <div
      ref={panneau}
      className="tiroir"
      role="dialog"
      aria-modal="true"
      aria-label={titre}
      tabIndex={-1}
    >
      <header className="tiroir-tete">
        <div>
          <h2 className="tiroir-titre">{titre}</h2>
          {sousTitre !== undefined && <p className="tiroir-sous-titre">{sousTitre}</p>}
        </div>
        <button type="button" className="bouton discret" onClick={onFermer} aria-label="Fermer">
          ✕
        </button>
      </header>
      <div className="tiroir-corps">{children}</div>
      {pied !== undefined && <footer className="tiroir-pied">{pied}</footer>}
    </div>
  )
}
```

### 3.5 `Pagination` et `Tableau`

```tsx
// apps/web/src/components/Pagination.tsx
export function Pagination({
  total,
  offset,
  limite,
  onChange,
}: {
  total: number
  offset: number
  limite: number
  onChange: (offset: number) => void
}) {
  const page = Math.floor(offset / limite) + 1
  const pages = Math.max(1, Math.ceil(total / limite))
  if (total <= limite) return null
  return (
    <nav className="pagination" aria-label="Pagination">
      <button
        type="button"
        className="bouton discret"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limite))}
      >
        ‹ Précédent
      </button>
      <span className="pagination-etat">
        Page <strong>{page}</strong> sur {pages} · {total} éléments
      </span>
      <button
        type="button"
        className="bouton discret"
        disabled={offset + limite >= total}
        onClick={() => onChange(offset + limite)}
      >
        Suivant ›
      </button>
    </nav>
  )
}
```

Le tableau dense (lisibleur d'un gestionnaire : 100 lignes d'alertes) impose
**une ligne par 32 px**, des cellules numériques alignées à droite, et un
tri par colonne.

```tsx
// apps/web/src/components/Tableau.tsx
import type { ReactNode } from 'react'

export interface Colonne<T> {
  cle: string
  titre: string
  alignement?: 'gauche' | 'droite' | 'centre'
  triable?: boolean
  rendu: (ligne: T) => ReactNode
  valeurTri?: (ligne: T) => string | number
}

export function Tableau<T extends { id: string }>({
  colonnes,
  lignes,
  onLigneClick,
  ligneActive,
  tri,
  onTri,
}: {
  colonnes: Colonne<T>[]
  lignes: T[]
  onLigneClick?: (ligne: T) => void
  ligneActive?: string
  tri?: { cle: string; sens: 'asc' | 'desc' }
  onTri?: (cle: string) => void
}) {
  return (
    <div className="table-enveloppe">
      <table className="table table-dense">
        <thead>
          <tr>
            {colonnes.map((colonne) => (
              <th
                key={colonne.cle}
                scope="col"
                className={colonne.alignement === 'droite' ? 'droite' : undefined}
                aria-sort={
                  tri?.cle === colonne.cle
                    ? tri.sens === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : undefined
                }
              >
                {colonne.triable === true ? (
                  <button type="button" className="tri-bouton" onClick={() => onTri?.(colonne.cle)}>
                    {colonne.titre}
                    {tri?.cle === colonne.cle && <span aria-hidden="true">{tri.sens === 'asc' ? ' ▲' : ' ▼'}</span>}
                  </button>
                ) : (
                  colonne.titre
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lignes.map((ligne) => (
            <tr
              key={ligne.id}
              className={ligneActive === ligne.id ? 'ligne-active' : undefined}
              onClick={onLigneClick ? () => onLigneClick(ligne) : undefined}
              tabIndex={onLigneClick ? 0 : undefined}
              onKeyDown={
                onLigneClick
                  ? (evenement) => {
                      if (evenement.key === 'Enter' || evenement.key === ' ') {
                        evenement.preventDefault()
                        onLigneClick(ligne)
                      }
                    }
                  : undefined
              }
            >
              {colonnes.map((colonne) => (
                <td key={colonne.cle} className={colonne.alignement === 'droite' ? 'droite' : undefined}>
                  {colonne.rendu(ligne)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

CSS de densité (à ajouter) :

```css
.table-dense th, .table-dense td { padding: 7px var(--espace-3); font-size: var(--taille-base); }
.table-dense tbody tr { cursor: pointer; }
.table-dense tbody tr:hover { background: var(--surface-2); }
.table-dense tbody tr.ligne-active { background: var(--primaire-clair); }
.table-dense td.droite, .table-dense th.droite { font-variant-numeric: tabular-nums; }
.tri-bouton { background: none; border: 0; color: inherit; cursor: pointer; font: inherit; padding: 0; }
.tri-bouton:focus-visible { outline: none; box-shadow: var(--focus-anneau); border-radius: 3px; }
```

---

## 4. Rôle A — Professionnel de santé

**Objectif** : déposer vite, savoir où en est chaque dossier, comprendre un
rejet.

### 4.1 Arborescence

```
/professionnel
├── Vue d'ensemble            (nouveau)  → KPI + 5 dernières actions
├── Dépôt de facture          (existant) → formulaire + résultat SHAP
├── Suivi des dossiers        (existant) → tableau filtrable + pagination
└── Ordonnances               (existant) → formulaire ordonnance
```

### 4.2 Wireframe — Vue d'ensemble

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Vue d'ensemble                                  [Déposer une facture]     │
├────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ 12           │ │  87 %        │ │ 4 250 000 Ar │ │ 3           │        │
│  │ FACTURES     │ │ TAUX DE      │ │ EN ATTENTE   │ │ REJETÉES     │        │
│  │ ce mois      │ │ VALIDATION   │ │ de paiement  │ │ ce mois      │        │
│  │ ▲ +4 vs mai  │ │ ▲ +2 pts     │ │ 6 dossiers   │ │ motif affiché│        │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘        │
├────────────────────────────────────────────────────────────────────────────┤
│  Activité récente                                                          │
│  15/10  12:04  FAC-91842FD227AF  2 500 000 Ar   ● Fraude confirmée          │
│  15/10  11:58  FAC-77BD1EAF5A1E    200 000 Ar   ● En cours                  │
│  14/10  09:12  FAC-54FD71E049E7    20 000 Ar   ● Remboursé                 │
├────────────────────────────────────────────────────────────────────────────┤
│  Dossiers à surveiller                    (3)                                │
│  → table : date, montant, statut, motif du rejet, action « corriger »      │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Interactions clés

| Interaction | Comportement attendu |
| --- | --- |
| **Clic sur une tuile KPI** | filtre la liste des dossiers (ex. tuile « Rejetées » → filtre `statut=rejetee`) — le KPI est une entrée, pas un décor |
| **Déposer une facture** | le bouton principal ouvre l'onglet Dépôt ; après envoi, un toast confirme et un lien « Voir le dossier » suit |
| **Rejet d'une facture** | le motif est affiché dans la liste, en texte court **et** copiable (« montant_total : 10 000 001 dépasse le plafond de 10 000 000 Ar ») |
| **Onglet Suivi** | tri par date par défaut, colonnes numériques alignées à droite, filtre statut, pagination serveur |
| **Perte de réseau** | l'état d'erreur propose « Réessayer » ; les valeurs déjà saisies ne sont pas perdues |
| **Double-clic sur une ligne du tableau** | ouvre le détail de la facture (aujourd'hui : le dépôt n'a pas d'écran de détail — c'est le manque principal) |

### 4.4 Contrats API nécessaires (à spécifier, non implémentés)

Les KPI ne peuvent pas être calculés par le front : la liste ne renvoie que
50 lignes et un `total`. Il faut un endpoint d'agrégat.

```http
GET /api/core/factures/statistiques?prestataire=PRE-00001
→ 200 {
    "factures_total": 701,
    "factures_mois": 12,
    "factures_mois_precedent": 8,
    "taux_validation": 0.87,
    "montant_attente": 4250000,
    "montant_rembourse": 12800000,
    "rejets": 3,
    "rejets_par_champ": { "montant_total": 2, "lignes.0.quantite": 1 },
    "serie_12_mois": [4, 7, 5, 9, 8, 11, 6, 10, 9, 12, 8, 12]
  }
```

### 4.5 Extrait de code — la vue d'ensemble

```tsx
// apps/web/src/pages/Professionnel/VueEnsemble.tsx
export function VueEnsemble() {
  const [stats, setStats] = useState<StatsProfessionnel | null>(null)
  const [filtre, setFiltre] = useState<string>('')

  useEffect(() => {
    api<StatsProfessionnel>('/api/core/factures/statistiques')
      .then(setStats)
      .catch((e: unknown) => setErreur(messageErreur(e)))
  }, [])

  if (stats === null) return <Squelette lignes={2} hauteur={92} />

  return (
    <div className="pile">
      <div className="grille quatre">
        <Kpi
          titre="Factures ce mois"
          valeur={stats.factures_mois}
          icone="facture"
          serie={stats.serie_12_mois}
          contexte={`▲ ${stats.factures_mois - stats.factures_mois_precedent} vs mois dernier`}
          onClick={() => setFiltre('')}
        />
        <Kpi
          titre="Taux de validation"
          valeur={pourcentage(stats.taux_validation)}
          ton={stats.taux_validation >= 0.8 ? 'ok' : 'avert'}
          contexte="Part des factures.remboursées"
        />
        <Kpi
          titre="En attente de paiement"
          valeur={montant(stats.montant_attente)}
          ton="avert"
          contexte="6 dossiers en cours"
          onClick={() => setFiltre('en_cours')}
        />
        <Kpi
          titre="Rejetées ce mois"
          valeur={stats.rejets}
          ton={stats.rejets > 0 ? 'alerte' : 'ok'}
          contexte="Motif affiché dans le suivi"
          onClick={() => setFiltre('rejetee')}
        />
      </div>
      {/* … activité récente + dossiers à surveiller */}
    </div>
  )
}
```

---

## 5. Rôle B — Assuré

**Objectif** : comprendre son argent et obtenir une réponse sourcée.

### 5.1 Arborescence

```
/assure
├── Mes remboursements   (existant, enrichi)  → KPI + graphe + liste
├── Assistant           (existant, enrichi)   → chat + sources
└── (drawer) Détail d'un remboursement      → ventilation des montants
```

### 5.2 Wireframe — Mes remboursements

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Mes remboursements                                    [Poser une question]│
├────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ 12 500 Ar    │ │ 31 000 Ar    │ │ 8 000 Ar     │ │ 4 250 000 Ar │        │
│  │ REMBOURSÉ   │ │ REMBOURSÉ   │ │ RESTE À CHARGE│ │ EN ATTENTE   │        │
│  │ 6 factures  │ │ 9 factures  │ │ ce mois     │ │ 2 dossiers   │        │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘        │
├────────────────────────────────────────────────────────────────────────────┤
│  Répartition sur 6 mois                                                  │
│  ▂▃▅▂▆▄  (barres : remboursé / reste à charge)                           │
├────────────────────────────────────────────────────────────────────────────┤
│  Date        Prestataire    Facture      Pris en charge   Reste   Statut     │
│  14/10/2026  PRE-00062     2 500 000    —                —       ● Fraude   │
│  12/10/2026  PRE-00001        20 000     16 000           4 000   ● Remb.    │
│  …                                                                         │
│                                          ‹ Précédent   Page 1 sur 3   ›    │
└────────────────────────────────────────────────────────────────────────────┘
```

**Point clé pour le jury** : la tuile « Reste à charge » est le chiffre que
l'assuré cherche et que l'interface ne montrait nulle part. Le détail
n'affichait que « Payée / En cours ».

### 5.3 Wireframe — L'assistant (drawer)

Décision : **le chat est un tiroir**, pas une page. L'assuré reste sur ses
remboursements pendant qu'il pose une question ; l'assistant occupe 420 px à
droite (pleine largeur en mobile). Cela évite de perdre le contexte — le
questionnement d'un remboursement « pourquoi il me reste 4 000 Ar ? » part
du tableau.

```
┌──────────────────────────────────────────────┬───────────────────────────────┐
│  MES REMBOURSEMENTS                          │  ASSISTANT PREDICARE        │
│                                              │  ┌─────────────────────────┐  │
│  Date    Facture    Pris en charge  Reste    │  │ ▸ Sources (3)  [ouvrir] │  │
│  12/10   20 000        16 000        4 000   │  └─────────────────────────┘  │
│                                              │                               │
│                                              │  Vous                         │
│                                              │  Pourquoi il me reste 4 000 ? │
│                                              │                               │
│                                              │  Assistant                    │
│                                              │  Sur la base du contrat CTR-… │
│                                              │  la participation est de 20 % │
│                                              │  du ticket.                   │
│                                              │                               │
│                                              │  [Source 1] Article 5.2 …     │
│                                              │  [Source 2] Article 7.1 …     │
│                                              │                               │
│                                              │  ▸ Traces de l'agent (2 outils)│
│                                              │                               │
│                                              │  [ poser une question…    ] ⏎│
└──────────────────────────────────────────────┴───────────────────────────────┘
```

### 5.4 Interactions clés

| Interaction | Comportement |
| --- | --- |
| **Poser une question** | l'interface est en « streaming » : la réponse s'écrit, les sources apparaissent sous forme d'extraits repliables avec le contrat, l'article et le score de similarité |
| **Cliquer une source** | ouvre le PDF du contrat à la bonne page (ancre `#page=12`) — sinon la citation n'est pas vérifiable |
| **Ouvre « Traces de l'agent »** | montre les outils appelés (`rechercher_contrats`, `consulter_historique_assure`), leur durée et leur résultat : c'est ce qui prouve le caractère agentique |
| **Assistant indisponible** | bandeau ambre explicite : « L'assistant n'est pas configuré (clé d'embedding ou de modèle manquante) » + ce qui fonctionne malgré tout (l'historique, les montants) — **ne jamais** un message d'erreur brut |
| **Question sans réponse** | « Je n'ai pas trouvé de passage de contrat correspondant. Voici les garanties du dossier… » + escalade vers un humain |
| **Coller un relevé de soins** | le garde-fou d'injection est visible : la pièce jointe est traitée comme une donnée, jamais comme une instruction |

### 5.5 Extrait de code — la bulle de réponse avec sources

```tsx
// apps/web/src/pages/Assure/Bulle.tsx
export function Bulle({ reponse }: { reponse: RagAnswer }) {
  return (
    <article className="bulle assistant">
      <p className="bulle-texte">{reponse.reponse}</p>

      {reponse.sources.length > 0 && (
        <details className="sources" open>
          <summary>
            {reponse.sources.length} source{reponse.sources.length > 1 ? 's' : ''} documentaire
            {reponse.sources.length > 1 ? 's' : ''}
          </summary>
          <ul>
            {reponse.sources.map((source, index) => (
              <li key={index} className="source">
                <div className="source-tete">
                  <span className="mono">{String(source.contrat)}</span>
                  <span className="source-article">Article {String(source.article)}</span>
                  <span className="source-score">
                    pertinence {Number(source.score).toFixed(2)}
                  </span>
                </div>
                <blockquote className="source-extrait">{String(source.extrait)}</blockquote>
              </li>
            ))}
          </ul>
        </details>
      )}

      {reponse.etapes_agent.length > 0 && (
        <details className="traces">
          <summary>Traces de l’agent ({reponse.etapes_agent.length})</summary>
          <ol>
            {reponse.etapes_agent.map((etape, index) => (
              <li key={index}>
                <span className="mono">{String(etape.outil)}</span>
                <span className="traces-duree">{Number(etape.duree_ms ?? 0).toFixed(0)} ms</span>
                <span className="traces-resultat">{String(etape.resultat)}</span>
              </li>
            ))}
          </ol>
        </details>
      )}

      <footer className="bulle-meta">
        {Math.round(reponse.latence_ms)} ms · {reponse.tokens} token(s)
        {reponse.cache_semantique && ' · réponse servie depuis le cache'}
      </footer>
    </article>
  )
}
```

### 5.6 Contrats API nécessaires

```http
GET /api/core/factures/statistiques?assure=<pseudonyme>
→ 200 { "rembourse": 12500, "reste": 8000, "en_attente": 4250000, "nombre": 12,
        "serie": [ { "mois": "2026-05", "rembourse": 8000, "reste": 2000 } ] }
```

---

## 6. Rôle C — Gestionnaire

**Objectif** : traiter une alerte en moins de 30 secondes, avec une décision
motivated et tracée.

### 6.1 Arborescence

```
/gestionnaire
├── Centre d'alertes   (existant, densifié)  → file priorisée + détail
├── Historique          (existant)             → décisions passées
└── (drawer) Investigation approfondie        → note d'analyse
```

### 6.2 Wireframe — Centre d'alertes

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Centre d'alertes          3 à traiter      [Rafraîchir] [Filtres ▾]       │
├────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐┌─────────────┐┌─────────────┐┌─────────────┐               │
│  │ 3           ││ 0,94        ││ 2,5 M Ar    ││ 12 min      │               │
│  │ À TRAITER   ││ SCORE MAX   ││ MONTANT     ││ ÂGE MOYEN   │               │
│  └─────────────┘└─────────────┘└─────────────┘└─────────────┘               │
├────────────────────────────────────────────────────────────────────────────┤
│  Score ▾ │ Facture   │ Assuré        │ Montant    │ Facteurs clés    │ Statut│
│  ────────┼───────────┼───────────────┼────────────┼──────────────────┼──────│
│  0,999   │ FAC-9184… │ assr_FyuK…   │ 2 500 000  │ forfait 8× moy. │ ●     │
│  0,982   │ FAC-77BD… │ assr_2CN4…   │   850 000  │ doublon presc.  │ ●     │
│  0,941   │ FAC-54FD… │ assr_9oGf…   │   200 000  │ hors horaire     │ ●     │
├────────────────────────────────────────────────────────────────────────────┤
│  DÉTAIL DE L'ALERTE (sélection)                                            │
│  ┌──────────────────────────────────────────────┬─────────────────────────┐ │
│  │ Score 0,999 — seuil 0,288                    │  Explicabilité          │ │
│  │ ▂▄▆█▇▅▃▂ score de base → score obtenu        │  [Waterfall]            │ │
│  │                                              │  + forfait ×8   +0,312  │ │
│  │  Motifs retenus :                            │  − heure normale −0,081 │ │
│  │  · Forfait césarienne 8× la moyenne          │  − formule ESSENTIEL    │ │
│  │  · Aucun acte de consultation associé        │                         │ │
│  │                                              │  Montant total          │ │
│  │  [Confirmer la fraude] [Rejeter] [Pièce]     │  2 500 000 Ar           │ │
│  │  Motif (obligatoire) : [________________]     │  5 lignes               │ │
│  └──────────────────────────────────────────────┴─────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

**Choix structurant** : le détail est **sous** la liste, pas dans un panneau
latéral. Le gestionnaire compare en permanence l'alerte courante aux
suivantes ; un panneau latéral masquerait la file et forcerait à
basculer. La liste reste visible, la ligne active est surlignée.

### 6.3 Interactions clés

| Interaction | Comportement |
| --- | --- |
| **Tri par score** | par défaut, décroissant. C'est la file qui doit être traitée, pas un ordre alphabétique |
| **Clavier** | `j`/`k` ligne suivante/précédente, `e` ouvrir le détail, `f` confirmer, `r` rejeter, `p` demander une pièce, `?` aide |
| **Sélection d'une ligne** | le détail se charge (état de chargement dédié, pas de clignotement de toute la page) |
| **Confirmer la fraude** | confirmation explicite (le geste est engageant) + **motif obligatoire** ; le motif est pré-rempli par une suggestion, jamais vide |
| **Rejeter** | le motif est obligatoire et doit être > 10 caractères : un rejet sans motif ne peut pas être audité |
| **Décision** | la ligne quitte la file, un bandeau confirme (« Alerte 12 confirmée — tracée dans le journal »), et le focus passe à la ligne suivante |
| **Facteur SHAP** | survol → surlignage de la ligne correspondante dans le tableau de la facture ; clic → explication en langage métier |
| **Alerte non tranchée** | elle reste en tête de file avec son âge : le temps de traitement est un indicateur de charge |
| **Erreur réseau à la décision** | la décision n'est pas perdue : le motif reste saisi, un bandeau propose « Réessayer » |

### 6.4 Extrait de code — la ligne d'alerte

```tsx
// apps/web/src/pages/Gestionnaire/LigneAlerte.tsx
export function LigneAlerte({
  alerte,
  active,
  onSelect,
}: {
  alerte: AlertSummary
  active: boolean
  onSelect: () => void
}) {
  const niveau = alerte.score_fraude >= 0.9 ? 'alerte' : 'avert'
  return (
    <tr
      className={active ? 'ligne-active' : undefined}
      onClick={onSelect}
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') onSelect() }}
    >
      <td className="droite">
        <span className={`score score-${niveau}`}>{alerte.score_fraude.toFixed(3)}</span>
      </td>
      <td className="mono">{alerte.facture_id}</td>
      <td className="mono">{alerte.assure_pseudonyme}</td>
      <td className="droite">{montant(alerte.montant_total)}</td>
      <td>
        <span className="facteur-facture">Forfait élevé · doublon d’ordonnance</span>
      </td>
      <td>
        <Pastille statut={alerte.statut} />
      </td>
    </tr>
  )
}
```

### 6.5 Contrats API nécessaires

```http
GET /api/core/alertes/file?statut=nouvelle&limit=50&tri=score
→ 200 [ { "prediction_id": "12", "facture_id": "…", "score_fraude": 0.999,
           "montant_total": 2500000, "age_minutes": 12, "top_facteurs": ["…"] } ]

GET /api/core/alertes/statistiques
→ 200 { "a_traiter": 3, "score_max": 0.999, "montant_total": 4250000, "age_moyen_min": 12 }
```

---

## 7. Rôle D — Administrateur

**Objectif** : voir l'état de la plateforme, agir sans redéployer, et
démontrer la supervision.

### 7.1 Arborescence

```
/administration
├── Pilotage BI        (existant, enrichi)  → KPI financiers + graphiques
├── Supervision        (existant Observabilité) → SLO, latence, erreurs, dérive
├── Configuration      (existant, enrichi)  → seuil, canaux, modèle, comptes
├── Journal            (existant)           → audit en chronologie
└── (drawer) Détail d'une ligne de journal
```

### 7.2 Wireframe — Pilotage BI

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Pilotage                                    [30 derniers jours ▾] [Export] │
├────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────┐┌────────────┐┌────────────┐┌────────────┐┌────────────┐     │
│  │ 12,4 M Ar  ││ 84 632     ││ 96,2 %     ││ 1 850 M Ar ││ 38         │     │
│  │ TRAITÉS    ││ FACTURES   ││ DÉLAI      ││ ÉCONOMISÉS ││ ALERTES    │     │
│  │ ▲ +8 %     ││ ▲ +3 %     ││ 2,1 j      ││ ▲ +12 %    ││ TRAITÉES   │     │
│  └────────────┘└────────────┘└────────────┘└────────────┘└────────────┘     │
├────────────────────────────────────────────────────────────────────────────┤
│  Flux traité par statut      │  Évolution des alertes      │  Répartition    │
│  ████████ PAYEE  79 775     │  ▂▄▆█▅▃▂▁  (12 semaines)  │  par motif     │
│  ██ EN_COURS 2 826          │                              │  forfait 41 %  │
│  █  REJETEE   1 992        │                              │  doublon 27 %  │
├────────────────────────────────────────────────────────────────────────────┤
│  [Ouvrir le tableau de bord Superset]     ← lien « Pilotage BI » du header  │
└────────────────────────────────────────────────────────────────────────────┘
```

Le lien Superset existe déjà (`VITE_SUPERSET_URL`). Il doit être **visible
dans l'écran**, pas seulement dans la navigation : c'est la preuve que le
Flux 3 est accessible depuis l'interface unique.

### 7.3 Wireframe — Supervision

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Supervision                          Sonde du 20/10 14:08 · tout est OK    │
├────────────────────────────────────────────────────────────────────────────┤
│  Latence d'inférence (P50 / P95 / P99)  │  Erreurs applicatives          │
│  185 ms      288 ms      288 ms         │  0 sur 38 requêtes (0,0 %)     │
│  ▁▂▁▁▁▂▃▂▂▃▂▄▅▄▃▂▁▁▁▁▁▁▂▃ 30 j   │  (prometheus, Grafana)         │
├────────────────────────────────────────────────────────────────────────────┤
│  Dérive du modèle (PSI)                 │  Services                      │
│  PSI 0,042 — nominal                    │  ● api-core     ok    v2      │
│  [Voir le rapport]                      │  ● api-inference ok   v2      │
│                                         │  ● api-rag      degraded      │
├────────────────────────────────────────────────────────────────────────────┤
│  Secrets manquants : llm_api_key, embedding_api_key  [Configurer]         │
└────────────────────────────────────────────────────────────────────────────┘
```

### 7.4 Interactions clés

| Interaction | Comportement |
| --- | --- |
| **Modifier le seuil** | champ numérique + aperçu de l'impact (« 38 alertes/mois au-dessus du seuil actuel ») ; validation côté API, application immédiate, message « seuil appliqué » |
| **Basculer de modèle** | liste des versions avec métriques (ROC-AUC, rappel), diff visuel, **confirmation explicite** — c'est l'action la plus risquée de la plateforme |
| **Activer/désactiver un canal** | interrupteur + champ destinataire ; état `configure` distinct de `actif` affiché côte à côte |
| **Rechercher dans le journal** | filtre par acteur, action, cible, date ; export CSV |
| **Dérive au-dessus du seuil** | bandeau ambre avec le PSI et la liste des variables dérivées |
| **Service dégradé** | la ligne du service passe en ambre avec la raison (« 0 document indexé ») — jamais un simple « down » |

### 7.5 Extrait de code — le sélecteur de seuil

```tsx
// apps/web/src/pages/Administration/Seuil.tsx
export function Seuil() {
  const [seuil, setSeuil] = useState('')
  const [apercu, setApercu] = useState<{ auDessus: number; parMois: number } | null>(null)

  // L'aperçu est débattu pendant la saisie : l'administrateur doit voir
  // l'effet de son curseur AVANT de l'appliquer.
  useEffect(() => {
    const valeur = Number(seuil)
    if (!Number.isFinite(valeur) || valeur < 0 || valeur > 1) { setApercu(null); return }
    const minuteur = setTimeout(() => {
      api<{ auDessus: number; parMois: number }>(
        `/api/core/admin/seuil/apercu?seuil=${valeur}`,
      )
        .then(setApercu)
        .catch(() => setApercu(null))
    }, 400)
    return () => clearTimeout(minuteur)
  }, [seuil])

  return (
    <Carte titre="Seuil d’alerte" actions={<Badge ton="info">Appliqué à chaud</Badge>}>
      <Champ
        label="Seuil de score"
        aide="Une facture au-dessus de ce score entre dans la file du gestionnaire."
      >
        <input
          type="number" min={0} max={1} step={0.01} value={seuil}
          onChange={(e) => setSeuil(e.target.value)}
          aria-describedby="apercu-seuil"
        />
      </Champ>
      {apercu !== null && (
        <p id="apercu-seuil" className="aide" role="status">
          À ce seuil, <strong>{apercu.auDessus}</strong> facture(s) entreraient en file
          (≈ {apercu.parMois} par mois).
        </p>
      )}
    </Carte>
  )
}
```

---

## 8. Accessibilité — checklist WCAG 2.1 AA

| Critère | Application concrète |
| --- | --- |
| **1.4.3 contraste** | texte ≥ 4,5:1, texte large ≥ 3:1. Vérifier `--encre-douce` (#475569) sur `--surface` : 7,4:1 ✓. `--encre-faible` (#94a3b8) sur blanc : 2,6:1 — **interdit pour du texte**, réservé aux icônes décoratives |
| **1.4.11 contraste non textuel** | bordure de champ ≥ 3:1 ; les pastilles de statut portent une couleur **et** un texte, jamais la couleur seule |
| **2.1.1 clavier** | tous les contrôles au clavier ; le tableau de la file d'alertes est navigable aux flèches ; `j`/`k` pour la file |
| **2.4.1 contour de focus** | `:focus-visible { outline: none; box-shadow: var(--focus-anneau) }` sur **tous** les éléments interactifs, y compris les lignes de tableau |
| **2.4.7 focus visible** | l'anneau de focus ne doit jamais être supprimé sans remplacement |
| **3.3.1 identification des erreurs** | chaque erreur est rattachée à son champ par `aria-describedby` et annoncée par `role="alert"` ; le message nomme le champ fautif |
| **4.1.2 nom, rôle, valeur** | onglets : `role="tab"` + `aria-selected` + `aria-controls` + `id` sur le panneau ; tiroir : `role="dialog"` + `aria-modal` + focus entrant/sortant |
| **4.1.3 messages d'état** | `role="status"` pour les confirmations, `role="alert"` pour les erreurs, `aria-live="polite"` sur le compteur de résultats |
| **1.3.1 information et relations** | `<th scope="col">`, `<caption>` ou `aria-label` sur chaque tableau, listes `<ul>` pour les listes de données |
| **2.3.3 animation** | `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important } }` |
| **1.1.1 alternatives** | SVG : `aria-hidden="true"` si décoratif, `role="img"` + `aria-label` si porteur d'information (barres, waterfall) |

```css
:focus-visible { outline: none; box-shadow: var(--focus-anneau); border-radius: var(--rayon-sm); }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
.visuellement-cache {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}
```

---

## 9. Plan de mise en œuvre

Séquencement proposé, du plus visible pour le jury au plus discret.

### Jalon 1 — Fondations et lisibilité (demi-journée)

1. Tokens : palette cible, échelles, espacements → remplacement du bloc `:root`.
2. `Pastille` (statut métier unifié) + remplacement des tables locales.
3. `Kpi` + grille de 4 tuiles.
4. `Squelette`, `EtatVide`, `ErreurBloc` et application aux 4 écrans.
5. `Pagination` serveur sur les listes.

**Gain** : l'ensemble de l'interface change de niveau visuel sans toucher à
la logique. C'est le jalon le plus rentable.

### Jalon 2 — Tableaux de bord (1 à 2 jours)

1. `GET /api/core/factures/statistiques` (agrégat, une requête).
2. Vue d'ensemble du professionnel + graphiques.
3. KPI du gestionnaire (file, score max, âge moyen).
4. KPI de l'assuré (remboursé / reste / en attente) + graphique 6 mois.
5. KPI administrateur (volumes, délais, économies) + lien Superset visible.

### Jalon 3 — Densité et interactions (1 jour)

1. `Tableau` générique + tri + filtre ; adoption par le gestionnaire et le professionnel.
2. `Waterfall` SHAP à la place de `ShapList` dans le détail d'alerte.
3. Raccourcis clavier du gestionnaire.
4. `Tiroir` pour l'assistant (chat) et le détail de journal.
5. Historique du gestionnaire en `Chronologie`.

### Jalon 4 — Finition (½ journée)

1. Mode sombre (tokens uniquement).
2. Passe de contraste + audit clavier sur les 4 parcours.
3. Libellés accentués (le projet a fait le choix inverse ; à trancher
   explicitement, car un livrable francophone sans accents se remarque).
4. Textesalternatifs sur tous les SVG porteurs d'information.

---

## 10. Décisions à trancher par l'équipe

| Question | Recommandation | Impact |
| --- | --- | --- |
| Palette teal (actuelle) ou bleu institutionnel (brief) ? | **bleu** : registre assurance, conforme au CDC « institutionnel de confiance » | 8 lignes de CSS |
| Navigation haute (actuelle) ou latérale ? | **latérale** : les écrans gestionnaire/admin sont des tableaux denses | refonte du `Shell` |
| Tailwind ou tokens CSS ? | **tokens CSS** : pas de dépendance, pas de réécriture | 1 fichier |
| L'assistant : page dédiée ou tiroir ? | **tiroir** : l'assuré garde ses remboursements sous les yeux | 1 écran |
| Le détail d'alerte : panneau latéral ou sous la liste ? | **sous la liste** : le gestionnaire compare en continu | refonte du `ManagerPage` |
| Accents dans les libellés ? | **oui** : livrable francophone | ~400 chaînes |
| Mode sombre ? | **oui**, mais après le jalon 3 | tokens seuls |
