import { Link } from 'react-router-dom'

import { ACCUEIL, ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Accordeon } from '../components/Accordeon'
import { EnTetePage, Etape } from '../components/blocs'

interface Rubrique {
  titre: string
  contenu: string[]
}

interface Procedure {
  titre: string
  etapes: string[]
}

const AIDES: Record<string, Rubrique[]> = {
  assure: [
    {
      titre: 'Où voir mes remboursements ?',
      contenu: [
        'Section « Mes remboursements » : chaque facture avec le montant pris en charge et le reste à charge.',
        'Un reste à charge n’est pas une erreur : c’est la part que votre contrat laisse à votre charge.',
        'Le statut « Fraude confirmée » signifie qu’un contrôle est en cours, pas une sanction.',
        'Le total affiché couvre l’ensemble de votre dossier, pas seulement la page.',
      ],
    },
    {
      titre: 'Poser une question sur mes garanties',
      contenu: [
        'Section « Assistant garanties » : la réponse s’appuie sur les extraits de votre contrat et cite ses sources.',
        'Ouvrez « Sources » pour lire l’article qui fonde la réponse.',
        'Si aucun passage ne correspond, l’assistant le dit : aucune réponse n’est inventée.',
      ],
    },
    {
      titre: 'Changer mon mot de passe',
      contenu: [
        'Menu du profil → Mon compte → Mot de passe.',
        'Le nouveau mot de passe doit compter au moins 12 caractères.',
        'Le changement s’applique dès votre prochaine connexion.',
      ],
    },
  ],
  professionnel_sante: [
    {
      titre: 'Déposer une facture',
      contenu: [
        'Section « Déposer une facture » : choisissez l’assuré, la date, puis les lignes avec l’acte et le montant unitaire.',
        'Le total est calculé au fil de la saisie et vérifié à l’envoi.',
        'Après l’envoi, le score et l’explication s’affichent : ils disent pourquoi la facture a été notée.',
        'Le prestataire est déterminé par votre compte : vous n’avez pas à le saisir.',
      ],
    },
    {
      titre: 'Ma facture a été rejetée',
      contenu: [
        'Le motif est écrit dans la liste de suivi, avec le nom du champ fautif.',
        '« montant_total » hors bornes : le total dépasse le plafond accepté.',
        '« code_acte » inconnu : l’acte n’existe pas au référentiel.',
        'Corrigez la facture et redéposez-la : un rejet ne crée aucun dossier.',
      ],
    },
    {
      titre: 'Déposer plusieurs factures',
      contenu: [
        'Section « Importer un lot » : collez un tableau JSON ou un CSV, puis importez.',
        'Chaque facture est notée séparément : une facture invalide est rejetée seule, sans interrompre le lot.',
        'Le récapitulatif indique, ligne par ligne, la référence obtenue ou le motif du rejet.',
        'Un lot est limité à 200 factures : au-delà, la ligne fautive est signalée avant tout envoi.',
      ],
    },
    {
      titre: 'Déposer une ordonnance',
      contenu: [
        'Section « Déposer une ordonnance » : elle complète une facture déjà déposée.',
        'Un doublon (même assuré, même acte, même jour) est refusé : vérifiez la date avant de renvoyer.',
        'L’ordonnance rapproche les lignes de la facture pour repérer les actes non prescrits.',
      ],
    },
  ],
  gestionnaire: [
    {
      titre: 'Traiter une alerte',
      contenu: [
        'La file est triée par score décroissant : la première ligne est la plus suspecte.',
        'Cliquez une alerte : l’explication de la note et les lignes de la facture s’affichent.',
        '« Non prescrite » sur une ligne signale un acte absent de l’ordonnance : c’est souvent là que se trouve l’anomalie.',
        'Le score n’est qu’un indice : votre motif prime sur lui, et c’est lui qui sera lu au contrôle.',
      ],
    },
    {
      titre: 'Décider',
      contenu: [
        'Le motif est obligatoire : il sera lu lors d’un contrôle et conservé avec la décision.',
        'Confirmer la fraude demande une confirmation explicite : la décision engage le dossier.',
        'La décision met à jour le statut de la facture : l’assuré la voit immédiatement.',
        'Rejeter l’alerte la clôt en faux positif ; demander une pièce laisse le dossier ouvert jusqu’à votre retour.',
      ],
    },
    {
      titre: 'Filtrer la file',
      contenu: [
        'Les filtres portent sur l’assuré, le montant et le score, sur l’ensemble des dossiers.',
        'La file est paginée : le total affiché couvre tous les dossiers, pas seulement la page.',
        'Réinitialiser les filtres recharge la file complète, sans tri résiduel.',
      ],
    },
    {
      titre: 'Retrouver une décision déjà prise',
      contenu: [
        'Section « Historique » : les décisions sont listées avec leur motif, leur auteur et leur horodatage.',
        'Le bouton d’export produit un fichier CSV de la page affichée.',
        'Une décision n’est jamais effacée : elle est consultable et opposable.',
      ],
    },
  ],
  administrateur: [
    {
      titre: 'Changer le seuil d’alerte',
      contenu: [
        'Section « Seuil » : la modification est appliquée immédiatement.',
        'Le seuil de détection décide ce qui entre dans la file ; le seuil de notification décide ce qui déclenche une alerte.',
        'Le changement est conservé avec son motif.',
        'Un seuil plus bas augmente le rappel et le nombre de fausses alertes : c’est un arbitrage.',
      ],
    },
    {
      titre: 'Vérifier que la plateforme fonctionne',
      contenu: [
        'Section « Santé » : état des données, de la notation et de l’assistant.',
        'Section « Observabilité » : latence, volume, erreurs et dérive du modèle.',
        'Section « Canaux » : le bouton « Tester » envoie un message d’essai et dit ce qu’il s’est passé.',
      ],
    },
    {
      titre: 'Changer de version de modèle',
      contenu: [
        'Section « Modèle » : chargez une candidate, puis basculez.',
        'Le retour arrière est disponible : aucune version n’est perdue.',
        'Charger ne bascule pas : la version en service reste active jusqu’à la bascule.',
      ],
    },
    {
      titre: 'Gérer les comptes',
      contenu: [
        'Section « Comptes » : créer un accès, le désactiver, réinitialiser un mot de passe.',
        'La désactivation prend effet immédiatement.',
        'Chaque rôle donne un périmètre d’actions distinct.',
      ],
    },
    {
      titre: 'Répondre aux demandes de droits',
      contenu: [
        'Section « Droits des personnes » : export, rectification, opposition, effacement.',
        'L’effacement supprime les données métier liées à la personne, et l’opération est journalisée.',
        'Chaque demande laisse une trace : qui l’a traitée, quand, et sur quelle base.',
      ],
    },
  ],
}

const PROCEDURES: Record<string, Procedure[]> = {
  assure: [
    {
      titre: 'Vérifier ce qui a été remboursé',
      etapes: [
        'Ouvrez « Mes remboursements » depuis la barre latérale.',
        'Lisez la colonne « Pris en charge » : c’est la part que votre contrat a couverte.',
        'Comparez avec « Reste à charge » : la différence est la part qui vous incombe.',
        'En cas de doute sur une ligne, posez la question à l’assistant : il cite le contrat.',
      ],
    },
  ],
  professionnel_sante: [
    {
      titre: 'Déposer un lot de factures',
      etapes: [
        'Préparez un tableau JSON ou un CSV aux colonnes attendues.',
        'Ouvrez « Importer un lot » et collez le contenu.',
        'Lancez l’import : le récapitulatif indique, ligne par ligne, la référence ou le motif du rejet.',
        'Corrigez uniquement les lignes rejetées : les autres sont déjà enregistrées et notées.',
      ],
    },
  ],
  gestionnaire: [
    {
      titre: 'Traiter une alerte de bout en bout',
      etapes: [
        'Ouvrez l’alerte en tête de file : c’est celle dont le score est le plus élevé.',
        'Lisez l’explication de la note : elle dit quels champs ont pesé, et dans quel sens.',
        'Vérifiez les lignes de la facture, en particulier celles marquées « Non prescrite ».',
        'Choisissez la décision, rédigez le motif, puis enregistrez.',
        'La facture change de statut côté assuré : l’information est immédiate.',
      ],
    },
  ],
  administrateur: [
    {
      titre: 'Changer le seuil en sécurité',
      etapes: [
        'Notez la valeur en vigueur : elle est affichée dans l’en-tête de l’espace.',
        'Saisissez la nouvelle valeur entre 0 et 1, et le motif du changement.',
        'Appliquez : la modification prend effet immédiatement.',
        'Contrôlez la file du gestionnaire : le volume d’alertes a changé.',
      ],
    },
  ],
}

export function AidePage() {
  const { profile } = useAuth()
  if (profile === null) return null

  const role = profile.role
  const rubriques = AIDES[role] ?? []
  const procedures = PROCEDURES[role] ?? []

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Mon espace', chemin: ACCUEIL[role] },
          { libelle: 'Aide' },
        ]}
        titre="Aide"
        chapo={`Les réponses aux questions courantes pour votre rôle (${ROLE_LABELS[
          role
        ].toLowerCase()}) et les gestes pas à pas.`}
        actions={
          <Link className="bouton contour" to={ACCUEIL[role]}>
            Revenir à mon espace
          </Link>
        }
      />

      {procedures.map((procedure, index) => (
        <section
          id={index === 0 ? 'procedures' : undefined}
          className="accueil-section scroll-mt-24"
          key={procedure.titre}
        >
          <h2>{procedure.titre}</h2>
          <p className="accueil-section-chapo">
            La suite des gestes, dans l’ordre où ils se présentent.
          </p>
          <ol className="etapes">
            {procedure.etapes.map((etape) => (
              <Etape titre={etape} key={etape} />
            ))}
          </ol>
        </section>
      ))}

      <section id="faq" className="accueil-section scroll-mt-24">
        <h2>Questions fréquentes</h2>
        <p className="accueil-section-chapo">
          Les réponses sont adaptées à votre rôle : {ROLE_LABELS[role].toLowerCase()}.
        </p>
        <Accordeon
          elements={rubriques.map((rubrique, index) => ({
            valeur: `rubrique-${index}`,
            titre: rubrique.titre,
            contenu: (
              <ul className="space-y-1.5 pl-4">
                {rubrique.contenu.map((ligne) => (
                  <li key={ligne} className="list-disc">
                    {ligne}
                  </li>
                ))}
              </ul>
            ),
          }))}
        />
      </section>
    </>
  )
}
