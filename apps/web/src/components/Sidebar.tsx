import { NavLink } from 'react-router-dom'

import type { Role } from '../api/types'
import { peut, useAuth } from '../auth/AuthContext'
import { ESPACES, LIEN_PILOTAGE, type Espace, type Section } from '../navigation'

/**
 * La navigation de l'espace.
 *
 * Sous 1024 px, elle devient un tiroir ; au-dela, un rail de 68 px peut la
 * reduire aux icones. Les liens communs (compte, aide) vivent dans le menu
 * du profil, pas ici.
 */
export function Sidebar({
  espace,
  repliee,
  ouverte,
  onFermer,
}: {
  espace: Espace | null
  repliee: boolean
  ouverte: boolean
  onFermer: () => void
}) {
  const { profile } = useAuth()

  const rendreLien = (section: Section) => (
    <li key={section.chemin}>
      <NavLink
        to={section.chemin}
        end={section.chemin === espace?.accueil}
        aria-label={repliee ? section.libelle : undefined}
        title={repliee ? section.libelle : undefined}
        onClick={onFermer}
        className={({ isActive }) =>
          [
            'group relative flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors',
            isActive
              ? 'bg-primary-soft text-primary-dark'
              : 'text-ink-soft hover:bg-surface-2 hover:text-ink',
            repliee ? 'lg:justify-center lg:px-0' : '',
          ].join(' ')
        }
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <span
                aria-hidden="true"
                className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary"
              />
            )}
            <span className="flex w-[22px] shrink-0 items-center justify-center">
              <section.icone size={20} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span className={`truncate ${repliee ? 'lg:hidden' : ''}`}>{section.libelle}</span>
          </>
        )}
      </NavLink>
    </li>
  )

  return (
    <aside
      className={[
        'fixed inset-y-16 left-0 z-40 w-[280px] shrink-0 overflow-y-auto border-r border-line bg-surface px-3 py-4 transition-[transform,width] duration-200',
        'lg:sticky lg:inset-auto lg:top-16 lg:z-0 lg:h-[calc(100vh-4rem)] lg:translate-x-0',
        ouverte ? 'translate-x-0 shadow-float lg:shadow-none' : '-translate-x-full',
        repliee ? 'lg:w-[68px]' : 'lg:w-[260px]',
      ].join(' ')}
      aria-label="Navigation de l’espace"
    >
      {espace !== null && (
        <>
          <p
            className={`px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-ink-muted ${
              repliee ? 'lg:hidden' : ''
            }`}
          >
            {espace.libelle}
          </p>
          {repliee && <div className="mx-3 mb-3 hidden h-px bg-line lg:block" aria-hidden="true" />}
          <ul className="flex flex-col gap-0.5">{espace.sections.map(rendreLien)}</ul>
        </>
      )}

      {peut(profile, 'gestionnaire', 'administrateur') && (
        <div className="mt-4 border-t border-line pt-3">
          <ul className="flex flex-col gap-0.5">{rendreLien(LIEN_PILOTAGE)}</ul>
        </div>
      )}
    </aside>
  )
}

export function espaceCourant(role: Role | undefined): Espace | null {
  if (role === undefined) return null
  return ESPACES.find((espace) => espace.roles.includes(role)) ?? null
}
