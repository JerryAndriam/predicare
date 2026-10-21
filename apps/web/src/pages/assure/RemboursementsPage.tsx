import { useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { InvoiceSummary, Page } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import {
  Badge,
  Chargement,
  Erreur,
  EtatVide,
  Pagination,
  Pastille,
  dateCourte,
  montant,
  montantOuTiret,
} from '../../components/ui'

const LIMITE = 50

/**
 * Etat du controle d'une facture.
 *
 * Le libelle ne dit jamais seul qu'une chose : une couleur. « Rejetée »
 * s'affiche en rouge ET en toutes lettres, et une facture rejetee n'est
 * plus qualifiee de « Clair » -- elle ne l'a jamais ete.
 */
function controleFacture(facture: InvoiceSummary): {
  ton: 'ok' | 'alerte' | 'avert' | 'neutre'
  texte: string
} {
  const statut = facture.statut.trim().toLowerCase()
  if (statut === 'fraude_confirmee') return { ton: 'alerte', texte: 'Fraude confirmée' }
  if (statut === 'piece_demandee') return { ton: 'avert', texte: 'Pièce demandée' }
  if (statut === 'rejetee' || statut === 'rejete') return { ton: 'alerte', texte: 'Rejetée' }
  if (facture.is_fraud === true) return { ton: 'alerte', texte: 'En vérification' }
  if (facture.is_fraud === false) return { ton: 'ok', texte: 'Clair' }
  return { ton: 'neutre', texte: 'Non contrôlé' }
}

export function RemboursementsPage() {
  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  const charger = (decalage = 0) => {
    setChargement(true)
    api<Page<InvoiceSummary>>(`/api/core/factures?limit=${LIMITE}&offset=${decalage}`)
      .then((page) => {
        setFactures(page.items)
        setTotal(page.total)
        setOffset(decalage)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
      .finally(() => setChargement(false))
  }

  useEffect(() => {
    charger()
  }, [])

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace assuré', chemin: '/assure' },
          { libelle: 'Mes remboursements' },
        ]}
        titre="Mes remboursements"
        chapo={
          <>
            Chaque facture déposée par vos professionnels de santé, avec le montant
            repris en charge, le reste à votre charge, et l’état du contrôle. Les
            montants sont exprimés en ariary.
          </>
        }
      />

      <Erreur message={erreur} />

      {chargement && <Chargement />}

      {!chargement && factures.length === 0 && (
        <EtatVide
          titre="Aucun remboursement pour le moment"
          texte="Vos factures apparaîtront ici dès que votre professionnel de santé les aura déposées. L’assistant peut vous indiquer ce qui est attendu de votre côté."
        />
      )}

      {!chargement && factures.length > 0 && (
        <>
          <div className="table-enveloppe">
            <table className="table">
              <caption className="visuellement-cache">
                Vos factures, leur prise en charge et l’état du contrôle
              </caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Prestataire</th>
                  <th scope="col" className="droite">
                    Facture
                  </th>
                  <th scope="col" className="droite">
                    Pris en charge
                  </th>
                  <th scope="col" className="droite">
                    Reste à charge
                  </th>
                  <th scope="col">Statut</th>
                  <th scope="col">Contrôle</th>
                </tr>
              </thead>
              <tbody>
                {factures.map((facture) => {
                  const controle = controleFacture(facture)
                  return (
                    <tr key={facture.facture_id}>
                      <td>{dateCourte(facture.date_facture)}</td>
                      <td className="mono">{facture.prestataire_id}</td>
                      <td className="droite">{montant(facture.montant_total)}</td>
                      <td className="droite">{montantOuTiret(facture.montant_pris_en_charge)}</td>
                      <td className="droite">{montantOuTiret(facture.reste_a_charge)}</td>
                      <td>
                        <Pastille statut={facture.statut} />
                      </td>
                      <td>
                        <Badge ton={controle.ton}>{controle.texte}</Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <Pagination
            total={total}
            offset={offset}
            limite={LIMITE}
            onChange={charger}
            libelle="factures"
          />
        </>
      )}
    </>
  )
}
