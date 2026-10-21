import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ChevronRight, Info, type LucideIcon } from 'lucide-react'

/**
 * Les blocs de contenu.
 *
 * Ils forment le vocabulaire commun des pages : un en-tete qui dit ou l'on
 * est, un chapo qui dit a quoi sert l'ecran, une tuile qui renvoie ailleurs,
 * une alerte qui met en garde.
 */

/* ------------------------------------------------------------ en-tete de page */

export interface ElementFilAriane {
  libelle: string
  chemin?: string
}

export function FilAriane({ elements }: { elements: ElementFilAriane[] }) {
  return (
    <nav aria-label="Fil d’Ariane" className="mb-2">
      <ol className="flex flex-wrap items-center gap-1 text-[13px] text-ink-muted">
        {elements.map((element, index) => (
          <li key={element.libelle} className="flex items-center gap-1">
            {index > 0 && (
              <ChevronRight size={13} className="text-line-strong" aria-hidden="true" />
            )}
            {element.chemin === undefined ? (
              <span aria-current="page" className="font-semibold text-ink">
                {element.libelle}
              </span>
            ) : (
              <Link
                to={element.chemin}
                className="rounded text-ink-soft transition-colors hover:text-primary hover:underline"
              >
                {element.libelle}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}

export function EnTetePage({
  fil,
  titre,
  chapo,
  actions,
}: {
  fil: ElementFilAriane[]
  titre: string
  chapo?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="mb-6 border-b border-line pb-4">
      <FilAriane elements={fil} />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-[30px] font-bold leading-tight tracking-[-0.025em] text-ink">
            {titre}
          </h1>
          {chapo !== undefined && (
            <p className="mt-2 max-w-[70ch] text-[17px] leading-relaxed text-ink-soft">{chapo}</p>
          )}
        </div>
        {actions !== undefined && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
    </header>
  )
}

/* --------------------------------------------------------------------- tuile */

export function Tuile({
  icone: Icone,
  titre,
  texte,
  chemin,
}: {
  icone: LucideIcon
  titre: string
  texte: string
  chemin: string
}) {
  return (
    <Link to={chemin} className="tuile">
      <span className="tuile-icone" aria-hidden="true">
        <Icone size={20} strokeWidth={1.75} />
      </span>
      <span className="tuile-corps">
        <span className="tuile-titre">{titre}</span>
        <span className="tuile-texte">{texte}</span>
      </span>
      <ArrowRight className="tuile-fleche" size={18} aria-hidden="true" />
    </Link>
  )
}

/* -------------------------------------------------------------- alerte ligne */

export type TonAlerte = 'info' | 'attention' | 'succes' | 'erreur'

export function AlerteLigne({
  ton = 'info',
  titre,
  children,
}: {
  ton?: TonAlerte
  titre?: string
  children: ReactNode
}) {
  return (
    <div className={`alerte-ligne ${ton}`}>
      <span className="alerte-ligne-icone" aria-hidden="true">
        <Info size={20} strokeWidth={1.75} />
      </span>
      <div>
        {titre !== undefined && <p className="alerte-ligne-titre">{titre}</p>}
        <div className="alerte-ligne-texte">{children}</div>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- stat cle */

export function StatCle({
  valeur,
  unite,
  libelle,
  contexte,
  ton = 'primaire',
}: {
  valeur: string | number
  unite?: string
  libelle: string
  contexte?: string
  ton?: 'primaire' | 'info' | 'alerte' | 'avert'
}) {
  const classe = ton === 'primaire' ? 'stat' : `stat ${ton}`
  return (
    <div className={classe}>
      <div className="stat-valeur">
        {valeur}
        {unite !== undefined && <span className="stat-unite">{unite}</span>}
      </div>
      <div className="stat-libelle">{libelle}</div>
      {contexte !== undefined && <div className="stat-contexte">{contexte}</div>}
    </div>
  )
}

/* --------------------------------------------------------------- pas a pas */

export function Etape({ titre, children }: { titre: string; children?: ReactNode }) {
  return (
    <li className="etape">
      <span className="etape-numero" aria-hidden="true" />
      <div>
        <p className="etape-titre">{titre}</p>
        {children !== undefined && <div className="etape-texte">{children}</div>}
      </div>
    </li>
  )
}
