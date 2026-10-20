import { useCallback, useEffect, useState } from 'react'

import { api, messageErreur } from '../api/client'
import type {
  AlertDetail,
  AlertSummary,
  Decision,
  DecisionRecord,
  PageResult,
} from '../api/types'
import { ShapList } from '../components/ShapList'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  EtatVide,
  Kpi,
  Pagination,
  Pastille,
  Succes,
  Vide,
  dateCourte,
  montant,
  pourcentage,
} from '../components/ui'

type Onglet = 'file' | 'historique'

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

export function ManagerPage() {
  const [onglet, setOnglet] = useState<Onglet>('file')

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

  const [historique, setHistorique] = useState<DecisionRecord[]>([])
  const [totalHistorique, setTotalHistorique] = useState(0)
  const [offsetHistorique, setOffsetHistorique] = useState(0)

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

  const chargerHistorique = useCallback((decalage: number) => {
    api<PageResult<DecisionRecord>>(
      `/api/core/alertes/historique?limit=${LIMITE}&offset=${decalage}`,
    )
      .then((page) => {
        setHistorique(page.items)
        setTotalHistorique(page.total)
        setOffsetHistorique(page.offset)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }, [])

  useEffect(() => {
    if (onglet !== 'historique') return
    chargerHistorique(0)
  }, [onglet, chargerHistorique])

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
  const exporterHistorique = () => {
    const entetes = ['decided_at', 'prediction_id', 'decision', 'score_fraude', 'commentaire']
    const lignes = historique.map((ligne) =>
      [
        ligne.decided_at,
        ligne.prediction_id,
        ligne.decision,
        String(ligne.score_fraude),
        ligne.commentaire ?? '',
      ]
        .map((valeur) => `"${String(valeur).replace(/"/g, '""')}"`)
        .join(';'),
    )
    const contenu = [entetes.join(';'), ...lignes].join('\r\n')
    const blob = new Blob([`﻿${contenu}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `decisions-${new Date().toISOString().slice(0, 10)}.csv`
    lien.click()
    URL.revokeObjectURL(url)
  }

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
    <div className="pile">
      <div className="titre-page">
        <h1>File d’alertes</h1>
        <p>
          Chaque alerte s’ouvre sur le rapport SHAP qui la justifie et sur les lignes de la
          facture source. La décision est motivée et tracée dans le journal.
        </p>
      </div>

      <div className="onglets" role="tablist" aria-label="File et historique">
        <button
          type="button"
          role="tab"
          id="onglet-file"
          aria-controls="panneau-file"
          aria-selected={onglet === 'file'}
          className={onglet === 'file' ? 'onglet actif' : 'onglet'}
          onClick={() => setOnglet('file')}
        >
          À traiter ({totalAlertes})
        </button>
        <button
          type="button"
          role="tab"
          id="onglet-historique"
          aria-controls="panneau-historique"
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
        <div
          id="panneau-file"
          role="tabpanel"
          aria-labelledby="onglet-file"
          className="pile"
        >
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
                  texte="Toutes les alertes au-dessus du seuil ont été traitées, ou le seuil est trop élevé. Elargissez les filtres, ou baissez le seuil depuis l’administration."
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
                <Vide>Sélectionnez une alerte pour voir son explication et ses lignes.</Vide>
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

                  <h3>Lignes de la facture</h3>
                  {selection.lignes.length === 0 ? (
                    <Vide>Aucune ligne de facture enregistrée pour ce dossier.</Vide>
                  ) : (
                    <div className="table-enveloppe">
                      <table className="table table-dense">
                        <caption className="visuellement-cache">
                          Lignes de la facture {selection.facture_id}
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

                  <h3>Pourquoi le modèle alerte</h3>
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
        </div>
      )}

      {onglet === 'historique' && (
        <div
          id="panneau-historique"
          role="tabpanel"
          aria-labelledby="onglet-historique"
          className="pile"
        >
          <Carte
            titre={`${totalHistorique} décision(s)`}
            actions={
              <div className="carte-actions">
                <button
                  type="button"
                  className="bouton discret"
                  onClick={exporterHistorique}
                  disabled={historique.length === 0}
                >
                  Exporter en CSV
                </button>
              </div>
            }
          >
            {historique.length === 0 && (
              <EtatVide
                titre="Aucune décision enregistrée"
                texte="Les décisions que vous prenez sur la file apparaîtront ici, avec leur motif."
              />
            )}
            {historique.length > 0 && (
              <>
                <div className="table-enveloppe">
                  <table className="table table-dense">
                    <caption className="visuellement-cache">
                      Historique des décisions du gestionnaire
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Alerte</th>
                        <th scope="col">Décision</th>
                        <th scope="col" className="droite">
                          Score
                        </th>
                        <th scope="col">Commentaire</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historique.map((ligne) => (
                        <tr key={`${ligne.prediction_id}-${ligne.decided_at}`}>
                          <td>{dateCourte(ligne.decided_at)}</td>
                          <td className="mono">{ligne.prediction_id}</td>
                          <td>
                            <Pastille
                              statut={
                                ligne.decision === 'valider_fraude'
                                  ? 'fraude_confirmee'
                                  : ligne.decision === 'rejeter'
                                    ? 'rejetée'
                                    : 'piece_demandee'
                              }
                            />
                          </td>
                          <td className="droite">{pourcentage(ligne.score_fraude)}</td>
                          <td>{ligne.commentaire ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination
                  total={totalHistorique}
                  offset={offsetHistorique}
                  limite={LIMITE}
                  onChange={chargerHistorique}
                  libelle="décisions"
                />
              </>
            )}
          </Carte>
        </div>
      )}
    </div>
  )
}
