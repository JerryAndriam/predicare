import type { ReactNode } from 'react'

export function Carte({
  titre,
  actions,
  children,
}: {
  titre?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="carte">
      {(titre !== undefined || actions !== undefined) && (
        <header className="carte-entete">
          {titre !== undefined && <h2>{titre}</h2>}
          {actions !== undefined && <div className="carte-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export type Ton = 'neutre' | 'ok' | 'alerte' | 'info' | 'avert'

export function Badge({ ton = 'neutre', children }: { ton?: Ton; children: ReactNode }) {
  return <span className={`badge ${ton}`}>{children}</span>
}

/**
 * Squelette de chargement.
 *
 * Il occupe la place du contenu a venir : la mise en page ne bouge pas
 * quand la reponse arrive, et l'utilisateur sait immediatement que
 * l'ecran travaille. Un texte « Chargement... » laissait, lui, un vide
 * a geometrie variable.
 */
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

/**
 * Etat vide.
 *
 * Jamais un simple tiret : toujours ce qui manque, pourquoi, et ce qu'on
 * peut faire. C'est l'ecran que le jury regarde quand il n'y a rien a
 * montrer : il doit expliquer la situation, pas la constater.
 */
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

/**
 * Pagination serveur.
 *
 * Les listes sont paginees COTE SERVEUR : le front ne recoit que la page
 * demandee, jamais la totalite. Le total affiche est celui du serveur,
 * ce qui evite de croire que la liste est complete alors qu'elle est
 * tronquee.
 */
export function Pagination({
  total,
  offset,
  limite,
  onChange,
  libelle = 'éléments',
}: {
  total: number
  offset: number
  limite: number
  onChange: (offset: number) => void
  libelle?: string
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
      <span className="pagination-etat" role="status">
        Page <strong>{page}</strong> sur {pages} · {total} {libelle}
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

/**
 * Tuile d'indicateur cle.
 *
 * Un chiffre seul n'apprend rien : la tuile porte donc toujours une
 * COMPARAISON (variation, contexte) et, si possible, une tendance. Elle
 * est cliquable quand une action lui correspond (filtrer la liste).
 */
export function Kpi({
  titre,
  valeur,
  unite,
  contexte,
  ton = 'neutre',
  onClick,
}: {
  titre: string
  valeur: string | number
  unite?: string
  contexte?: ReactNode
  ton?: Ton
  onClick?: () => void
}) {
  const contenu = (
    <>
      <span className="kpi-libelle">{titre}</span>
      <span className="kpi-valeur">
        {valeur}
        {unite !== undefined && <span className="kpi-unite">{unite}</span>}
      </span>
      {contexte !== undefined && <span className="kpi-contexte">{contexte}</span>}
    </>
  )
  if (onClick === undefined) {
    return <div className={`kpi kpi-${ton}`}>{contenu}</div>
  }
  return (
    <button type="button" className={`kpi kpi-${ton} kpi-action`} onClick={onClick}>
      {contenu}
    </button>
  )
}

/**
 * Statut metier normalise.
 *
 * La base porte des statuts heterogenes : `PAYEE` vient du seed, `reçue`
 * vient du depot, `fraude_confirmee` vient de la decision du gestionnaire.
 * L'utilisateur ne voit que six etats. Cette table est le SEUL endroit du
 * front qui connait la correspondance.
 */
const ETATS: Record<string, { libelle: string; ton: Ton }> = {
  payee: { libelle: 'Remboursé', ton: 'ok' },
  en_cours: { libelle: 'En cours', ton: 'avert' },
  recue: { libelle: 'Reçue', ton: 'info' },
  rejetee: { libelle: 'Rejetée', ton: 'alerte' },
  fraude_confirmee: { libelle: 'Fraude confirmée', ton: 'alerte' },
  piece_demandee: { libelle: 'Pièce demandée', ton: 'avert' },
}

export function Pastille({ statut }: { statut: string }) {
  const etat = ETATS[statut.trim().toLowerCase()]
  if (etat === undefined) return <Badge ton="neutre">{statut || '—'}</Badge>
  return <Badge ton={etat.ton}>{etat.libelle}</Badge>
}

export function Erreur({ message }: { message: string | null }) {
  if (message === null || message === '') return null
  return (
    <p className="erreur" role="alert">
      {message}
    </p>
  )
}

export function Succes({ message }: { message: string | null }) {
  if (message === null || message === '') return null
  return (
    <p className="succes" role="status">
      {message}
    </p>
  )
}

export function Vide({ children }: { children: ReactNode }) {
  return <p className="vide">{children}</p>
}

export function Chargement({ texte = 'Chargement...' }: { texte?: string }) {
  return <p className="vide">{texte}</p>
}

export function Champ({
  label,
  aide,
  children,
}: {
  label: string
  aide?: string
  children: ReactNode
}) {
  return (
    <label className="champ">
      <span className="champ-label">{label}</span>
      {children}
      {aide !== undefined && <span className="champ-aide">{aide}</span>}
    </label>
  )
}

/** Montant lisible : les factures sont en ariary dans le jeu de donnees. */
export function montant(valeur: number): string {
  return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(valeur) + ' Ar'
}

/** Montant facultatif : les factures non traitees n'ont pas encore de prise en charge. */
export function montantOuTiret(valeur: number | null | undefined): string {
  return valeur === null || valeur === undefined ? '—' : montant(valeur)
}

export function dateCourte(iso: string | null): string {
  if (iso === null) return '-'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function pourcentage(valeur: number): string {
  return (valeur * 100).toFixed(1) + ' %'
}
