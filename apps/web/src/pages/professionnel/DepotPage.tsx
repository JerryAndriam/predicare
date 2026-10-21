import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../../api/client'
import type { InvoiceInput, Prediction, References } from '../../api/types'
import { ShapList } from '../../components/ShapList'
import { EnTetePage } from '../../components/blocs'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  EtatVide,
  Succes,
  montant,
  pourcentage,
} from '../../components/ui'

interface LigneForm {
  code_acte: string
  quantite: number
  montant_unitaire: number
  date_acte: string
}

/** Plafond du montant total d'une facture, verifie cote client. */
const PLAFOND_FACTURE = 10_000_000

function maintenantLocal(): string {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

/**
 * Le depot d'une facture.
 *
 * Le formulaire reproduit a l'identique les regles de saisie : les
 * references viennent du serveur, le montant total est recalcule a partir
 * des lignes, et la validation avant envoi est celle d'origine. La page
 * affiche a cote le resultat de la notation : score, seuil applique,
 * version du modele et rapport SHAP.
 */
export function DepotPage() {
  const [references, setReferences] = useState<References | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  const [assure, setAssure] = useState('')
  const [prestataire, setPrestataire] = useState('')
  const [dateFacture, setDateFacture] = useState(maintenantLocal())
  const [lignes, setLignes] = useState<LigneForm[]>([])
  const [resultat, setResultat] = useState<Prediction | null>(null)

  useEffect(() => {
    api<References>('/api/core/factures/references')
      .then((valeurs) => {
        setReferences(valeurs)
        if (valeurs.assures.length > 0) setAssure(valeurs.assures[0].pseudonyme)
        const propre = valeurs.prestataire_du_compte ?? null
        if (propre !== null) setPrestataire(propre)
        else if (valeurs.prestataires.length > 0) setPrestataire(valeurs.prestataires[0].code)
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
        }
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
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
        ? 'Choisissez un assuré.'
        : prestataire === ''
          ? 'Choisissez un prestataire.'
          : lignes.length === 0
            ? 'Ajoutez au moins une ligne de facture.'
            : lignes.some((ligne) => ligne.code_acte === '')
              ? 'Chaque ligne doit référencer un acte.'
              : total > PLAFOND_FACTURE
                ? 'Le montant total dépasse le plafond accepté (10 000 000).'
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
      setSucces(`Facture ${prediction.facture_id} enregistrée et notée.`)
    } catch (problemeTechnique) {
      setErreur(messageErreur(problemeTechnique))
      setResultat(null)
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div className="pile">
      <EnTetePage
        fil={[
          { libelle: 'Espace professionnel de santé', chemin: '/professionnel' },
          { libelle: 'Déposer une facture' },
        ]}
        titre="Déposer une facture"
        chapo={
          <>
            Saisissez les lignes de l’acte réalisé : la facture est vérifiée, notée,
            puis expliquée champ par champ. Le prestataire rattaché à votre compte est
            repris automatiquement.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <div className="grille deux-large">
        <Carte titre="Nouvelle facture">
          {references === null ? (
            <Chargement texte="Chargement des référentiels..." />
          ) : (
            <form className="formulaire" onSubmit={soumettre}>
              <div className="grille deux">
                <Champ label="Dossier de l’assuré">
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
                    disabled={references.prestataire_du_compte != null}
                  >
                    {references.prestataires.map((valeur) => (
                      <option key={valeur.code} value={valeur.code}>
                        {valeur.code} - {valeur.nom}
                      </option>
                    ))}
                  </select>
                </Champ>
              </div>
              {references.prestataire_du_compte != null && (
                <p className="aide">
                  Votre compte est rattaché à {references.prestataire_du_compte} : le
                  prestataire est repris automatiquement.
                </p>
              )}

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
                    aria-label="Code acte"
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
                    aria-label="Quantité"
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
                    aria-label="Date de l’acte"
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
                Montant total calculé : <strong>{montant(total)}</strong>
              </p>

              <button type="submit" className="bouton principal large" disabled={envoi}>
                {envoi ? 'Envoi et notation...' : 'Envoyer et noter la facture'}
              </button>
            </form>
          )}
        </Carte>

        <Carte titre="Résultat de la notation">
          {resultat === null ? (
            <EtatVide
              titre="Aucune facture notée pour l’instant"
              texte="La note, le seuil appliqué et son explication s’afficheront ici après l’envoi."
            />
          ) : (
            <div className="resultat">
              <div className="score-bloc">
                <span className="score-valeur">{pourcentage(resultat.score_fraude)}</span>
                <span className="score-legende">note de vigilance</span>
              </div>
              <div className="resultat-meta">
                <Badge ton={resultat.is_fraud ? 'alerte' : 'ok'}>
                  {resultat.is_fraud ? 'Au-dessus du seuil - alerte' : 'Sous le seuil'}
                </Badge>
                <span>Seuil : {pourcentage(resultat.seuil_applique)}</span>
              </div>
              {resultat.notification !== undefined && (
                <p
                  className={resultat.notification.envoye ? 'succes' : 'aide'}
                  role="status"
                >
                  {resultat.notification.envoye ? '✓ ' : 'ℹ '}
                  {resultat.notification.message}
                </p>
              )}
              <h3>Ce qui a pesé dans la note</h3>
              <ShapList contributions={resultat.shap} />
            </div>
          )}
        </Carte>
      </div>

    </div>
  )
}
