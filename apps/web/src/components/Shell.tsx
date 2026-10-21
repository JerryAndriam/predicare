import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { libellePage } from '../navigation'
import { MenuProfil } from './MenuProfil'
import { espaceCourant, Sidebar } from './Sidebar'

const CLE_RAIL = 'predicare.sidebar'

type IconProps = { size: number }

function Menu({ size }: IconProps) {
  return (
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  )
}

function PanelLeftClose({ size }: IconProps) {
  return (
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18m4-12 3 3-3 3" />
    </svg>
  )
}

function PanelLeftOpen({ size }: IconProps) {
  return (
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18m7-12-3 3 3 3" />
    </svg>
  )
}

function initiales(nom: string): string {
  const mots = nom.trim().split(/\s+/).filter(Boolean)
  if (mots.length === 0) return '?'
  if (mots.length === 1) return mots[0].slice(0, 2).toUpperCase()
  return (mots[0][0] + mots[1][0]).toUpperCase()
}

export function Shell() {
  const { profile, deconnexion } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const contenu = useRef<HTMLElement>(null)

  const [rail, setRail] = useState(() => window.localStorage.getItem(CLE_RAIL) === 'rail')
  const [tiroir, setTiroir] = useState(false)

  useEffect(() => {
    window.localStorage.setItem(CLE_RAIL, rail ? 'rail' : 'deplie')
  }, [rail])

  useEffect(() => {
    setTiroir(false)
  }, [location.pathname])

  useEffect(() => {
    if (location.hash !== '') {
      const identifiant = decodeURIComponent(location.hash.slice(1))
      const minuteur = window.setTimeout(() => {
        document.getElementById(identifiant)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 80)
      return () => window.clearTimeout(minuteur)
    }
    window.scrollTo({ top: 0 })
  }, [location.pathname, location.hash])

  if (profile === null) return null

  const espace = espaceCourant(profile.role)
  const nom = profile.display_name ?? profile.subject
  const section =
    espace?.sections.find((element) =>
      element.chemin === location.pathname ? true : location.pathname.startsWith(`${element.chemin}/`),
    )?.libelle ?? libellePage(location.pathname)

  const sortie = () => {
    deconnexion()
    navigate('/connexion', { replace: true })
  }

  return (
    <div className="min-h-screen bg-fond">
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
      >
        Aller au contenu principal
      </a>

      <header className="sticky top-0 z-40 flex h-16 border-b border-line bg-surface">
        <NavLink
          to={espace?.accueil ?? '/'}
          className={[
            'flex shrink-0 items-center gap-2 overflow-hidden bg-[linear-gradient(135deg,#5b9bc9_0%,#3e7ca8_100%)] px-4 text-white transition-[width] duration-200',
            rail ? 'lg:w-[68px]' : 'lg:w-[260px]',
          ].join(' ')}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-white/40">
            <img
              src="/brand/kolikolycare-marque.png"
              alt=""
              className="h-full w-full object-cover"
            />
          </span>
          <span className={`flex min-w-0 flex-col ${rail ? 'lg:hidden' : ''}`}>
            <span className="font-display text-[17px] font-bold leading-tight tracking-tight">
              KolikolyCare
            </span>
            <span className="text-[9px] font-semibold uppercase tracking-[0.18em] text-white/70">
              TPA santé
            </span>
          </span>
        </NavLink>

        <div className="flex min-w-0 flex-1 items-center gap-3 px-3 sm:gap-4 sm:px-5">
          <button
            type="button"
            className="hidden h-10 w-10 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-surface-2 hover:text-ink lg:inline-flex"
            aria-label={rail ? 'Déplier la navigation' : 'Replier la navigation'}
            aria-expanded={!rail}
            onClick={() => setRail((etat) => !etat)}
          >
            {rail ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          </button>

          <div className="min-w-0">
            <span className="block text-[10px] font-bold uppercase tracking-[0.14em] text-ink-muted">
              {espace?.libelleCourt ?? 'PrediCare'}
            </span>
            <span className="block truncate font-display text-[15px] font-semibold text-ink">
              {section}
            </span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-surface-2 hover:text-ink lg:hidden"
              aria-label="Ouvrir la navigation"
              aria-expanded={tiroir}
              onClick={() => setTiroir((etat) => !etat)}
            >
              <Menu size={20} />
            </button>

            <MenuProfil
              nom={nom}
              role={ROLE_LABELS[profile.role]}
              initiales={initiales(nom)}
              onSortie={sortie}
            />
          </div>
        </div>
      </header>

      {tiroir && (
        <button
          type="button"
          className="fixed inset-x-0 bottom-0 top-16 z-30 bg-ink/40 lg:hidden"
          aria-label="Fermer la navigation"
          onClick={() => setTiroir(false)}
        />
      )}

      <div className="flex">
        <Sidebar
          espace={espace}
          repliee={rail}
          ouverte={tiroir}
          onFermer={() => setTiroir(false)}
        />

        <main
          ref={contenu}
          id="contenu"
          tabIndex={-1}
          className="min-w-0 flex-1 px-4 py-5 outline-none sm:px-6 lg:px-8 lg:py-8"
        >
          <div
            key={location.pathname}
            className="mx-auto w-full max-w-[1680px] animate-content"
          >
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
