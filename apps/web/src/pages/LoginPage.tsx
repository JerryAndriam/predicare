import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { CircleCheck } from 'lucide-react'

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
      <div className="login-contenu">
        <section className="login-presentation">
          <span className="marque">
            <span className="marque-point" aria-hidden="true" />
            PrediCare
          </span>
          <h1>La bonne facture, au bon moment.</h1>
          <p>
            PrediCare est la plateforme de tiers payant qui relie les professionnels de
            santé, les caisses et les assureurs : chaque facture est vérifiée, notée,
            expliquée, puis décidée par un gestionnaire.
          </p>
          <ul className="login-arguments">
            {ARGUMENTS.map((argument) => (
              <li className="login-argument" key={argument}>
                <CircleCheck size={18} strokeWidth={1.75} aria-hidden="true" />
                {argument}
              </li>
            ))}
          </ul>
        </section>

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
    </main>
  )
}
