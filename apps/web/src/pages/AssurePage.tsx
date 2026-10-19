import { useEffect, useState, type FormEvent } from 'react'

import { ApiError, api, messageErreur } from '../api/client'
import type { InvoiceSummary, Page, RagAnswer } from '../api/types'
import { Badge, Carte, Chargement, Erreur, Vide, dateCourte, montant } from '../components/ui'

type Onglet = 'remboursements' | 'assistant'

interface Message {
  auteur: 'vous' | 'assistant'
  texte: string
  sources?: Record<string, unknown>[]
  meta?: string
}

const STATUTS: Record<string, string> = {
  remboursee: 'Remboursee',
  rembourse: 'Remboursee',
  en_attente: 'En attente',
  rejetee: 'Rejetee',
  rejete: 'Rejetee',
  recue: 'Recue',
  en_cours: 'En cours',
}

function libelleStatut(statut: string): string {
  return STATUTS[statut] ?? statut
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
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [envoi, setEnvoi] = useState(false)

  useEffect(() => {
    api<Page<InvoiceSummary>>('/api/core/factures?limit=100')
      .then((page) => setFactures(page.items))
      .catch((error: unknown) => setErreur(messageErreur(error)))
      .finally(() => setChargement(false))
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
          meta: `${reponse.latence_ms.toFixed(0)} ms${reponse.cache_semantique ? ' - reponse en cache' : ''}`,
        },
      ])
    } catch (error) {
      const indisponible =
        error instanceof ApiError && error.status === 503
          ? "L'assistant est momentanement indisponible : la cle du modele de langage n'est pas configuree."
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
        <p>Historique de vos factures et assistant sur vos garanties.</p>
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
        <Carte titre={`${factures.length} facture(s)`}>
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
                    <th className="droite">Montant</th>
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
                      <td>{libelleStatut(facture.statut)}</td>
                      <td>
                        {facture.is_fraud === true ? (
                          <Badge ton="alerte">En verification</Badge>
                        ) : (
                          <Badge ton="ok">Clair</Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
