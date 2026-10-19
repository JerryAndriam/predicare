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

export type Ton = 'neutre' | 'ok' | 'alerte' | 'info'

export function Badge({ ton = 'neutre', children }: { ton?: Ton; children: ReactNode }) {
  return <span className={`badge ${ton}`}>{children}</span>
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
