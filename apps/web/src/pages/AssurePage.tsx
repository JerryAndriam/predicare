import { useEffect, useState, type FormEvent } from 'react'

import { ApiError, api, messageErreur } from '../api/client'
import type { InvoiceSummary, Page, RagAnswer } from '../api/types'
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

interface Message {
  auteur: 'vous' | 'assistant'
  texte: string
  sources?: Record<string, unknown>[]
  etapes?: Record<string, unknown>[]
  meta?: string
}

const STATUTS: Record<string, string> = {
  payee: 'Remboursee',
  remboursee: 'Remboursee',
  rembourse: 'Remboursee',
  en_attente: 'En attente',
  rejetee: 'Rejetee',
  rejete: 'Rejetee',
  recue: 'Recue',
  en_cours: 'En cours',
  fraude_confirmee: 'Fraude confirmee',
  piece_demandee: 'Piece demandee',
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
  if (statut === 'piece_demandee') return { ton: 'alerte', texte: 'Piece demandee' }
  if (statut === 'rejetee' || statut === 'rejete') return { ton: 'ok', texte: 'Clair' }
  if (facture.is_fraud === true) return { ton: 'alerte', texte: 'En verification' }
  if (facture.is_fraud === false) return { ton: 'ok', texte: 'Clair' }
  return { ton: 'neutre', texte: 'Non controle' }
}

function Source({ source }: { source: Record<string, unknown> }) {
  const textes = Object.entries(source).filter(
    ([, valeur]) => typeof valeur === 'string' && valeur.trim() !== '',
  )
  if (textes.length === 0) return null
  return (
    <li>
      <strong>{String(textes[0][1])}</strong>
      {textes.slice(1, 3).map(([cle, valeur]) => (
        <p key={cle}>{String(valeur)}</p>
      ))}
    </li>
  )
}

export function AssurePage() {
  const [onglet, setOnglet] = useState<Onglet>('remboursements')

  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [total, setTotal] = useState(0)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [envoi, setEnvoi] = useState(false)

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

  const demander = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const texte = question.trim()
    if (texte === '') return

    setMessages((precedent) => [...precedent, { auteur: 'vous', texte }])
    setQuestion('')
    setEnvoi(true)

    try {
      const reponse = await api<RagAnswer>('/api/rag/question', {
        method: 'POST',
        body: JSON.stringify({ question: texte }),
      })
      setMessages((precedent) => [
        ...precedent,
        {
          auteur: 'assistant',
          texte: reponse.reponse,
          sources: reponse.sources,
          etapes: reponse.etapes_agent,
          meta: `${reponse.latence_ms.toFixed(0)} ms - ${reponse.tokens} token(s)${
            reponse.cache_semantique ? ' - reponse en cache' : ''
          }${reponse.succes === false ? ' - mode degrade' : ''}`,
        },
      ])
    } catch (error) {
      const indisponible =
        error instanceof ApiError && (error.status === 503 || error.status === 500)
          ? "L'assistant est momentanement indisponible : verifiez la configuration des embeddings et du modele de langage, puis reessayez."
          : messageErreur(error)
      setMessages((precedent) => [
        ...precedent,
        { auteur: 'assistant', texte: indisponible },
      ])
    } finally {
      setEnvoi(false)
    }
  }

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
                    <th>Controle</th>
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

      {onglet === 'assistant' && (
        <Carte titre="Assistant PrediCare">
          <p className="aide">
            Posez une question sur vos garanties, un remboursement ou une procedure.
            L assistant cite les extraits du contrat sur lesquels il s appuie.
          </p>

          <div className="conversation">
            {messages.length === 0 && (
              <Vide>
                Exemple : « Quelles sont les conditions de remboursement d une consultation ? »
              </Vide>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`bulle ${message.auteur}`}>
                <span className="bulle-auteur">
                  {message.auteur === 'vous' ? 'Vous' : 'Assistant'}
                </span>
                <p>{message.texte}</p>
                {message.sources !== undefined && message.sources.length > 0 && (
                  <div className="sources">
                    <span className="champ-label">Sources</span>
                    <ul>
                      {message.sources.map((source, position) => (
                        <Source key={position} source={source} />
                      ))}
                    </ul>
                  </div>
                )}
                {message.etapes !== undefined && message.etapes.length > 0 && (
                  <details className="sources">
                    <summary>Etapes de l'agent ({message.etapes.length})</summary>
                    <ul>
                      {message.etapes.map((etape, position) => (
                        <li key={position}>
                          <span className="mono">{String(etape.outil ?? 'outil')}</span>
                          {' - '}
                          {String(etape.resultat ?? 'ok')}
                          {typeof etape.duree_ms === 'number'
                            ? ` (${etape.duree_ms.toFixed(0)} ms)`
                            : ''}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                {message.meta !== undefined && <span className="bulle-meta">{message.meta}</span>}
              </div>
            ))}
          </div>

          <form className="ligne-formulaire" onSubmit={demander}>
            <input
              type="text"
              value={question}
              maxLength={1000}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Votre question..."
              aria-label="Votre question"
            />
            <button type="submit" className="bouton principal" disabled={envoi}>
              {envoi ? 'Recherche...' : 'Envoyer'}
            </button>
          </form>
        </Carte>
      )}
    </div>
  )
}
