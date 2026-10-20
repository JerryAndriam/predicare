import { useCallback, useEffect, useState } from 'react'

import { api, messageErreur } from '../api/client'
import type {
  AlertDetail,
  AlertSummary,
  Decision,
  DecisionRecord,
} from '../api/types'
import { ShapList } from '../components/ShapList'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  Succes,
  Vide,
  dateCourte,
  montant,
  pourcentage,
} from '../components/ui'

type Onglet = 'file' | 'historique'

const DECISIONS: { valeur: Decision; libelle: string }[] = [
  { valeur: 'valider_fraude', libelle: 'Confirmer la fraude' },
  { valeur: 'rejeter', libelle: 'Rejeter l alerte (faux positif)' },
  { valeur: 'demander_piece', libelle: 'Demander une piece justificative' },
]

export function ManagerPage() {
  const [onglet, setOnglet] = useState<Onglet>('file')

  const [alertes, setAlertes] = useState<AlertSummary[]>([])
  const [chargement, setChargement] = useState(true)
  const [selection, setSelection] = useState<AlertDetail | null>(null)
  const [detailEnCours, setDetailEnCours] = useState(false)

  const [decision, setDecision] = useState<Decision>('valider_fraude')
  const [commentaire, setCommentaire] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)

  const [historique, setHistorique] = useState<DecisionRecord[]>([])

  const chargerFile = useCallback(() => {
    setChargement(true)
    api<AlertSummary[]>('/api/core/alertes/file?statut=nouvelle&limit=100')
      .then(setAlertes)
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
      .finally(() => setChargement(false))
  }, [])

  useEffect(() => {
    chargerFile()
  }, [chargerFile])

  useEffect(() => {
    if (onglet !== 'historique') return
    api<DecisionRecord[]>('/api/core/alertes/historique?limit=200')
      .then(setHistorique)
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }, [onglet])

  const ouvrir = async (predictionId: string) => {
    setDetailEnCours(true)
    setErreur(null)
    setSucces(null)
    try {
      const detail = await api<AlertDetail>(`/api/core/alertes/detail/${predictionId}`)
      setSelection(detail)
      // Chaque dossier repart d'un formulaire neutre : sinon la decision et le
      // motif du dossier precedent restaient selectionnes et pouvaient etre
      // envoyes par inadvertance sur une autre alerte.
      setDecision('valider_fraude')
      setCommentaire('')
    } catch (probleme) {
      setErreur(messageErreur(probleme))
      setSelection(null)
    } finally {
      setDetailEnCours(false)
    }
  }

  const decider = async () => {
    if (selection === null) return
    if (commentaire.trim().length < 3) {
      setErreur('Le commentaire est obligatoire (au moins 3 caracteres).')
      return
    }
    if (
      decision === 'valider_fraude' &&
      !window.confirm(
        'Confirmer la fraude ? Cette decision engage le dossier et reste tracee dans le journal.',
      )
    ) {
      return
    }

    setErreur(null)
    setSucces(null)
    try {
      await api<{ status: string }>('/api/core/alertes/decision', {
        method: 'POST',
        body: JSON.stringify({
          prediction_id: selection.prediction_id,
          decision,
          commentaire: commentaire.trim(),
          decided_at: new Date().toISOString(),
        }),
      })
      setSucces('Decision enregistree.')
      setSelection(null)
      setCommentaire('')
      chargerFile()
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>File d alertes</h1>
        <p>
          Chaque alerte s ouvre sur le rapport SHAP qui la justifie. La decision est
          motivee et tracee dans le journal.
        </p>
      </div>

      <div className="onglets" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'file'}
          className={onglet === 'file' ? 'onglet actif' : 'onglet'}
          onClick={() => setOnglet('file')}
        >
          A traiter ({alertes.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'historique'}
          className={onglet === 'historique' ? 'onglet actif' : 'onglet'}
          onClick={() => setOnglet('historique')}
        >
          Historique
        </button>
      </div>

      <Erreur message={erreur} />
      <Succes message={succes} />

      {onglet === 'file' && (
        <div className="grille deux-large">
          <Carte
            titre="Alertes au-dessus du seuil"
            actions={
              <button type="button" className="bouton discret" onClick={chargerFile}>
                Rafraichir
              </button>
            }
          >
            {chargement && <Chargement />}
            {!chargement && alertes.length === 0 && (
              <Vide>Aucune alerte en attente. Le seuil est peut-etre eleve, ou tout est traite.</Vide>
            )}
            {alertes.length > 0 && (
              <ul className="liste-alertes">
                {alertes.map((alerte) => (
                  <li key={alerte.prediction_id}>
                    <button
                      type="button"
                      className={
                        selection?.prediction_id === alerte.prediction_id
                          ? 'alerte-item actif'
                          : 'alerte-item'
                      }
                      onClick={() => ouvrir(alerte.prediction_id)}
                    >
                      <span className="alerte-score">{pourcentage(alerte.score_fraude)}</span>
                      <span className="alerte-corps">
                        <strong>{montant(alerte.montant_total)}</strong>
                        <span className="mono">{alerte.assure_pseudonyme}</span>
                        <span className="alerte-date">{dateCourte(alerte.created_at)}</span>
                      </span>
                      <Badge ton="alerte">A traiter</Badge>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Carte>

          <Carte titre="Detail et decision">
            {detailEnCours && <Chargement texte="Ouverture du dossier..." />}
            {!detailEnCours && selection === null && (
              <Vide>Selectionnez une alerte pour voir son explication.</Vide>
            )}
            {selection !== null && !detailEnCours && (
              <div className="detail-alerte">
                <div className="entete-detail">
                  <div className="score-bloc">
                    <span className="score-valeur">{pourcentage(selection.score_fraude)}</span>
                    <span className="score-legende">score de fraude</span>
                  </div>
                  <div className="resultat-meta">
                    <span className="mono">Facture {selection.facture_id}</span>
                    <span className="mono">{selection.assure_pseudonyme}</span>
                    <span>{montant(selection.montant_total)}</span>
                    <span>{dateCourte(selection.created_at)}</span>
                  </div>
                </div>

                <h3>Pourquoi le modele alerte</h3>
                <ShapList contributions={selection.shap} />

                <div className="formulaire">
                  <Champ label="Decision">
                    <select
                      value={decision}
                      onChange={(event) => setDecision(event.target.value as Decision)}
                    >
                      {DECISIONS.map((choix) => (
                        <option key={choix.valeur} value={choix.valeur}>
                          {choix.libelle}
                        </option>
                      ))}
                    </select>
                  </Champ>
                  <Champ
                    label="Motif de la decision"
                    aide="Obligatoire : il sera lu lors d un controle et conserve dans le journal."
                  >
                    <textarea
                      rows={3}
                      minLength={3}
                      maxLength={2000}
                      value={commentaire}
                      onChange={(event) => setCommentaire(event.target.value)}
                      placeholder="Exemple : acte facture deux fois le meme jour, piece demandee au prestataire."
                    />
                  </Champ>
                  <button type="button" className="bouton principal" onClick={decider}>
                    Enregistrer la decision
                  </button>
                </div>
              </div>
            )}
          </Carte>
        </div>
      )}

      {onglet === 'historique' && (
        <Carte titre={`${historique.length} decision(s)`}>
          {historique.length === 0 && <Vide>Aucune decision enregistree.</Vide>}
          {historique.length > 0 && (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Alerte</th>
                    <th>Decision</th>
                    <th className="droite">Score</th>
                    <th>Commentaire</th>
                  </tr>
                </thead>
                <tbody>
                  {historique.map((ligne) => (
                    <tr key={`${ligne.prediction_id}-${ligne.decided_at}`}>
                      <td>{dateCourte(ligne.decided_at)}</td>
                      <td className="mono">{ligne.prediction_id}</td>
                      <td>{ligne.decision}</td>
                      <td className="droite">{pourcentage(ligne.score_fraude)}</td>
                      <td>{ligne.commentaire ?? '-'}</td>
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
