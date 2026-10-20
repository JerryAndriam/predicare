import { useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import { ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Carte, Champ, Erreur, Succes } from '../components/ui'

export function AccountPage() {
  const { profile } = useAuth()
  const [ancien, setAncien] = useState('')
  const [nouveau, setNouveau] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const soumettre = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)

    if (nouveau.length < 12) {
      setErreur('Le nouveau mot de passe doit contenir au moins 12 caractères.')
      return
    }
    if (nouveau !== confirmation) {
      setErreur('La confirmation ne correspond pas au nouveau mot de passe.')
      return
    }

    setEnCours(true)
    try {
      await api<{ status: string }>('/api/core/auth/password', {
        method: 'POST',
        body: JSON.stringify({ old_password: ancien, new_password: nouveau }),
      })
      setSucces('Mot de passe modifié. Il sera demande a la prochaine connexion.')
      setAncien('')
      setNouveau('')
      setConfirmation('')
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Mon compte</h1>
        <p>Profil et changement de mot de passe.</p>
      </div>

      <div className="grille deux-large">
        <Carte titre="Profil">
          <ul className="liste-simple">
            <li>
              <span className="champ-label">Nom</span> : {profile?.display_name ?? '-'}
            </li>
            <li>
              <span className="champ-label">Rôle</span> :{' '}
              {profile === null ? '-' : ROLE_LABELS[profile.role]}
            </li>
            {profile?.assured_pseudonym != null && (
              <li>
                <span className="champ-label">Dossier</span> :{' '}
                <span className="mono">{profile.assured_pseudonym}</span>
              </li>
            )}
            <li>
              <span className="champ-label">Dernière connexion</span> :{' '}
              {profile?.last_login ?? '-'}
            </li>
          </ul>
        </Carte>

        <Carte titre="Changer le mot de passe">
          <Erreur message={erreur} />
          <Succes message={succes} />
          <form className="formulaire" onSubmit={soumettre}>
            <Champ label="Mot de passe actuel">
              <input
                type="password"
                required
                maxLength={256}
                autoComplete="current-password"
                value={ancien}
                onChange={(event) => setAncien(event.target.value)}
              />
            </Champ>

            <Champ
              label="Nouveau mot de passe"
              aide="Au moins 12 caracteres. Il est hache (Argon2id) avant enregistrement."
            >
              <input
                type="password"
                required
                minLength={12}
                maxLength={256}
                autoComplete="new-password"
                value={nouveau}
                onChange={(event) => setNouveau(event.target.value)}
              />
            </Champ>

            <Champ label="Confirmation">
              <input
                type="password"
                required
                maxLength={256}
                autoComplete="new-password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </Champ>

            <button type="submit" className="bouton principal" disabled={enCours}>
              {enCours ? 'Enregistrement...' : 'Changer le mot de passe'}
            </button>
          </form>
        </Carte>
      </div>
    </div>
  )
}
