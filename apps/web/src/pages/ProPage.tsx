import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import type {
  InvoiceInput,
  InvoiceSummary,
  Page,
  Prediction,
  References,
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

type Onglet = 'depot' | 'suivi' | 'ordonnance'

interface LigneForm {
  code_acte: string
  quantite: number
  montant_unitaire: number
  date_acte: string
}

function maintenantLocal(): string {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

export function ProPage() {
  const [onglet, setOnglet] = useState<Onglet>('depot')
  const [references, setReferences] = useState<References | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  const [assure, setAssure] = useState('')
  const [prestataire, setPrestataire] = useState('')
  const [dateFacture, setDateFacture] = useState(maintenantLocal())
  const [lignes, setLignes] = useState<LigneForm[]>([])
  const [resultat, setResultat] = useState<Prediction | null>(null)

  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [chargementSuivi, setChargementSuivi] = useState(true)

  const [ordonnance, setOrdonnance] = useState({
    code_acte: '',
    date_ordonnance: maintenantLocal(),
    quantite: 1,
  })

  const chargerSuivi = () => {
    setChargementSuivi(true)
    api<Page<InvoiceSummary>>('/api/core/factures?limit=100')
      .then((page) => setFactures(page.items))
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
      .finally(() => setChargementSuivi(false))
  }

  useEffect(() => {
    api<References>('/api/core/factures/references')
      .then((valeurs) => {
        setReferences(valeurs)
        if (valeurs.assures.length > 0) setAssure(valeurs.assures[0].pseudonyme)
        if (valeurs.prestataires.length > 0) setPrestataire(valeurs.prestataires[0].code)
        const premier = valeurs.actes[0]
        if (premier !== undefined) {
          setLignes([
            {
              code_acte: premier.code,
              quantite: 1,
              montant_unitaire: premier.prix_unitaire,
              date_acte: maintenantLocal(),
            },
          ])
          setOrdonnance((precedent) => ({ ...precedent, code_acte: premier.code }))
        }
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
    chargerSuivi()
  }, [])

  const total = lignes.reduce(
    (somme, ligne) => somme + ligne.quantite * ligne.montant_unitaire,
    0,
  )

  const changerActe = (index: number, code: string) => {
    const acte = references?.actes.find((valeur) => valeur.code === code)
    setLignes((precedent) =>
      precedent.map((ligne, position) =>
        position === index
          ? {
              ...ligne,
              code_acte: code,
              montant_unitaire: acte !== undefined ? acte.prix_unitaire : ligne.montant_unitaire,
            }
          : ligne,
      ),
    )
  }

  const ajouterLigne = () => {
    const premier = references?.actes[0]
    setLignes((precedent) => [
      ...precedent,
      {
        code_acte: premier?.code ?? '',
        quantite: 1,
        montant_unitaire: premier?.prix_unitaire ?? 0,
        date_acte: dateFacture,
      },
    ])
  }

  const retirerLigne = (index: number) => {
    setLignes((precedent) => precedent.filter((_, position) => position !== index))
  }

  const soumettre = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)

    const probleme =
      assure === ''
        ? 'Choisissez un assure.'
        : prestataire === ''
          ? 'Choisissez un prestataire.'
          : lignes.length === 0
            ? 'Ajoutez au moins une ligne de facture.'
            : lignes.some((ligne) => ligne.code_acte === '')
              ? 'Chaque ligne doit reference un acte.'
              : total > 10_000_000
                ? 'Le montant total depasse le plafond accepte (10 000 000).'
                : null

    if (probleme !== null) {
      setErreur(probleme)
      return
    }

    const charge: InvoiceInput = {
      assure_pseudonyme: assure,
      prestataire_id: prestataire,
      date_facture: new Date(dateFacture).toISOString(),
      montant_total: total,
      lignes: lignes.map((ligne) => ({
        code_acte: ligne.code_acte,
        quantite: ligne.quantite,
        montant_unitaire: ligne.montant_unitaire,
        date_acte: new Date(ligne.date_acte).toISOString(),
      })),
    }

    setEnvoi(true)
    try {
      const prediction = await api<Prediction>('/api/core/factures/soumettre', {
        method: 'POST',
        body: JSON.stringify(charge),
      })
      setResultat(prediction)
      setSucces(`Facture ${prediction.facture_id} enregistree et notee par le modele.`)
      chargerSuivi()
    } catch (problemeTechnique) {
      setErreur(messageErreur(problemeTechnique))
      setResultat(null)
    } finally {
      setEnvoi(false)
    }
  }

  const soumettreOrdonnance = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnvoi(true)
    try {
      await api<{ status: string }>('/api/core/factures/ordonnances', {
        method: 'POST',
        body: JSON.stringify({
          assure_pseudonyme: assure,
          prestataire_id: prestataire,
          code_acte: ordonnance.code_acte,
          date_ordonnance: new Date(ordonnance.date_ordonnance).toISOString(),
          quantite: ordonnance.quantite,
        }),
      })
      setSucces('Ordonnance enregistree.')
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Espace professionnel de sante</h1>
        <p>Depot des factures et des ordonnances, puis suivi des dossiers.</p>
      </div>

      <div className="onglets" role="tablist">
        {(
          [
            ['depot', 'Deposer une facture'],
            ['suivi', 'Suivi des dossiers'],
            ['ordonnance', 'Ordonnance'],
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

      {onglet === 'depot' && (
        <div className="grille deux-large">
          <Carte titre="Nouvelle facture">
            {references === null ? (
              <Chargement texte="Chargement des referentiels..." />
            ) : (
              <form className="formulaire" onSubmit={soumettre} style={{ background: 'rgba(255,255,255,0.5)', padding: '1.2rem', borderRadius: 'var(--rayon)', border: '1px solid var(--bord)' }}>
                <div className="grille deux">
                  <Champ label="Assure (pseudonyme)">
                    <select value={assure} onChange={(event) => setAssure(event.target.value)}>
                      {references.assures.map((valeur) => (
                        <option key={valeur.pseudonyme} value={valeur.pseudonyme}>
                          {valeur.pseudonyme}
                        </option>
                      ))}
                    </select>
                  </Champ>
                  <Champ label="Prestataire">
                    <select
                      value={prestataire}
                      onChange={(event) => setPrestataire(event.target.value)}
                    >
                      {references.prestataires.map((valeur) => (
                        <option key={valeur.code} value={valeur.code}>
                          {valeur.code} - {valeur.nom}
                        </option>
                      ))}
                    </select>
                  </Champ>
                </div>

                <Champ label="Date de la facture">
                  <input
                    type="datetime-local"
                    value={dateFacture}
                    onChange={(event) => setDateFacture(event.target.value)}
                    required
                  />
                </Champ>

                <div className="lignes-entete">
                  <h3>Lignes</h3>
                  <button type="button" className="bouton discret" onClick={ajouterLigne}>
                    Ajouter une ligne
                  </button>
                </div>

                {lignes.map((ligne, index) => (
                  <div className="ligne-facture" key={index}>
                    <select
                      value={ligne.code_acte}
                      onChange={(event) => changerActe(index, event.target.value)}
                      aria-label="Acte"
                    >
                      {references.actes.map((acte) => (
                        <option key={acte.code} value={acte.code}>
                          {acte.code} - {acte.libelle}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={1}
                      max={999}
                      value={ligne.quantite}
                      aria-label="Quantite"
                      onChange={(event) =>
                        setLignes((precedent) =>
                          precedent.map((valeur, position) =>
                            position === index
                              ? { ...valeur, quantite: Number(event.target.value) }
                              : valeur,
                          ),
                        )
                      }
                    />
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={ligne.montant_unitaire}
                      aria-label="Montant unitaire"
                      onChange={(event) =>
                        setLignes((precedent) =>
                          precedent.map((valeur, position) =>
                            position === index
                              ? { ...valeur, montant_unitaire: Number(event.target.value) }
                              : valeur,
                          ),
                        )
                      }
                    />
                    <input
                      type="datetime-local"
                      value={ligne.date_acte}
                      aria-label="Date de l acte"
                      onChange={(event) =>
                        setLignes((precedent) =>
                          precedent.map((valeur, position) =>
                            position === index
                              ? { ...valeur, date_acte: event.target.value }
                              : valeur,
                          ),
                        )
                      }
                    />
                    <button
                      type="button"
                      className="bouton danger"
                      onClick={() => retirerLigne(index)}
                      disabled={lignes.length === 1}
                    >
                      Retirer
                    </button>
                  </div>
                ))}

                <p className="total">
                  Montant total calcule : <strong>{montant(total)}</strong>
                </p>

                <button type="submit" className="bouton principal large" disabled={envoi}>
                  {envoi ? 'Envoi et notation...' : 'Envoyer et noter la facture'}
                </button>
              </form>
            )}
          </Carte>

          <Carte titre="Resultat de la notation">
            {resultat === null ? (
              <Vide>
                Le score, le seuil applique et le rapport SHAP s afficheront ici apres l envoi.
              </Vide>
            ) : (
              <div className="resultat">
                <div className="score-bloc">
                  <span className="score-valeur">{pourcentage(resultat.score_fraude)}</span>
                  <span className="score-legende">score de fraude</span>
                </div>
                <div className="resultat-meta">
                  <Badge ton={resultat.is_fraud ? 'alerte' : 'ok'}>
                    {resultat.is_fraud ? 'Au-dessus du seuil - alerte' : 'Sous le seuil'}
                  </Badge>
                  <span>Seuil : {pourcentage(resultat.seuil_applique)}</span>
                  <span>Modele : {resultat.model_version}</span>
                  <span>{resultat.inference_ms.toFixed(1)} ms</span>
                </div>
                <h3>Explication SHAP</h3>
                <ShapList contributions={resultat.shap} />
              </div>
            )}
          </Carte>
        </div>
      )}

      {onglet === 'suivi' && (
        <Carte titre={`${factures.length} dossier(s)`}>
          {chargementSuivi && <Chargement />}
          {!chargementSuivi && factures.length === 0 && <Vide>Aucun dossier depose.</Vide>}
          {factures.length > 0 && (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Assure</th>
                    <th>Prestataire</th>
                    <th className="droite">Montant</th>
                    <th className="droite">Score</th>
                    <th>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {factures.map((facture) => (
                    <tr key={facture.facture_id}>
                      <td>{dateCourte(facture.date_facture)}</td>
                      <td className="mono">{facture.assure_pseudonyme}</td>
                      <td className="mono">{facture.prestataire_id}</td>
                      <td className="droite">{montant(facture.montant_total)}</td>
                      <td className="droite">
                        {facture.score_fraude === null
                          ? '-'
                          : pourcentage(facture.score_fraude)}
                      </td>
                      <td>{facture.statut}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Carte>
      )}

      {onglet === 'ordonnance' && (
        <Carte titre="Deposer une ordonnance">
          {references === null ? (
            <Chargement />
          ) : (
            <form className="formulaire" onSubmit={soumettreOrdonnance}>
              <div className="grille deux">
                <Champ label="Assure (pseudonyme)">
                  <select value={assure} onChange={(event) => setAssure(event.target.value)}>
                    {references.assures.map((valeur) => (
                      <option key={valeur.pseudonyme} value={valeur.pseudonyme}>
                        {valeur.pseudonyme}
                      </option>
                    ))}
                  </select>
                </Champ>
                <Champ label="Prestataire">
                  <select
                    value={prestataire}
                    onChange={(event) => setPrestataire(event.target.value)}
                  >
                    {references.prestataires.map((valeur) => (
                      <option key={valeur.code} value={valeur.code}>
                        {valeur.code} - {valeur.nom}
                      </option>
                    ))}
                  </select>
                </Champ>
                <Champ label="Acte prescrit">
                  <select
                    value={ordonnance.code_acte}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        code_acte: event.target.value,
                      }))
                    }
                  >
                    {references.actes.map((acte) => (
                      <option key={acte.code} value={acte.code}>
                        {acte.code} - {acte.libelle}
                      </option>
                    ))}
                  </select>
                </Champ>
                <Champ label="Date de l ordonnance">
                  <input
                    type="datetime-local"
                    value={ordonnance.date_ordonnance}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        date_ordonnance: event.target.value,
                      }))
                    }
                  />
                </Champ>
                <Champ label="Quantite">
                  <input
                    type="number"
                    min={1}
                    max={999}
                    value={ordonnance.quantite}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        quantite: Number(event.target.value),
                      }))
                    }
                  />
                </Champ>
              </div>
              <button type="submit" className="bouton principal" disabled={envoi}>
                {envoi ? 'Enregistrement...' : 'Enregistrer l ordonnance'}
              </button>
            </form>
          )}
        </Carte>
      )}
    </div>
  )
}
