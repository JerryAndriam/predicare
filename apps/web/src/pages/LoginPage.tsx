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
      <div className="login-presentation" style={{
        background: 'linear-gradient(160deg, #0e1a27 0%, #0f766e 60%, #0b5c56 100%)',
        color: '#fff',
        padding: '3rem 2rem',
        borderRadius: 'var(--rayon)',
        boxShadow: 'var(--ombre-levite)',
        marginBottom: '2rem',
        position: 'relative',
        overflow: 'hidden'
      }}>
        <div style={{ position: 'absolute', top: -30, right: -30, width: 200, height: 200, borderRadius: '50%', background: 'rgba(255,255,255,0.06)', pointerEvents: 'none' }} />
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div className="marque grande" style={{ color: '#fff', marginBottom: '1.2rem' }}>
            <span className="marque-point" aria-hidden="true" />
            PrediCare
          </div>
          <h1 style={{ fontSize: '2rem', letterSpacing: '-0.02em', marginBottom: '0.8rem' }}>La bonne facture, au bon moment.</h1>
          <p style={{ opacity: 0.88, maxWidth: '42ch', lineHeight: 1.55 }}>
            Plateforme de tiers payant : depot des factures, detection des anomalies,
            explication de chaque alerte et decision humanisee.
          </p>
          <ul className="login-points" style={{ listStyle: 'none', padding: 0, marginTop: '1.2rem', opacity: 0.92 }}>
            <li>Un score et un rapport SHAP pour chaque facture</li>
            <li>Quatre roles separes, controles cote serveur</li>
            <li>Donnees pseudonymisees, journal d audit complet</li>
          </ul>
        </div>
      </div>

      <form className="login-carte" onSubmit={soumettre} style={{
        background: 'rgba(255,255,255,0.92)',
        backdropFilter: 'blur(8px)',
        border: '1px solid rgba(255,255,255,0.3)',
        borderRadius: 'var(--rayon)',
        boxShadow: '0 12px 40px rgba(16,24,40,0.12)',
        padding: '1.6rem 1.5rem'
      }}>
        <h2 style={{ fontSize: '1.15rem', marginBottom: '0.2rem', letterSpacing: '-0.01em' }}>Connexion</h2>
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

        <div className="comptes-demo" style={{
          borderTop: '1px solid var(--bord)',
          marginTop: '1.4rem',
          paddingTop: '1.1rem',
          background: 'transparent'
        }}>
          <span className="champ-label" style={{ fontWeight: 700, color: 'var(--primaire-fonce)' }}>Comptes de demonstration</span>
          <ul style={{ listStyle: 'none', padding: 0, margin: '0.5rem 0' }}>
            {COMPTES_DEMO.map((compte) => (
              <li key={compte.email} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.35rem 0', fontSize: '0.85rem', borderBottom: '1px dashed var(--bord)' }}>
                <button
                  type="button"
                  className="lien"
                  onClick={() => setEmail(compte.email)}
                  style={{ fontWeight: 600, color: 'var(--primaire)', textDecoration: 'none', background: 'none', border: 'none', cursor: 'pointer', padding: '0.15rem 0.35rem', borderRadius: '6px', transition: 'background 0.15s ease' }}
                >
                  {compte.email}
                </button>
                <span style={{ color: 'var(--encre-douce)', fontSize: '0.78rem', fontWeight: 500 }}>{compte.role}</span>
              </li>
            ))}
          </ul>
          <p className="champ-aide" style={{ fontSize: '0.78rem', color: 'var(--encre-douce)', marginTop: '0.4rem', padding: '0.5rem 0.7rem', background: 'var(--info-clair)', borderRadius: '8px', borderLeft: '3px solid var(--info)' }}>
            Le mot de passe est celui choisi avec <code style={{ background: '#e2e6eb', padding: '0.05rem 0.35rem', borderRadius: '4px', fontSize: '0.85em' }}>DEMO_PASSWORD</code> au moment du seed.
          </p>
        </div>
      </form>
    </div>
  )
}
