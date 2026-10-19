import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import type {
  AuditEntry,
  ModelInfo,
  NotificationChannel,
  PlatformHealth,
} from '../api/types'
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

type Onglet = 'seuil' | 'modele' | 'sante' | 'canaux' | 'audit'

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

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Administration</h1>
        <p>
          Seuil, versions du modele, sante et journal. Aucun reglage ne demande de
          redemarrer un conteneur.
        </p>
      </div>

      <div className="onglets" role="tablist">
        {(
          [
            ['seuil', 'Seuil'],
            ['modele', 'Modele'],
            ['sante', 'Sante'],
            ['canaux', 'Canaux'],
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
