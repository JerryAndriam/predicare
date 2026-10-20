import { Navigate, Outlet, useLocation } from 'react-router-dom'

import type { Role } from '../api/types'
import { peut, useAuth } from '../auth/AuthContext'

export function RequireAuth() {
  const { profile, chargement } = useAuth()
  const location = useLocation()

  if (chargement) return <p className="centre">Chargement de la session...</p>
  if (profile === null) {
    return <Navigate to="/connexion" state={{ depuis: location.pathname }} replace />
  }
  return <Outlet />
}

/**
 * Garde d'ecran. Elle évité d'afficher un ecran interdit, mais elle ne
 * remplace PAS le controle serveur : l'API refuse de toute facon la requete
 * (403) si le role ne correspond pas. C'est une aide a la navigation.
 */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { profile } = useAuth()
  if (!peut(profile, ...roles)) return <Navigate to="/" replace />
  return <Outlet />
}
