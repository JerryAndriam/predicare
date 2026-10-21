import { useEffect, useState } from 'react'
import { FilePlus2, FileText, ListChecks, Upload } from 'lucide-react'

import { api, messageErreur } from '../../api/client'
import type { InvoiceSummary, Page } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { EnTetePage, Etape, StatCle, Tuile } from '../../components/blocs'
import { Chargement, Erreur, montant } from '../../components/ui'

/**
 * L'accueil du professionnel de sante.
 *
 * L'ecran consolide des chiffres venus de l'API et rappelle les regles qui
 * ne changent pas : ce que le professionnel peut faire, et dans quel ordre.
 * Aucune regle n'est inventee, et aucun chiffre n'est estime : seuls les
 * totaux reellement calcules sont affiches.
 */
export function AccueilProPage() {
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

  const montantDepose = factures.reduce((somme, facture) => somme + facture.montant_total, 0)
  const enVerification = factures.filter(
    (facture) => facture.is_fraud === true || facture.statut === 'piece_demandee',
  ).length

  // L'API sert au maximum 200 dossiers par page. Au-dela, la portee des
  // chiffres est annoncee : mieux vaut un chiffre borne et exact qu'un
  // total que l'utilisateur croirait complet.
  const portee =
    factures.length >= total
      ? 'Sur l’ensemble de vos dossiers'
      : `Sur les ${factures.length} dossiers les plus récents`

  const nom = profile?.display_name ?? profile?.subject ?? ''

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace professionnel de santé', chemin: '/professionnel' },
          { libelle: 'Accueil' },
        ]}
        titre={nom === '' ? 'Espace professionnel de santé' : `Bonjour ${nom}`}
        chapo={
          <>
            Voici l’essentiel de votre activité : ce que vous avez déposé, ce qui
            attend une décision, et les gestes du quotidien. Chaque page pose une
            seule question — déposer, importer ou suivre — et rappelle la règle qui
            s’y applique.
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
              libelle="Dossiers déposés"
              contexte="Depuis la mise en service de la plateforme"
            />
            <StatCle
              valeur={montant(montantDepose)}
              libelle="Montant déposé"
              contexte={portee}
              ton="info"
            />
            <StatCle
              valeur={enVerification}
              libelle="Dossiers en vérification"
              contexte={portee}
              ton={enVerification > 0 ? 'avert' : 'primaire'}
            />
          </div>

          <section className="accueil-section">
            <h2>Que pouvez-vous faire ?</h2>
            <p className="accueil-section-chapo">
              Quatre entrées, quatre usages : déposer une facture, traiter un lot de
              factures en une fois, suivre un dossier, transmettre une ordonnance.
            </p>
            <div className="tuiles">
              <Tuile
                icone={FilePlus2}
                titre="Déposer une facture"
                texte="Saisissez les lignes de l’acte : la facture est vérifiée, notée, puis expliquée."
                chemin="/professionnel/depot"
              />
              <Tuile
                icone={Upload}
                titre="Importer un lot"
                texte="Déposez un tableau de factures en une fois : une ligne invalide n’interrompt pas le lot."
                chemin="/professionnel/import-lot"
              />
              <Tuile
                icone={ListChecks}
                titre="Suivi des dossiers"
                texte="L’état de chaque dossier déposé : date, montant, note de vigilance et statut de traitement."
                chemin="/professionnel/suivi"
              />
              <Tuile
                icone={FileText}
                titre="Déposer une ordonnance"
                texte="Transmettez une ordonnance pour rapprocher le dossier de l’acte prescrit."
                chemin="/professionnel/ordonnance"
              />
            </div>
          </section>

          <section className="accueil-section">
            <h2>Comment se déroule un dépôt</h2>
            <p className="accueil-section-chapo">
              Trois étapes, de la saisie à la décision. Vous n’avez rien à faire
              ensuite : le suivi du dossier est automatique.
            </p>
            <ol className="etapes">
              <Etape titre="Vous saisissez la facture">
                Une facture porte une date, un assuré et une ou plusieurs lignes
                d’acte. Le montant total est recalculé à partir des lignes. Le
                prestataire rattaché à votre compte est repris automatiquement.
              </Etape>
              <Etape titre="La facture est vérifiée, puis notée">
                Les références — assuré, prestataire, acte — sont contrôlées avant
                l’enregistrement. La note de vigilance, le seuil appliqué et son
                explication s’affichent ensuite.
              </Etape>
              <Etape titre="Le dossier poursuit son traitement">
                Sous le seuil, la facture suit le circuit de remboursement. Au-dessus,
                elle est confiée à un gestionnaire, qui examine le dossier et
                tranche : le statut du dossier change alors.
              </Etape>
            </ol>
          </section>

        </>
      )}
    </>
  )
}
