import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { ROLE_LABELS, type Role } from '../api/types'
import { peut, useAuth } from '../auth/AuthContext'

interface Espace {
  chemin: string
  libelle: string
  roles: Role[]
}

const ESPACES: Espace[] = [
  { chemin: '/assure', libelle: 'Mes remboursements', roles: ['assure'] },
  { chemin: '/professionnel', libelle: 'Dépôt de facture', roles: ['professionnel_sante'] },
  { chemin: '/gestionnaire', libelle: 'File d alertes', roles: ['gestionnaire'] },
  { chemin: '/administration', libelle: 'Administration', roles: ['administrateur'] },
]

export function Shell() {
  const { profile, deconnexion } = useAuth()
  const navigate = useNavigate()

  if (profile === null) return null

  const sortie = () => {
    deconnexion()
    navigate('/connexion', { replace: true })
  }

  return (
    <div className="app">
      <header className="entete">
        <div className="barre-haut">
          <NavLink to="/" className="marque">
            <span className="marque-point" aria-hidden="true" />
            PrediCare
            <span className="marque-sous">TPA santé</span>
          </NavLink>
          <div className="utilisateur">
            <span className="utilisateur-nom">
              {profile.display_name ?? profile.subject}
            </span>
            <span className="badge info">{ROLE_LABELS[profile.role]}</span>
            <button type="button" className="bouton discret" onClick={sortie}>
              Se deconnecter
            </button>
          </div>
        </div>
        <nav className="nav" aria-label="Navigation principale">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'actif' : '')}>
            Accueil
          </NavLink>
          {ESPACES.filter((espace) => peut(profile, ...espace.roles)).map((espace) => (
            <NavLink
              key={espace.chemin}
              to={espace.chemin}
              className={({ isActive }) => (isActive ? 'actif' : '')}
            >
              {espace.libelle}
            </NavLink>
          ))}
          <NavLink to="/compte" className={({ isActive }) => (isActive ? 'actif' : '')}>
            Mon compte
          </NavLink>
          <NavLink to="/aide" className={({ isActive }) => (isActive ? 'actif' : '')}>
            Aide
          </NavLink>
          {peut(profile, 'gestionnaire', 'administrateur') && (
            <NavLink to="/pilotage" className={({ isActive }) => (isActive ? 'actif' : '')}>
              Pilotage BI
            </NavLink>
          )}
        </nav>
      </header>
      <main className="contenu">
        <Outlet />
      </main>
      <footer className="pied">
        PrediCare - demonstration. Les donnees affichees sont pseudonymisees.
      </footer>
    </div>
  )
}
