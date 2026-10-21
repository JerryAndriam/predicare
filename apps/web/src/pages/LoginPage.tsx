import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { messageErreur } from '../api/client'
import { ACCUEIL } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Champ, Erreur } from '../components/ui'

const ARGUMENTS = [
  'Un score et une explication pour chaque facture déposée',
  'Quatre espaces séparés, chacun avec ses propres droits',
  'Des données pseudonymisées et une décision toujours motivée',
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
    <main className="login">
      <section className="login-visuel">
        <img
          className="login-visuel-image"
          src="/brand/kolikolycare-login.jpg"
          alt="KolikolyCare, système intelligent de détection de fraudes médicales et d’optimisation santé"
        />
        <ul className="login-arguments">
          {ARGUMENTS.map((argument) => (
            <li className="login-argument" key={argument}>
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="m9 12 2 2 4-4" />
              </svg>
              {argument}
            </li>
          ))}
        </ul>
      </section>

      <section className="login-panneau">
        <div className="login-contenu">
          <div className="login-marque">
            <img
              className="login-marque-logo"
              src="/brand/kolikolycare-marque.png"
              alt=""
            />
            <span>KolikolyCare</span>
          </div>

          <h1>La bonne facture, au bon moment.</h1>
          <p className="login-intro">
            KolikolyCare est la plateforme de tiers payant qui relie les professionnels de
            santé, les caisses et les assureurs : chaque facture est vérifiée, notée,
            expliquée, puis décidée par un gestionnaire.
          </p>

          <form className="login-carte" onSubmit={soumettre}>
            <h2>Connexion</h2>
            <p className="login-aide">Accédez à votre espace de travail.</p>

            <Champ label="Adresse e-mail" requis>
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="prenom@predicare.local"
              />
            </Champ>

            <Champ label="Mot de passe" requis>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Champ>

            <Erreur message={erreur} />

            <button type="submit" className="bouton principal large" disabled={envoi}>
              {envoi ? 'Connexion…' : 'Se connecter'}
            </button>

            <p className="login-pied">Un accès nominatif et personnel.</p>
          </form>
        </div>
      </section>
    </main>
  )
}
