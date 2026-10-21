
import { EnTetePage } from '../../components/blocs'
import { RagAssistant } from '../../components/RagAssistant'

/**
 * L'assistant garanties.
 *
 * La page est volontairement courte : l'assistant est l'ecran. Ce qui
 * l'entoure explique ce qu'il peut faire, et ce qu'il ne peut pas.
 */
export function AssistantPage() {
  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace assuré', chemin: '/assure' },
          { libelle: 'Assistant garanties' },
        ]}
        titre="Assistant garanties"
        chapo={
          <>
            Posez votre question en langage courant : l’assistant cherche dans les
            extraits de votre contrat et répond en citant ses sources. Chaque réponse
            indique l’article qui la fonde.
          </>
        }
      />

      <RagAssistant />
    </>
  )
}
