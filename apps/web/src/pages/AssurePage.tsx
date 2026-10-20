import { useEffect, useState } from 'react'

import { api, messageErreur } from '../api/client'
import type { InvoiceSummary, Page } from '../api/types'
import { RagAssistant } from '../components/RagAssistant'
import {
  Badge,
  Carte,
  Chargement,
  Erreur,
  Vide,
  dateCourte,
  montant,
  montantOuTiret,
} from '../components/ui'

type Onglet = 'remboursements' | 'assistant'

const STATUTS: Record<string, string> = {
  payee: 'Remboursée',
  remboursee: 'Remboursée',
  rembourse: 'Remboursée',
  en_attente: 'En attente',
  rejetee: 'Rejetée',
  rejete: 'Rejetée',
  recue: 'Reçue',
  en_cours: 'En cours',
  fraude_confirmee: 'Fraude confirmee',
  piece_demandee: 'Pièce demandée',
}

function libelleStatut(statut: string): string {
  return STATUTS[statut.trim().toLowerCase()] ?? statut
}

function controleFacture(facture: InvoiceSummary): {
  ton: 'ok' | 'alerte' | 'neutre'
  texte: string
} {
  const statut = facture.statut.trim().toLowerCase()
  if (statut === 'fraude_confirmee') return { ton: 'alerte', texte: 'Fraude confirmee' }
  if (statut === 'piece_demandee') return { ton: 'alerte', texte: 'Pièce demandée' }
  if (statut === 'rejetee' || statut === 'rejete') return { ton: 'ok', texte: 'Clair' }
  if (facture.is_fraud === true) return { ton: 'alerte', texte: 'En vérification' }
  if (facture.is_fraud === false) return { ton: 'ok', texte: 'Clair' }
  return { ton: 'neutre', texte: 'Non contrôle' }
}

export function AssurePage() {
  const [onglet, setOnglet] = useState<Onglet>('remboursements')

  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [total, setTotal] = useState(0)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  const chargerFactures = (offset = 0) => {
    setChargement(true)
    api<Page<InvoiceSummary>>(`/api/core/factures?limit=100&offset=${offset}`)
      .then((page) => {
        setFactures((precedent) =>
          offset === 0 ? page.items : [...precedent, ...page.items],
        )
        setTotal(page.total)
      })
      .catch((error: unknown) => setErreur(messageErreur(error)))
      .finally(() => setChargement(false))
  }

  useEffect(() => {
    chargerFactures()
  }, [])

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Mes remboursements</h1>
        <p>Historique de vos factures, de leur prise en charge et assistant sur vos garanties.</p>
      </div>

      <div className="onglets" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'remboursements'}
          className={onglet === 'remboursements' ? 'onglet actif' : 'onglet'}
          onClick={() => setOnglet('remboursements')}
        >
          Remboursements
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'assistant'}
          className={onglet === 'assistant' ? 'onglet actif' : 'onglet'}
          onClick={() => setOnglet('assistant')}
        >
          Assistant
        </button>
      </div>

      {onglet === 'remboursements' && (
        <Carte titre={`${factures.length} sur ${total} facture(s)`}>
          <Erreur message={erreur} />
          {chargement && <Chargement />}
          {!chargement && factures.length === 0 && (
            <Vide>Aucune facture rattachee a votre dossier pour le moment.</Vide>
          )}
          {factures.length > 0 && (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Prestataire</th>
                    <th className="droite">Facture</th>
                    <th className="droite">Pris en charge</th>
                    <th className="droite">Reste a charge</th>
                    <th>Statut</th>
                    <th>Contrôle</th>
                  </tr>
                </thead>
                <tbody>
                  {factures.map((facture) => (
                    <tr key={facture.facture_id}>
                      <td>{dateCourte(facture.date_facture)}</td>
                      <td className="mono">{facture.prestataire_id}</td>
                      <td className="droite">{montant(facture.montant_total)}</td>
                      <td className="droite">
                        {montantOuTiret(facture.montant_pris_en_charge)}
                      </td>
                      <td className="droite">{montantOuTiret(facture.reste_a_charge)}</td>
                      <td>{libelleStatut(facture.statut)}</td>
                      <td>
                        {(() => {
                          const controle = controleFacture(facture)
                          return <Badge ton={controle.ton}>{controle.texte}</Badge>
                        })()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!chargement && factures.length < total && (
            <button
              type="button"
              className="bouton discret"
              onClick={() => chargerFactures(factures.length)}
            >
              Charger la suite ({total - factures.length} restantes)
            </button>
          )}
        </Carte>
      )}

      <div hidden={onglet !== 'assistant'}>
        <RagAssistant />
      </div>
    </div>
  )
}
