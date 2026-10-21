import { useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import { ACCUEIL, ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { EnTetePage } from '../components/blocs'
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
      setSucces('Mot de passe modifié. Il sera demandé à la prochaine connexion.')
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
      <EnTetePage
        fil={[
          { libelle: 'Mon espace', chemin: profile === null ? '/' : ACCUEIL[profile.role] },
          { libelle: 'Mon compte' },
        ]}
        titre="Mon compte"
        chapo="Votre profil, votre rôle et votre dernière connexion. Le mot de passe se change ici."

      />

      <div className="grille deux-large">
        <Carte id="profil" titre="Profil" className="scroll-mt-24">
          <dl className="liste-definitions">
            <div>
              <dt>Nom</dt>
              <dd>{profile?.display_name ?? '-'}</dd>
            </div>
            <div>
              <dt>Rôle</dt>
              <dd>{profile === null ? '-' : ROLE_LABELS[profile.role]}</dd>
            </div>
            {profile?.assured_pseudonym != null && (
              <div>
                <dt>Dossier</dt>
                <dd className="mono">{profile.assured_pseudonym}</dd>
              </div>
            )}
            <div>
              <dt>Dernière connexion</dt>
              <dd>{profile?.last_login ?? '-'}</dd>
            </div>
          </dl>
        </Carte>

        <Carte id="mot-de-passe" titre="Changer le mot de passe" className="scroll-mt-24">
          <Erreur message={erreur} />
          <Succes message={succes} />
          <form className="formulaire" onSubmit={soumettre}>
            <Champ label="Mot de passe actuel" requis>
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
              aide="Au moins 12 caractères. Choisissez une phrase longue et unique."
              requis
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

            <Champ label="Confirmation" requis>
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
              {enCours ? 'Enregistrement…' : 'Changer le mot de passe'}
            </button>
          </form>
        </Carte>
      </div>
    </div>
  )
}
