import { useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { InvoiceSummary, Page } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import {
  Carte,
  Champ,
  Chargement,
  Erreur,
  EtatVide,
  Pagination,
  Pastille,
  dateCourte,
  montant,
  pourcentage,
} from '../../components/ui'

/** Nombre de dossiers servis par page : la pagination est cote serveur. */
const LIMITE_SUIVI = 100

/** Statuts de facture proposes dans le filtre du suivi. */
const STATUTS_AFFICHES: { valeur: string; libelle: string }[] = [
  { valeur: 'reçue', libelle: 'Reçue' },
  { valeur: 'en_cours', libelle: 'En cours' },
  { valeur: 'payee', libelle: 'Payée' },
  { valeur: 'rejetée', libelle: 'Rejetée' },
  { valeur: 'fraude_confirmee', libelle: 'Fraude confirmée' },
  { valeur: 'piece_demandee', libelle: 'Pièce demandée' },
]

/**
 * Le suivi des dossiers.
 *
 * La liste est paginee COTE SERVEUR : le front ne recoit que la page
 * demandee, et le total affiche est celui du serveur. Le filtre de statut
 * est applique lui aussi par le serveur.
 */
export function SuiviPage() {
  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [chargement, setChargement] = useState(true)
  const [filtreStatut, setFiltreStatut] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const charger = (decalage = 0) => {
    setChargement(true)
    const filtre = filtreStatut === '' ? '' : `&statut=${encodeURIComponent(filtreStatut)}`
    api<Page<InvoiceSummary>>(
      `/api/core/factures?limit=${LIMITE_SUIVI}&offset=${decalage}${filtre}`,
    )
      .then((page) => {
        setFactures(page.items)
        setOffset(decalage)
        setTotal(page.total)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
      .finally(() => setChargement(false))
  }

  useEffect(() => {
    charger()
  }, [])

  return (
    <div className="pile">
      <EnTetePage
        fil={[
          { libelle: 'Espace professionnel de santé', chemin: '/professionnel' },
          { libelle: 'Suivi des dossiers' },
        ]}
        titre="Suivi des dossiers"
        chapo={
          <>
            L’état de chaque dossier déposé : date, montant, note de vigilance et statut
            de traitement. Le filtre et la pagination couvrent l’ensemble de vos dépôts.
          </>
        }
      />

      <Erreur message={erreur} />

      <Carte
        titre="Dossiers déposés"
        actions={
          <Champ label="Statut">
            <select
              value={filtreStatut}
              onChange={(event) => {
                setFiltreStatut(event.target.value)
                setFactures([])
                charger(0)
              }}
            >
              <option value="">Tous les statuts</option>
              {STATUTS_AFFICHES.map((statut) => (
                <option key={statut.valeur} value={statut.valeur}>
                  {statut.libelle}
                </option>
              ))}
            </select>
          </Champ>
        }
      >
        {chargement && <Chargement texte="Chargement des dossiers..." />}

        {!chargement && factures.length === 0 && (
          <EtatVide
            titre="Aucun dossier déposé"
            texte="Les factures que vous déposez apparaîtront ici, avec leur score et leur état de traitement."
          />
        )}

        {factures.length > 0 && (
          <>
            <div className="table-enveloppe">
              <table className="table">
                <caption className="visuellement-cache">
                  Vos dossiers déposés et leur état de traitement
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Assuré</th>
                    <th scope="col">Prestataire</th>
                    <th scope="col" className="droite">
                      Montant
                    </th>
                    <th scope="col" className="droite">
                      Score
                    </th>
                    <th scope="col">Statut</th>
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
                      <td>
                        <Pastille statut={facture.statut} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              total={total}
              offset={offset}
              limite={LIMITE_SUIVI}
              onChange={charger}
              libelle="dossiers"
            />
          </>
        )}
      </Carte>

    </div>
  )
}
