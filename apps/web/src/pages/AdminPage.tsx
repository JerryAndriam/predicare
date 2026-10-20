import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import {
  ROLE_LABELS,
  type AdminUser,
  type AdminUserCreate,
  type AuditEntry,
  type ModelInfo,
  type NotificationChannel,
  type PlatformHealth,
  type References,
  type Role,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { SchemaProjet } from '../components/SchemaProjet'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  Succes,
  Vide,
  dateCourte,
  pourcentage,
} from '../components/ui'

type Onglet = 'seuil' | 'modele' | 'sante' | 'canaux' | 'audit' | 'utilisateurs'

function tonSante(statut: string): 'ok' | 'alerte' | 'neutre' {
  if (statut === 'ok') return 'ok'
  if (statut === 'degraded') return 'alerte'
  return 'neutre'
}

export function AdminPage() {
  const [onglet, setOnglet] = useState<Onglet>('seuil')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const [seuil, setSeuil] = useState('')
  const [motif, setMotif] = useState('')

  const [modele, setModele] = useState<ModelInfo | null>(null)
  const [version, setVersion] = useState('')

  const [sante, setSante] = useState<PlatformHealth | null>(null)
  const [canaux, setCanaux] = useState<NotificationChannel[]>([])
  const [journal, setJournal] = useState<AuditEntry[]>([])

  const { profile } = useAuth()
  const [utilisateurs, setUtilisateurs] = useState<AdminUser[]>([])
  const [assures, setAssures] = useState<string[]>([])
  const [form, setForm] = useState({
    email: '',
    password: '',
    role: 'assure' as Role,
    display_name: '',
    assured_pseudonyme: '',
  })

  async function chargerModele() {
    const etat = await api<ModelInfo>('/api/core/admin/modele')
    setModele(etat)
    if (etat.active_version !== null) setVersion(etat.active_version)
  }

  useEffect(() => {
    setErreur(null)
    const charger = async () => {
      try {
        if (onglet === 'seuil') {
          const reponse = await api<{ seuil: number }>('/api/core/admin/seuil')
          setSeuil(String(reponse.seuil))
        }
        if (onglet === 'modele') await chargerModele()
        if (onglet === 'sante') {
          setSante(await api<PlatformHealth>('/api/core/admin/sante'))
        }
        if (onglet === 'canaux') {
          setCanaux(await api<NotificationChannel[]>('/api/core/admin/canaux'))
        }
        if (onglet === 'audit') {
          setJournal(await api<AuditEntry[]>('/api/core/audit/journal?limit=200'))
        }
        if (onglet === 'utilisateurs') {
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
        }
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [onglet])

  const enregistrerSeuil = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<{ status: string }>('/api/core/admin/seuil', {
        method: 'PUT',
        body: JSON.stringify({ seuil: Number(seuil), motif }),
      })
      setSucces('Seuil enregistre et pousse au service d inference.')
      setMotif('')
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const agirModele = async (chemin: string) => {
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<Record<string, unknown>>(chemin, { method: 'POST' })
      setSucces('Operation appliquee sur le registre de modeles.')
      await chargerModele()
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

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
      }
      await api<AdminUser>('/api/core/admin/utilisateurs', {
        method: 'POST',
        body: JSON.stringify(charge),
      })
      setSucces('Compte cree.')
      setForm({
        email: '',
        password: '',
        role: 'assure',
        display_name: '',
        assured_pseudonyme: assures[0] ?? '',
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
      setSucces(compte.is_active ? 'Compte desactive.' : 'Compte active.')
      setUtilisateurs(await api<AdminUser[]>('/api/core/admin/utilisateurs'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div className="pile">
      <div className="titre-page" style={{
        background: 'linear-gradient(160deg, #0e1a27 0%, #0f766e 70%, #0b5c56 100%)',
        color: '#fff',
        padding: '1.8rem 1.5rem 1.4rem',
        borderRadius: 'var(--rayon)',
        boxShadow: 'var(--ombre-levite)',
        marginBottom: '1.2rem',
        position: 'relative',
        overflow: 'hidden'
      }}>
        <h1 style={{ fontSize: '1.8rem', letterSpacing: '-0.03em', marginBottom: '0.2rem', color: '#fff' }}>Administration</h1>
        <p style={{ opacity: 0.9, maxWidth: '60ch', color: '#e8f0f6', marginBottom: '0.6rem' }}>
          Seuil, versions du modele, sante, comptes et journal. Aucun reglage ne
          demande de redemarrer un conteneur.
        </p>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.82rem', opacity: 0.8 }}>
          <span>Role : <strong style={{ color: '#2dd4bf' }}>Administrateur</strong></span>
          <span>Version : <strong style={{ color: '#2dd4bf' }}>2</strong></span>
          <span>Seuil : <strong style={{ color: '#2dd4bf' }}>28,76 %</strong></span>
        </div>
        <SchemaProjet />
      </div>

      <div className="onglets" role="tablist">
        {(
          [
            ['seuil', 'Seuil'],
            ['modele', 'Modele'],
            ['sante', 'Sante'],
            ['canaux', 'Canaux'],
            ['utilisateurs', 'Comptes'],
            ['audit', 'Journal'],
          ] as const
        ).map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            role="tab"
            aria-selected={onglet === cle}
            className={onglet === cle ? 'onglet actif' : 'onglet'}
            onClick={() => setOnglet(cle)}
          >
            {libelle}
          </button>
        ))}
      </div>

      <Erreur message={erreur} />
      <Succes message={succes} />

      {onglet === 'seuil' && (
        <Carte titre="Seuil de declenchement des alertes">
          <p className="aide">
            Une facture dont le score depasse ce seuil entre dans la file du gestionnaire.
            Un seuil plus bas augmente le rappel et le nombre de fausses alertes.
          </p>
          <form className="formulaire" onSubmit={enregistrerSeuil}>
            <div className="grille deux">
              <Champ label="Seuil (0 a 1)">
                <input
                  type="number"
                  min={0}
                  max={1}
                  step="0.001"
                  value={seuil}
                  onChange={(event) => setSeuil(event.target.value)}
                  required
                />
              </Champ>
              <Champ label="Motif du changement" aide="Trace dans le journal d audit.">
                <input
                  type="text"
                  minLength={3}
                  maxLength={500}
                  value={motif}
                  onChange={(event) => setMotif(event.target.value)}
                  placeholder="Exemple : arbitrage rappel / charge de travail"
                  required
                />
              </Champ>
            </div>
            <button type="submit" className="bouton principal" disabled={enCours}>
              {enCours ? 'Application...' : 'Appliquer le seuil'}
            </button>
          </form>
        </Carte>
      )}

      {onglet === 'modele' && (
        <div className="grille deux">
          <Carte titre="Registre des modeles">
            {modele === null ? (
              <Chargement />
            ) : (
              <div className="pile-serre">
                <div className="resultat-meta">
                  <Badge ton={modele.active_version === null ? 'alerte' : 'ok'}>
                    Active : {modele.active_version ?? 'aucune'}
                  </Badge>
                  <Badge ton="info">
                    Candidate : {modele.candidate_version ?? 'aucune'}
                  </Badge>
                  <span>Seuil : {pourcentage(modele.threshold)}</span>
                  <span>Charge : {dateCourte(modele.loaded_at)}</span>
                </div>

                <h3>Metriques de la version active</h3>
                {Object.keys(modele.metrics).length === 0 ? (
                  <Vide>Aucune metrique exposee.</Vide>
                ) : (
                  <ul className="liste-simple">
                    {Object.entries(modele.metrics).map(([cle, valeur]) => (
                      <li key={cle}>
                        <span className="mono">{cle}</span> : {String(valeur)}
                      </li>
                    ))}
                  </ul>
                )}

                <h3>Versions presentes sur le volume</h3>
                {modele.available_versions.length === 0 ? (
                  <Vide>
                    Aucune version sur /models. Lancez <code>make train VERSION=2</code>.
                  </Vide>
                ) : (
                  <p className="mono">{modele.available_versions.join(', ')}</p>
                )}
              </div>
            )}
          </Carte>

          <Carte titre="Deploiement sans interruption">
            <div className="formulaire">
              <Champ label="Version" aide="Un numero present sur le volume /models.">
                <input
                  type="text"
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                  placeholder="2"
                />
              </Champ>
              <div className="boutons-ligne">
                <button
                  type="button"
                  className="bouton"
                  disabled={enCours || version === ''}
                  onClick={() =>
                    void agirModele(
                      `/api/core/admin/modele/candidat?version=${encodeURIComponent(version)}`,
                    )
                  }
                >
                  Charger la candidate
                </button>
                <button
                  type="button"
                  className="bouton principal"
                  disabled={enCours}
                  onClick={() => void agirModele('/api/core/admin/modele/bascule')}
                >
                  Basculer sur la candidate
                </button>
                <button
                  type="button"
                  className="bouton danger"
                  disabled={enCours || version === ''}
                  onClick={() =>
                    void agirModele(
                      `/api/core/admin/modele/retour-arriere?version=${encodeURIComponent(version)}`,
                    )
                  }
                >
                  Revenir a cette version
                </button>
              </div>
              <p className="aide">
                Charger ne bascule pas : le modele en service continue de repondre pendant
                le chargement. C est la condition d un deploiement sans coupure.
              </p>
            </div>
          </Carte>
        </div>
      )}

      {onglet === 'sante' && (
        <Carte titre="Sante de la plateforme">
          {sante === null ? (
            <Chargement />
          ) : (
            <div className="pile-serre">
              <div className="grille trois">
                <div className="sonde">
                  <span className="champ-label">Base de donnees</span>
                  <Badge ton={sante.dependances.base ? 'ok' : 'alerte'}>
                    {sante.dependances.base ? 'ok' : 'indisponible'}
                  </Badge>
                </div>
                <div className="sonde">
                  <span className="champ-label">Service d inference</span>
                  <Badge ton={tonSante(sante.dependances.inference.status)}>
                    {sante.dependances.inference.status}
                  </Badge>
                  <span className="mono">{sante.dependances.inference.version ?? '-'}</span>
                </div>
                <div className="sonde">
                  <span className="champ-label">Assistant RAG</span>
                  <Badge ton={tonSante(sante.dependances.rag.status)}>
                    {sante.dependances.rag.status}
                  </Badge>
                  <span className="mono">{sante.dependances.rag.version ?? '-'}</span>
                </div>
              </div>

              <p className="aide">
                api-core {sante.version} - seuil {pourcentage(sante.seuil)} - sonde du{' '}
                {dateCourte(sante.timestamp)}
              </p>

              <h3>Secrets manquants</h3>
              {sante.secrets_manquants.length === 0 ? (
                <p>Configuration complete.</p>
              ) : (
                <ul className="liste-simple">
                  {sante.secrets_manquants.map((secret) => (
                    <li key={secret} className="mono">
                      {secret}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Carte>
      )}

      {onglet === 'canaux' && (
        <Carte titre="Canaux de notification">
          {canaux.length === 0 ? (
            <Chargement />
          ) : (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Nom</th>
                    <th>Type</th>
                    <th>Actif</th>
                    <th>Destinataire</th>
                  </tr>
                </thead>
                <tbody>
                  {canaux.map((canal) => (
                    <tr key={canal.nom}>
                      <td>{canal.nom}</td>
                      <td>{canal.type}</td>
                      <td>
                        <Badge ton={canal.actif ? 'ok' : 'neutre'}>
                          {canal.actif ? 'actif' : 'inactif'}
                        </Badge>
                      </td>
                      <td className="mono">{canal.destinataire}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="aide">
            Le webhook Slack et l adresse d envoi viennent de la configuration du service.
            Un destinataire « non-configure » signifie que le canal ne peut pas alerter.
          </p>
        </Carte>
      )}

      {onglet === 'utilisateurs' && (
        <div className="grille deux-large">
          <Carte titre={`Comptes (${utilisateurs.length})`}>
            {utilisateurs.length === 0 ? (
              <Vide>Aucun compte. Creez le premier a droite.</Vide>
            ) : (
              <div className="table-enveloppe">
                <table className="table">
                  <thead>
                    <tr>
                      <th>E-mail</th>
                      <th>Role</th>
                      <th>Nom</th>
                      <th>Dossier</th>
                      <th>Etat</th>
                      <th>Derniere connexion</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {utilisateurs.map((compte) => {
                      const estMoi =
                        profile !== null && String(compte.id) === profile.subject
                      return (
                        <tr key={compte.id}>
                          <td className="mono">{compte.email}</td>
                          <td>{ROLE_LABELS[compte.role]}</td>
                          <td>{compte.display_name ?? '-'}</td>
                          <td className="mono">{compte.assured_pseudonyme ?? '-'}</td>
                          <td>
                            <Badge ton={compte.is_active ? 'ok' : 'neutre'}>
                              {compte.is_active ? 'actif' : 'desactive'}
                            </Badge>
                          </td>
                          <td>{dateCourte(compte.last_login)}</td>
                          <td className="droite">
                            <button
                              type="button"
                              className={compte.is_active ? 'bouton danger' : 'bouton'}
                              disabled={enCours || (estMoi && compte.is_active)}
                              title={
                                estMoi && compte.is_active
                                  ? 'Vous ne pouvez pas desactiver votre propre compte.'
                                  : undefined
                              }
                              onClick={() => void changerStatut(compte)}
                            >
                              {compte.is_active ? 'Desactiver' : 'Activer'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="aide">
              La desactivation bloque la prochaine connexion. Un jeton deja emis reste
              valide jusqu a son expiration.
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
                aide="Au moins 12 caracteres. Il est hache (Argon2id) avant l enregistrement."
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

              <Champ label="Role">
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

              <Champ label="Nom affiche">
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
                  label="Dossier assure"
                  aide="Un compte assure doit pointer vers un dossier existant."
                >
                  {assures.length === 0 ? (
                    <p className="aide">
                      Aucun dossier disponible : lancez d abord le seed des donnees.
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

              <button type="submit" className="bouton principal" disabled={enCours}>
                {enCours ? 'Creation...' : 'Creer le compte'}
              </button>
            </form>
          </Carte>
        </div>
      )}

      {onglet === 'audit' && (
        <Carte titre={`Journal d audit (${journal.length} entrees)`}>
          {journal.length === 0 ? (
            <Vide>Aucune entree pour le moment.</Vide>
          ) : (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Acteur</th>
                    <th>Role</th>
                    <th>Action</th>
                    <th>Cible</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.map((entree) => (
                    <tr key={entree.id}>
                      <td>{dateCourte(entree.created_at)}</td>
                      <td className="mono">{entree.acteur}</td>
                      <td>{entree.role}</td>
                      <td>{entree.action}</td>
                      <td className="mono">{entree.cible ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Carte>
      )}
    </div>
  )
}
