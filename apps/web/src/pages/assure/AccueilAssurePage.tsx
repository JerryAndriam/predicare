import { useEffect, useState } from 'react'
import { MessageSquareText, Receipt } from 'lucide-react'

import { api, messageErreur } from '../../api/client'
import type { InvoiceSummary, Page } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { EnTetePage, Etape, StatCle, Tuile } from '../../components/blocs'
import { Chargement, Erreur, montant } from '../../components/ui'

/**
 * L'accueil de l'assure.
 *
 * Cette page ne montre pas de donnees sensibles : elle explique ce que
 * l'assure peut faire, et combien cela represente. Le reste de l'espace
 * est a portee de clic.
 */
export function AccueilAssurePage() {
  const { profile } = useAuth()
  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [total, setTotal] = useState(0)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    api<Page<InvoiceSummary>>('/api/core/factures?limit=200&offset=0')
      .then((page) => {
        setFactures(page.items)
        setTotal(page.total)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
      .finally(() => setChargement(false))
  }, [])

  const prisEnCharge = factures.reduce(
    (somme, facture) => somme + (facture.montant_pris_en_charge ?? 0),
    0,
  )
  const enVerification = factures.filter(
    (facture) => facture.is_fraud === true || facture.statut === 'piece_demandee',
  ).length
  const nom = profile?.display_name ?? profile?.subject ?? ''

  return (
    <>
      <EnTetePage
        fil={[{ libelle: 'Espace assuré', chemin: '/assure' }, { libelle: 'Accueil' }]}
        titre={`Bonjour ${nom}`}
        chapo={
          <>
            Voici l’essentiel de votre dossier de soins : ce qui a été remboursé, ce qui
            reste à votre charge, et les points sur lesquels un contrôle est en cours.
            Toute question sur vos garanties trouve sa réponse dans l’assistant.
          </>
        }
      />

      <Erreur message={erreur} />

      {chargement ? (
        <Chargement />
      ) : (
        <>
          <div className="stats">
            <StatCle
              valeur={total}
              libelle="Factures dans votre dossier"
              contexte="Depuis la mise en service de la plateforme"
            />
            <StatCle
              valeur={montant(prisEnCharge)}
              libelle="Montant repris en charge"
              contexte="Somme des montants remboursés"
              ton="info"
            />
            <StatCle
              valeur={enVerification}
              libelle="Dossiers en vérification"
              contexte="Un contrôle est demandé"
              ton={enVerification > 0 ? 'avert' : 'primaire'}
            />
          </div>

          <section className="accueil-section">
            <h2>Que pouvez-vous faire ?</h2>
            <p className="accueil-section-chapo">
              Deux entrées : le détail de vos remboursements et les réponses sur vos
              garanties.
            </p>
            <div className="tuiles">
              <Tuile
                icone={Receipt}
                titre="Mes remboursements"
                texte="Le détail de chaque facture : date, montant, part remboursée et reste à charge."
                chemin="/assure/remboursements"
              />
              <Tuile
                icone={MessageSquareText}
                titre="Poser une question"
                texte="Garanties, plafonds, prises en charge : la réponse cite l’article du contrat qui la fonde."
                chemin="/assure/assistant"
              />
            </div>
          </section>

          <section className="accueil-section">
            <h2>Comment se déroule un remboursement</h2>
            <p className="accueil-section-chapo">
              Trois étapes, du dépôt de la facture à votre notification. Vous n’avez rien
              à faire : le suivi est automatique.
            </p>
            <ol className="etapes">
              <Etape titre="Votre professionnel de santé dépose la facture">
                Il saisit les lignes de l’acte. Chaque ligne est vérifiée avant d’être
                enregistrée : une facture incomplète est refusée et ne crée aucun
                dossier.
              </Etape>
              <Etape titre="La facture est examinée">
                Une note de vigilance est calculée, avec une explication champ par champ.
                Elle sert à repérer les dossiers qui demandent un contrôle.
              </Etape>
              <Etape titre="La décision est prise, puis vous êtes informé">
                Si le score dépasse le seuil, un gestionnaire examine le dossier et
                tranche. Le statut de votre facture change, et il apparaît immédiatement
                dans « Mes remboursements ».
              </Etape>
            </ol>
          </section>

        </>
      )}
    </>
  )
}
