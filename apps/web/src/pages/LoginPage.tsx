import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { messageErreur } from '../api/client'
import { ACCUEIL } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Erreur } from '../components/ui'

const COMPTES_DEMO = [
  { email: 'assure@predicare.local', role: 'Assure' },
  { email: 'pro@predicare.local', role: 'Professionnel de sante' },
  { email: 'gestionnaire@predicare.local', role: 'Gestionnaire' },
  { email: 'admin@predicare.local', role: 'Administrateur' },
]

export function LoginPage() {
  const { connexion, profile } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const depuis = (location.state as { depuis?: string } | null)?.depuis

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  if (profile !== null) {
    return <Navigate to={ACCUEIL[profile.role]} replace />
  }

  const soumettre = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setEnvoi(true)
    try {
      const profil = await connexion(email.trim(), password)
      navigate(depuis ?? ACCUEIL[profil.role], { replace: true })
    } catch (error) {
      setErreur(messageErreur(error))
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div className="login">
      <div className="login-presentation">
        <div className="marque grande">
          <span className="marque-point" aria-hidden="true" />
          PrediCare
        </div>
        <h1>La bonne facture, au bon moment.</h1>
        <p>
          Plateforme de tiers payant : depot des factures, detection des anomalies,
          explication de chaque alerte et decision humanisee.
        </p>
        <ul className="login-points">
          <li>Un score et un rapport SHAP pour chaque facture</li>
          <li>Quatre roles separes, controles cote serveur</li>
          <li>Donnees pseudonymisees, journal d audit complet</li>
        </ul>
      </div>

      <form className="login-carte" onSubmit={soumettre}>
        <h2>Connexion</h2>
        <p className="login-aide">Utilisez un compte de demonstration cree par le seed.</p>

        <label className="champ">
          <span className="champ-label">Adresse e-mail</span>
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="prenom@predicare.local"
          />
        </label>

        <label className="champ">
          <span className="champ-label">Mot de passe</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        <Erreur message={erreur} />

        <button type="submit" className="bouton principal large" disabled={envoi}>
          {envoi ? 'Connexion...' : 'Se connecter'}
        </button>

        <div className="comptes-demo">
          <span className="champ-label">Comptes de demonstration</span>
          <ul>
            {COMPTES_DEMO.map((compte) => (
              <li key={compte.email}>
                <button
                  type="button"
                  className="lien"
                  onClick={() => setEmail(compte.email)}
                >
                  {compte.email}
                </button>
                <span>{compte.role}</span>
              </li>
            ))}
          </ul>
          <p className="champ-aide">
            Le mot de passe est celui choisi avec <code>DEMO_PASSWORD</code> au moment du seed.
          </p>
        </div>
      </form>
    </div>
  )
}
