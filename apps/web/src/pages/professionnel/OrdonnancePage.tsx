import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../../api/client'
import type { References } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import {
  Carte,
  Champ,
  Chargement,
  Erreur,
  Succes,
} from '../../components/ui'

function maintenantLocal(): string {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

/**
 * Le depot d'une ordonnance.
 *
 * L'ordonnance complete un dossier : elle est rapprochee des lignes de la
 * facture pour verifier que l'acte prescrit correspond a ce qui a ete
 * facture. Les regles de saisie et de refus sont celles du serveur : la
 * page ne fait que les lui transmettre.
 */
export function OrdonnancePage() {
  const [references, setReferences] = useState<References | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  const [assure, setAssure] = useState('')
  const [prestataire, setPrestataire] = useState('')
  const [ordonnance, setOrdonnance] = useState({
    code_acte: '',
    date_ordonnance: maintenantLocal(),
    quantite: 1,
    reference: '',
    diagnostic: '',
    validite_jours: 30,
  })

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
          setOrdonnance((precedent) => ({ ...precedent, code_acte: premier.code }))
        }
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }, [])

  const soumettreOrdonnance = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnvoi(true)
    try {
      const reponse = await api<{ status: string; reference: string }>(
        '/api/core/factures/ordonnances',
        {
          method: 'POST',
          body: JSON.stringify({
            assure_pseudonyme: assure,
            prestataire_id: prestataire,
            code_acte: ordonnance.code_acte,
            date_ordonnance: new Date(ordonnance.date_ordonnance).toISOString(),
            quantite: ordonnance.quantite,
            reference: ordonnance.reference.trim() || undefined,
            diagnostic: ordonnance.diagnostic.trim() || undefined,
            validite_jours: ordonnance.validite_jours,
          }),
        },
      )
      setSucces(`Ordonnance enregistrée (${reponse.reference}).`)
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div className="pile">
      <EnTetePage
        fil={[
          { libelle: 'Espace professionnel de santé', chemin: '/professionnel' },
          { libelle: 'Déposer une ordonnance' },
        ]}
        titre="Déposer une ordonnance"
        chapo={
          <>
            Transmettez une ordonnance pour compléter un dossier : elle est
            rapprochée des lignes de la facture, et le document rapproché apparaît
            alors au gestionnaire qui examine le dossier.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <Carte titre="Déposer une ordonnance">
        {references === null ? (
          <Chargement texte="Chargement des référentiels..." />
        ) : (
          <form className="formulaire" onSubmit={soumettreOrdonnance}>
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
              <Champ label="Date de l’ordonnance">
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
              <Champ label="Quantité">
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
              <Champ label="Validité (jours)">
                <input
                  type="number"
                  min={1}
                  max={730}
                  value={ordonnance.validite_jours}
                  onChange={(event) =>
                    setOrdonnance((precedent) => ({
                      ...precedent,
                      validite_jours: Number(event.target.value),
                    }))
                  }
                />
              </Champ>
              <Champ label="Référence (facultatif)">
                <input
                  value={ordonnance.reference}
                  maxLength={64}
                  placeholder="Générée automatiquement si vide"
                  onChange={(event) =>
                    setOrdonnance((precedent) => ({
                      ...precedent,
                      reference: event.target.value,
                    }))
                  }
                />
              </Champ>
              <Champ label="Diagnostic (facultatif)">
                <input
                  value={ordonnance.diagnostic}
                  maxLength={256}
                  placeholder="Ex. lombalgie aiguë"
                  onChange={(event) =>
                    setOrdonnance((precedent) => ({
                      ...precedent,
                      diagnostic: event.target.value,
                    }))
                  }
                />
              </Champ>
            </div>
            <p className="aide">
              La validité et le diagnostic servent à vérifier que chaque acte est bien
              prescrit. Un doublon (même assuré, même acte, même jour) est refusé.
            </p>
            <button type="submit" className="bouton principal" disabled={envoi}>
              {envoi ? 'Enregistrement...' : 'Enregistrer l’ordonnance'}
            </button>
          </form>
        )}
      </Carte>

    </div>
  )
}
