import type { RagSource } from '../api/types'
import { Badge } from './ui'

/**
 * Une source contractuelle affichable telle quelle.
 *
 * Le contrat, l'article et la garantie permettent de verifier la reference ;
 * l'extrait est replie pour ne pas noyer la conversation, mais il reste le
 * seul element qui prouve que la reponse s'appuie sur le document.
 */
function libelleArticle(article: string): string {
  if (article === '' || article === '-') return ''
  return article.toLowerCase().startsWith('article') ? article : `Article ${article}`
}

export function RagSourceCard({ source }: { source: RagSource }) {
  const extrait = source.extrait.trim()
  const article = libelleArticle(source.article.trim())
  const garantie = source.garantie.trim()
  const pertinence = Number.isFinite(source.score) ? Math.round(source.score * 100) : null

  return (
    <li className="source-carte">
      <div className="source-entete">
        <strong>{source.contrat || 'Contrat'}</strong>
        {article !== '' && <Badge ton="info">{article}</Badge>}
        {garantie !== '' && garantie !== '-' && <Badge>{garantie}</Badge>}
        {pertinence !== null && (
          <span className="source-score">Pertinence {pertinence} %</span>
        )}
      </div>

      {extrait !== '' && (
        <details className="source-extrait">
          <summary>Voir l’extrait</summary>
          <p>{extrait}</p>
        </details>
      )}

      {source.source_fichier !== '' && (
        <span className="source-fichier">{source.source_fichier}</span>
      )}
    </li>
  )
}
