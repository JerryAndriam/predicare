import { useEffect, useRef, useState, type FormEvent } from 'react'

import { ApiError, api, messageErreur } from '../api/client'
import type { RagAnswer, RagSource, RagStep } from '../api/types'
import { RagSourceCard } from './RagSourceCard'
import { Badge, Carte, Vide } from './ui'

type Auteur = 'vous' | 'assistant'

interface Message {
  id: string
  auteur: Auteur
  texte: string
  sources: RagSource[]
  etapes: RagStep[]
  succes: boolean
  mode?: 'complet' | 'degrade' | 'indisponible'
  limiteAtteinte: boolean
  latenceMs?: number
  tokensEntree?: number
  tokensSortie?: number
  coutUsd?: number
  coutEur?: number
  cache?: boolean
}

const EXEMPLES = [
  'Quel est le taux de remboursement d’une consultation en formule PREMIUM ?',
  'Quel est le plafond annuel de l’optique pour cette formule ?',
  'Combien ai-je été remboursé au total sur mes factures payées ?',
]

const LIBELLES_OUTILS: Record<string, string> = {
  rechercher_contrats: 'Recherche dans les contrats',
  consulter_historique_assure: 'Historique de remboursement',
  cache_semantique: 'Cache sémantique',
  configuration: 'Configuration',
}

const LIBELLES_STATUTS: Record<string, string> = {
  ok: 'OK',
  hit: 'Hit',
  limite: 'Limite',
  erreur: 'Erreur',
  inconnu: 'Inconnu',
}

/** Identifiant de conversation cote client. Le serveur le cloisonne par assure. */
function nouvelId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `rag-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function nombre(valeur: number, decimales = 0): string {
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  }).format(valeur)
}

function montantUsd(valeur: number): string {
  return `${nombre(valeur, 6)} USD`
}

function montantEur(valeur: number): string {
  return `${nombre(valeur, 6)} €`
}

function messageAssistantErreur(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return error.message
    if (error.status === 400) return error.message
    if (error.status === 401) {
      return 'Votre session a expiré. Reconnectez-vous pour continuer.'
    }
    if (error.status === 403) {
      return "Votre rôle ne permet pas d'interroger l'assistant."
    }
    if (error.status === 422) {
      return "La question n'est pas validé. Reformulez-la en moins de 1 000 caractères."
    }
    if (error.status === 429) {
      return 'Trop de questions en peu de temps. Patientez un instant avant de réessayer.'
    }
    if (error.status === 500 || error.status === 502 || error.status === 503) {
      return "L'assistant est momentanément indisponible. Réessayez dans quelques instants."
    }
    return error.message
  }
  return messageErreur(error)
}

function EtapeAgent({ etape }: { etape: RagStep }) {
  const ton: 'ok' | 'alerte' | 'neutre' =
    etape.resultat === 'ok' ? 'ok' : etape.resultat === 'erreur' ? 'alerte' : 'neutre'

  return (
    <li className="etape-agent">
      <span>{LIBELLES_OUTILS[etape.outil] ?? etape.outil}</span>
      <Badge ton={ton}>{LIBELLES_STATUTS[etape.resultat] ?? etape.resultat}</Badge>
      {typeof etape.duree_ms === 'number' && (
        <span className="etape-duree">{nombre(Math.round(etape.duree_ms))} ms</span>
      )}
    </li>
  )
}

function DetailsTechniques({ message }: { message: Message }) {
  return (
    <details className="sources details-techniques">
      <summary>Détails techniques</summary>
      <dl className="details-liste">
        <div>
          <dt>Latence</dt>
          <dd>{nombre(Math.round(message.latenceMs ?? 0))} ms</dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd>
            {message.tokensEntree ?? 0} en entrée / {message.tokensSortie ?? 0} en sortie
          </dd>
        </div>
        <div>
          <dt>Coût estimé</dt>
          <dd>
            {montantUsd(message.coutUsd ?? 0)} ({montantEur(message.coutEur ?? 0)})
          </dd>
        </div>
        <div>
          <dt>Cache sémantique</dt>
          <dd>{message.cache === true ? 'Oui' : 'Non'}</dd>
        </div>
      </dl>
    </details>
  )
}

function MessageBulle({ message }: { message: Message }) {
  const estVous = message.auteur === 'vous'

  return (
    <div className={`bulle ${estVous ? 'vous' : 'assistant'}${message.succes ? '' : ' degradee'}`}>
      <span className="bulle-auteur">{estVous ? 'Vous' : 'Assistant'}</span>
      <p className="bulle-texte">{message.texte}</p>

      {!estVous && (!message.succes || message.mode === 'degrade' || message.limiteAtteinte) && (
        <div className="bulle-badges">
          {!message.succes && <Badge ton="alerte">Réponse dégradée</Badge>}
          {message.mode === 'degrade' && (
            <Badge ton="info">Extraits de contrat, sans rédaction</Badge>
          )}
          {message.limiteAtteinte && <Badge ton="info">Limite d’étapes atteinte</Badge>}
        </div>
      )}

      {!estVous && message.sources.length > 0 && (
        <div className="sources">
          <span className="champ-label">Sources ({message.sources.length})</span>
          <ul className="liste-sources">
            {message.sources.map((source, index) => (
              <RagSourceCard
                key={`${source.contrat}-${source.article}-${index}`}
                source={source}
              />
            ))}
          </ul>
        </div>
      )}

      {!estVous && message.succes && message.sources.length === 0 && (
        <p className="source-vide">Aucune source contractuelle retrouvée pour cette réponse.</p>
      )}

      {!estVous && message.etapes.length > 0 && (
        <details className="sources">
          <summary>Trace de l’agent ({message.etapes.length})</summary>
          <ul className="liste-etapes">
            {message.etapes.map((etape, index) => (
              <EtapeAgent key={`${etape.outil}-${index}`} etape={etape} />
            ))}
          </ul>
        </details>
      )}

      {!estVous && message.latenceMs !== undefined && (
        <DetailsTechniques message={message} />
      )}
    </div>
  )
}

export function RagAssistant() {
  const [sessionId, setSessionId] = useState(nouvelId)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [envoi, setEnvoi] = useState(false)

  const conversationRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    const conversation = conversationRef.current
    if (conversation !== null) {
      conversation.scrollTop = conversation.scrollHeight
    }
  }, [messages, envoi])

  const envoyer = async (texteBrut?: string) => {
    const texte = (texteBrut ?? question).trim()
    if (texte === '' || envoi) return

    setQuestion('')
    setMessages((precedent) => [
      ...precedent,
      {
        id: nouvelId(),
        auteur: 'vous',
        texte,
        sources: [],
        etapes: [],
        succes: true,
        limiteAtteinte: false,
      },
    ])
    setEnvoi(true)

    try {
      const reponse = await api<RagAnswer>('/api/rag/question', {
        method: 'POST',
        body: JSON.stringify({ question: texte, session_id: sessionId }),
      })

      setMessages((precedent) => [
        ...precedent,
        {
          id: nouvelId(),
          auteur: 'assistant',
          texte: reponse.reponse,
          sources: reponse.sources ?? [],
          etapes: reponse.etapes_agent ?? [],
          succes: reponse.succes ?? true,
          mode: reponse.mode ?? 'complet',
          limiteAtteinte: reponse.limite_atteinte ?? false,
          latenceMs: reponse.latence_ms,
          tokensEntree: reponse.tokens_entree ?? 0,
          tokensSortie: reponse.tokens_sortie ?? 0,
          coutUsd: reponse.cout_estime_usd ?? 0,
          coutEur: reponse.cout_estime_eur ?? 0,
          cache: reponse.cache_semantique,
        },
      ])
    } catch (error) {
      setMessages((precedent) => [
        ...precedent,
        {
          id: nouvelId(),
          auteur: 'assistant',
          texte: messageAssistantErreur(error),
          sources: [],
          etapes: [],
          succes: false,
          limiteAtteinte: false,
        },
      ])
    } finally {
      setEnvoi(false)
      inputRef.current?.focus()
    }
  }

  const soumettre = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void envoyer()
  }

  const recommencer = () => {
    if (envoi) return
    setMessages([])
    setQuestion('')
    setSessionId(nouvelId())
    inputRef.current?.focus()
  }

  return (
    <Carte
      titre="Assistant KolikolyCare"
      actions={
        <button
          type="button"
          className="bouton discret"
          onClick={recommencer}
          disabled={envoi || messages.length === 0}
        >
          Nouvelle conversation
        </button>
      }
    >
      <p className="aide">
        Posez une question sur vos garanties, un remboursement ou une procédure.
        L’assistant cite les extraits du contrat sur lesquels il s’appuie et garde
        le fil de la conversation pendant une heure.
      </p>

      <div
        className="conversation"
        ref={conversationRef}
        role="log"
        aria-live="polite"
        aria-busy={envoi}
      >
        {messages.length === 0 && (
          <div className="assistant-accueil">
            <Vide>
              Exemple : « Quelles sont les conditions de remboursement d’une consultation ? »
            </Vide>
            <div className="suggestions" aria-label="Exemples de questions">
              {EXEMPLES.map((exemple) => (
                <button
                  key={exemple}
                  type="button"
                  className="suggestion"
                  onClick={() => void envoyer(exemple)}
                  disabled={envoi}
                >
                  {exemple}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <MessageBulle key={message.id} message={message} />
        ))}

        {envoi && (
          <div className="bulle assistant">
            <span className="bulle-auteur">Assistant</span>
            <p className="bulle-texte assistant-attente">
              Recherche dans vos contrats et votre historique...
            </p>
          </div>
        )}
      </div>

      <form className="ligne-formulaire" onSubmit={soumettre}>
        <input
          ref={inputRef}
          type="text"
          value={question}
          maxLength={1000}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Posez votre question..."
          aria-label="Votre question"
          autoComplete="off"
        />
        <button
          type="submit"
          className="bouton principal"
          disabled={envoi || question.trim() === ''}
        >
          {envoi ? 'Recherche...' : 'Envoyer'}
        </button>
      </form>

      <div className="assistant-pied">
        <span>{question.length} / 1000</span>
        <span>Entrée pour envoyer</span>
      </div>
    </Carte>
  )
}
