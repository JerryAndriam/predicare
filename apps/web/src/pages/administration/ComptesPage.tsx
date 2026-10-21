import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../../api/client'
import { ROLE_LABELS, type AdminUser, type AdminUserCreate, type References, type Role } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { EnTetePage } from '../../components/blocs'
import { Badge, Bouton, Carte, Champ, Erreur, Succes, Vide, dateCourte } from '../../components/ui'

/**
 * Les comptes de la plateforme.
 *
 * Un compte porte un role, et selon ce role, un dossier assure ou un
 * code prestataire. La desactivation bloque la prochaine connexion sans
 * bloquer la prochaine connexion.
 */
export function ComptesPage() {
  const { profile } = useAuth()
  const [utilisateurs, setUtilisateurs] = useState<AdminUser[]>([])
  const [assures, setAssures] = useState<string[]>([])
  const [form, setForm] = useState({
    email: '',
    password: '',
    role: 'assure' as Role,
    display_name: '',
    assured_pseudonyme: '',
    prestataire_code: '',
  })
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  useEffect(() => {
    const charger = async () => {
      try {
        const [comptes, references] = await Promise.all([
          api<AdminUser[]>('/api/core/admin/utilisateurs'),
          api<References>('/api/core/factures/references'),
        ])
        setUtilisateurs(comptes)
        const pseudonymes = references.assures.map((valeur) => valeur.pseudonyme)
        setAssures(pseudonymes)
        setForm((precedent) => ({
          ...precedent,
          assured_pseudonyme: precedent.assured_pseudonyme || pseudonymes[0] || '',
        }))
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [])

  const creerCompte = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      const charge: AdminUserCreate = {
        email: form.email.trim(),
        password: form.password,
        role: form.role,
        display_name: form.display_name.trim() || undefined,
        assured_pseudonyme:
          form.role === 'assure' ? form.assured_pseudonyme : undefined,
        prestataire_code:
          form.role === 'professionnel_sante' ? form.prestataire_code.trim() : undefined,
      }
      await api<AdminUser>('/api/core/admin/utilisateurs', {
        method: 'POST',
        body: JSON.stringify(charge),
      })
      setSucces('Compte créé.')
      setForm({
        email: '',
        password: '',
        role: 'assure',
        display_name: '',
        assured_pseudonyme: assures[0] ?? '',
        prestataire_code: '',
      })
      setUtilisateurs(await api<AdminUser[]>('/api/core/admin/utilisateurs'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const changerStatut = async (compte: AdminUser) => {
    if (compte.is_active && !window.confirm(`Desactiver le compte ${compte.email} ?`)) {
      return
    }
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<AdminUser>(`/api/core/admin/utilisateurs/${compte.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !compte.is_active }),
      })
      setSucces(compte.is_active ? 'Compte désactivé.' : 'Compte activé.')
      setUtilisateurs(await api<AdminUser[]>('/api/core/admin/utilisateurs'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Comptes' },
        ]}
        titre="Comptes"
        chapo={
          <>
            Les comptes de la plateforme, leur rôle et leur état d’activation. Un compte
            créé ici est rattaché à un dossier assuré ou à un code prestataire, selon le
            rôle choisi. Une désactivation bloque la prochaine connexion.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <div className="grille deux-large">
        <Carte titre={`Comptes (${utilisateurs.length})`}>
          {utilisateurs.length === 0 ? (
            <Vide>Aucun compte. Créez le premier à droite.</Vide>
          ) : (
            <div className="table-enveloppe">
              <table className="table">
                <caption className="visuellement-cache">
                  Comptes utilisateurs, leur rôle et leur dernière connexion
                </caption>
                <thead>
                  <tr>
                    <th scope="col">E-mail</th>
                    <th scope="col">Rôle</th>
                    <th scope="col">Nom</th>
                    <th scope="col">Dossier</th>
                    <th scope="col">Prestataire</th>
                    <th scope="col">État</th>
                    <th scope="col">Dernière connexion</th>
                    <th scope="col">
                      <span className="visuellement-cache">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {utilisateurs.map((compte) => {
                    const estMoi = profile !== null && String(compte.id) === profile.subject
                    return (
                      <tr key={compte.id}>
                        <td className="mono">{compte.email}</td>
                        <td>{ROLE_LABELS[compte.role]}</td>
                        <td>{compte.display_name ?? '-'}</td>
                        <td className="mono">{compte.assured_pseudonyme ?? '-'}</td>
                        <td className="mono">{compte.prestataire_code ?? '-'}</td>
                        <td>
                          <Badge ton={compte.is_active ? 'ok' : 'neutre'}>
                            {compte.is_active ? 'actif' : 'désactivé'}
                          </Badge>
                        </td>
                        <td>{dateCourte(compte.last_login)}</td>
                        <td className="droite">
                          <Bouton
                            variante={compte.is_active ? 'danger' : 'contour'}
                            desactive={enCours || (estMoi && compte.is_active)}
                            titre={
                              estMoi && compte.is_active
                                ? 'Vous ne pouvez pas désactiver votre propre compte.'
                                : undefined
                            }
                            onClick={() => void changerStatut(compte)}
                          >
                            {compte.is_active ? 'Désactiver' : 'Activer'}
                          </Bouton>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="aide">
            La désactivation bloque la prochaine connexion. Une session déjà ouverte se
            termine à son échéance.
          </p>
        </Carte>

        <Carte titre="Nouveau compte">
          <form className="formulaire" onSubmit={creerCompte}>
            <Champ label="Adresse e-mail">
              <input
                type="email"
                required
                value={form.email}
                onChange={(event) =>
                  setForm((precedent) => ({ ...precedent, email: event.target.value }))
                }
                placeholder="prenom@predicare.local"
              />
            </Champ>

            <Champ
              label="Mot de passe"
              aide="Au moins 12 caractères. Choisissez une phrase longue et unique."
            >
              <input
                type="password"
                required
                minLength={12}
                maxLength={256}
                value={form.password}
                onChange={(event) =>
                  setForm((precedent) => ({ ...precedent, password: event.target.value }))
                }
              />
            </Champ>

            <Champ label="Rôle">
              <select
                value={form.role}
                onChange={(event) =>
                  setForm((precedent) => ({
                    ...precedent,
                    role: event.target.value as Role,
                  }))
                }
              >
                {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABELS[role]}
                  </option>
                ))}
              </select>
            </Champ>

            <Champ label="Nom affiché">
              <input
                type="text"
                maxLength={128}
                value={form.display_name}
                onChange={(event) =>
                  setForm((precedent) => ({
                    ...precedent,
                    display_name: event.target.value,
                  }))
                }
                placeholder="Optionnel"
              />
            </Champ>

            {form.role === 'assure' && (
              <Champ
                label="Dossier assuré"
                aide="Un compte assuré doit pointer vers un dossier existant."
              >
                {assures.length === 0 ? (
                  <p className="aide">
                    Aucun dossier disponible : lancez d’abord le seed des données.
                  </p>
                ) : (
                  <select
                    required
                    value={form.assured_pseudonyme}
                    onChange={(event) =>
                      setForm((precedent) => ({
                        ...precedent,
                        assured_pseudonyme: event.target.value,
                      }))
                    }
                  >
                    {assures.map((pseudonyme) => (
                      <option key={pseudonyme} value={pseudonyme}>
                        {pseudonyme}
                      </option>
                    ))}
                  </select>
                )}
              </Champ>
            )}

            {form.role === 'professionnel_sante' && (
              <Champ
                label="Prestataire"
                aide="Code du prestataire dont ce compte dépend (ex. PRE-00001). Il détermine les factures visibles."
              >
                <input
                  type="text"
                  required
                  maxLength={64}
                  value={form.prestataire_code}
                  onChange={(event) =>
                    setForm((precedent) => ({
                      ...precedent,
                      prestataire_code: event.target.value,
                    }))
                  }
                  placeholder="PRE-00001"
                />
              </Champ>
            )}

            <Bouton type="submit" variante="principal" desactive={enCours}>
              {enCours ? 'Création…' : 'Créer le compte'}
            </Bouton>
          </form>
        </Carte>
      </div>

    </>
  )
}
