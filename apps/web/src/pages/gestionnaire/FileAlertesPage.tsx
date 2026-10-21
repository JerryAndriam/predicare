import { useCallback, useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { AlertDetail, AlertSummary, Decision, PageResult } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import { ShapList } from '../../components/ShapList'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  EtatVide,
  Kpi,
  Pagination,
  Succes,
  dateCourte,
  montant,
  pourcentage,
} from '../../components/ui'

const DECISIONS: { valeur: Decision; libelle: string }[] = [
  { valeur: 'valider_fraude', libelle: 'Confirmer la fraude' },
  { valeur: 'rejeter', libelle: 'Rejeter l’alerte (faux positif)' },
  { valeur: 'demander_piece', libelle: 'Demander une pièce justificative' },
]

/** Filtres de la file : ce que le gestionnaire cherche réellement. */
interface Filtres {
  assure: string
  montantMin: string
  montantMax: string
  scoreMin: string
}

const FILTRES_VIDES: Filtres = { assure: '', montantMin: '', montantMax: '', scoreMin: '' }

const LIMITE = 20

function queryAlertes(filtres: Filtres, offset: number): string {
  const params = new URLSearchParams({ limit: String(LIMITE), offset: String(offset) })
  if (filtres.assure.trim() !== '') params.set('assure', filtres.assure.trim())
  if (filtres.montantMin.trim() !== '') params.set('montant_min', filtres.montantMin.trim())
  if (filtres.montantMax.trim() !== '') params.set('montant_max', filtres.montantMax.trim())
  if (filtres.scoreMin.trim() !== '') params.set('score_min', filtres.scoreMin.trim())
  return params.toString()
}

export function FileAlertesPage() {
  const [alertes, setAlertes] = useState<AlertSummary[]>([])
  const [totalAlertes, setTotalAlertes] = useState(0)
  const [offset, setOffset] = useState(0)
  const [filtres, setFiltres] = useState<Filtres>(FILTRES_VIDES)
  const [chargement, setChargement] = useState(true)
  const [selection, setSelection] = useState<AlertDetail | null>(null)
  const [detailEnCours, setDetailEnCours] = useState(false)

  const [decision, setDecision] = useState<Decision>('valider_fraude')
  const [commentaire, setCommentaire] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCoursDecision, setEnCoursDecision] = useState(false)


  const chargerFile = useCallback(
    (decalage: number, filtresActifs: Filtres = filtres) => {
      setChargement(true)
      api<PageResult<AlertSummary>>(`/api/core/alertes/file?${queryAlertes(filtresActifs, decalage)}`)
        .then((page) => {
          setAlertes(page.items)
          setTotalAlertes(page.total)
          setOffset(page.offset)
        })
        .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
        .finally(() => setChargement(false))
    },
    [filtres],
  )

  useEffect(() => {
    chargerFile(0, FILTRES_VIDES)
    // La file est chargee une fois a l'ouverture ; les rechargements
    // passent par `chargerFile` (filtres, pagination, decision).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])



  const ouvrir = async (predictionId: string) => {
    setDetailEnCours(true)
    setErreur(null)
    setSucces(null)
    try {
      const detail = await api<AlertDetail>(`/api/core/alertes/detail/${predictionId}`)
      setSelection(detail)
      // Chaque dossier repart d'un formulaire neutre : sinon la décision et le
      // motif du dossier précédent restaient sélectionnés et pouvaient être
      // envoyés par inadvertence sur une autre alerte.
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
    if (enCoursDecision) return
    if (commentaire.trim().length < 3) {
      setErreur('Le commentaire est obligatoire (au moins 3 caractères).')
      return
    }
    if (
      decision === 'valider_fraude' &&
      !window.confirm(
        'Confirmer la fraude ? Cette décision engage le dossier et reste tracée dans le journal.',
      )
    ) {
      return
    }

    setErreur(null)
    setSucces(null)
    setEnCoursDecision(true)
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
      setSucces('Décision enregistrée et tracée dans le journal.')
      setSelection(null)
      setCommentaire('')
      chargerFile(offset)
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCoursDecision(false)
    }
  }

  /**
   * Export CSV de l'historique affiché.
   *
   * L'export porte sur ce que l'écran montre (page courante) : exporter
   * autre chose serait une surprise pour le lecteur.
   */

  const appliquerFiltres = () => {    setSelection(null)
    chargerFile(0, filtres)
  }

  const reinitialiserFiltres = () => {
    setFiltres(FILTRES_VIDES)
    setSelection(null)
    chargerFile(0, FILTRES_VIDES)
  }

  const scoreMax = alertes.length > 0 ? Math.max(...alertes.map((a) => a.score_fraude)) : null
  const montantTotal = alertes.reduce((somme, a) => somme + a.montant_total, 0)
  const ageMoyen =
    alertes.length > 0
      ? Math.round(alertes.reduce((somme, a) => somme + a.age_minutes, 0) / alertes.length)
      : 0


  return (
    <>
      <EnTetePage
        fil={[{ libelle: 'Espace gestionnaire', chemin: '/gestionnaire' }, { libelle: 'File d’alertes' }]}
        titre="File d’alertes"
        chapo={
          <>
            Les factures dont la note dépasse le seuil, triées de la plus suspecte à la
            moins suspecte. Chaque alerte s’ouvre sur l’explication de la note et sur les
            lignes de la facture source : la décision est motivée, puis conservée.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

          <div className="grille quatre">
            <Kpi titre="À traiter" valeur={totalAlertes} ton={totalAlertes > 0 ? 'alerte' : 'ok'} />
            <Kpi
              titre="Score maximum"
              valeur={scoreMax === null ? '—' : scoreMax.toFixed(3)}
              ton="alerte"
            />
            <Kpi titre="Montant en jeu" valeur={montant(montantTotal)} ton="avert" />
            <Kpi titre="Âge moyen" valeur={`${ageMoyen} min`} ton={ageMoyen > 120 ? 'avert' : 'neutre'} />
          </div>

          <Carte
            titre="Filtres de la file"
            actions={
              <div className="carte-actions">
                <button type="button" className="bouton discret" onClick={reinitialiserFiltres}>
                  Réinitialiser
                </button>
                <button type="button" className="bouton principal" onClick={appliquerFiltres}>
                  Appliquer
                </button>
              </div>
            }
          >
            <div className="grille quatre">
              <Champ label="Assuré (identifiant)">
                <input
                  value={filtres.assure}
                  placeholder="assr_…"
                  onChange={(event) =>
                    setFiltres((precedent) => ({ ...precedent, assure: event.target.value }))
                  }
                />
              </Champ>
              <Champ label="Montant minimum (Ar)">
                <input
                  type="number"
                  min={0}
                  value={filtres.montantMin}
                  onChange={(event) =>
                    setFiltres((precedent) => ({
                      ...precedent,
                      montantMin: event.target.value,
                    }))
                  }
                />
              </Champ>
              <Champ label="Montant maximum (Ar)">
                <input
                  type="number"
                  min={0}
                  value={filtres.montantMax}
                  onChange={(event) =>
                    setFiltres((precedent) => ({
                      ...precedent,
                      montantMax: event.target.value,
                    }))
                  }
                />
              </Champ>
              <Champ label="Score minimum">
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={filtres.scoreMin}
                  onChange={(event) =>
                    setFiltres((precedent) => ({
                      ...precedent,
                      scoreMin: event.target.value,
                    }))
                  }
                />
              </Champ>
            </div>
          </Carte>

          <div className="grille deux-large">
            <Carte
              titre={`Alertes au-dessus du seuil (${totalAlertes})`}
              actions={
                <button type="button" className="bouton discret" onClick={() => chargerFile(offset)}>
                  Rafraîchir
                </button>
              }
            >
              {chargement && <Chargement />}
              {!chargement && alertes.length === 0 && (
                <EtatVide
                  titre="Aucune alerte à traiter"
                  texte="Toutes les alertes au-dessus du seuil ont été traitées, ou le seuil est trop élevé. Élargissez les filtres, ou baissez le seuil depuis l’administration."
                />
              )}
              {alertes.length > 0 && (
                <>
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
                            {alerte.age_minutes > 60 && (
                              <span className="alerte-age">
                                {Math.round(alerte.age_minutes / 60)} h en file
                              </span>
                            )}
                          </span>
                          <Badge ton="alerte">À traiter</Badge>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <Pagination
                    total={totalAlertes}
                    offset={offset}
                    limite={LIMITE}
                    onChange={(decalage) => chargerFile(decalage)}
                    libelle="alertes"
                  />
                </>
              )}
            </Carte>

            <Carte titre="Détail et décision">
              {detailEnCours && <Chargement texte="Ouverture du dossier…" />}
              {!detailEnCours && selection === null && (
                <EtatVide
                  titre="Aucune alerte sélectionnée"
                  texte="Choisissez une alerte dans la file : son explication et ses lignes de facture s’afficheront ici."
                />
              )}
              {selection !== null && !detailEnCours && (
                <div className="detail-alerte">
                  <div className="entete-detail">
                    <div className="score-bloc">
                      <span className="score-valeur">{pourcentage(selection.score_fraude)}</span>
                      <span className="score-legende">note de vigilance</span>
                    </div>
                    <div className="resultat-meta">
                      <span className="mono">Facture {selection.facture_id}</span>
                      <span className="mono">{selection.assure_pseudonyme}</span>
                      <span>{montant(selection.montant_total)}</span>
                      <span>{dateCourte(selection.created_at)}</span>
                    </div>
                  </div>

                  <h3>Lignes de la facture</h3>
                  {selection.lignes.length === 0 ? (
                    <EtatVide
                      titre="Aucune ligne enregistrée"
                      texte="Ce dossier ne comporte aucune ligne de facture exploitable."
                    />
                  ) : (
                    <div className="table-enveloppe">
                      <table className="table table-dense">
                        <caption className="visuellement-cache">
                          Détail des lignes de la facture {selection.facture_id}
                        </caption>
                        <thead>
                          <tr>
                            <th scope="col">Acte</th>
                            <th scope="col">Quantité</th>
                            <th scope="col" className="droite">
                              Prix unitaire
                            </th>
                            <th scope="col" className="droite">
                              Total
                            </th>
                            <th scope="col">Ordonnance</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selection.lignes.map((ligne) => (
                            <tr key={ligne.code_acte}>
                              <td>
                                <span className="mono">{ligne.code_acte}</span>
                                <span className="aide">{ligne.libelle}</span>
                              </td>
                              <td>{ligne.quantite}</td>
                              <td className="droite">{montant(ligne.montant_unitaire)}</td>
                              <td className="droite">{montant(ligne.montant_total)}</td>
                              <td>
                                {ligne.prescrite ? (
                                  <Badge ton="ok">Prescrite</Badge>
                                ) : (
                                  <Badge ton="alerte">Non prescrite</Badge>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <h3>Ce qui a pesé dans la note</h3>
                  <ShapList contributions={selection.shap} />

                  <div className="formulaire">
                    <Champ label="Décision">
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
                      label="Motif de la décision"
                      aide="Obligatoire : il sera lu lors d’un contrôle et conservé dans le journal."
                    >
                      <textarea
                        rows={3}
                        minLength={3}
                        maxLength={2000}
                        value={commentaire}
                        onChange={(event) => setCommentaire(event.target.value)}
                        placeholder="Exemple : acte facturé deux fois le même jour, pièce demandée au prestataire."
                      />
                    </Champ>
                    <button
                      type="button"
                      className="bouton principal"
                      onClick={decider}
                      disabled={enCoursDecision}
                    >
                      {enCoursDecision ? 'Enregistrement…' : 'Enregistrer la décision'}
                    </button>
                  </div>
                </div>
              )}
            </Carte>
          </div>
    </>
  )
}
