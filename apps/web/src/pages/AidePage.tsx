import { Link } from 'react-router-dom'

import { ACCUEIL, ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Carte } from '../components/ui'

interface Rubrique {
  titre: string
  contenu: string[]
}

/**
 * Aide integree, contextuelle au role connecte.
 *
 * Une aide qui ne se trouve pas ne sert a rien : le guide papier existe,
 * mais la question « comment je fais ? » se pose devant l'ecran. Cette
 * page repond aux trois questions qui reviennent dans chaque parcours, et
 * pointe vers le guide complet.
 */
const AIDES: Record<string, Rubrique[]> = {
  assure: [
    {
      titre: 'Où voir mes remboursements ?',
      contenu: [
        'Onglet « Mes remboursements » : chaque facture avec le montant repris en charge et le reste à charge.',
        'Un reste à charge n’est pas une erreur : c’est la part que le contrat laisse à votre charge.',
        'Le statut « Fraude confirmée » signifie qu’un contrôle a été fait et qu’une procédure est en cours.',
      ],
    },
    {
      titre: 'Poser une question sur mes garanties',
      contenu: [
        'Onglet « Assistant » : la question est répondée à partir des extraits de votre contrat, et chaque réponse cite ses sources.',
        'Ouvrez « Sources » pour lire l’article du contrat qui fonde la réponse.',
        'Si la question ne trouve pas de passage, l’assistant le dit : aucune réponse n’est inventée.',
      ],
    },
    {
      titre: 'Changer mon mot de passe',
      contenu: [
        'Menu « Mon compte » : le formulaire demande l’ancien puis le nouveau mot de passe.',
        'Le nouveau mot de passe doit compter au moins 12 caractères.',
      ],
    },
  ],
  professionnel_sante: [
    {
      titre: 'Déposer une facture',
      contenu: [
        'Onglet « Déposer une facture » : choisissez l’assuré, la date, puis les lignes avec l’acte et le montant unitaire.',
        'Le total est calculé au fil de la saisie ; il est vérifié par le serveur au moment de l’envoi.',
        'Après l’envoi, le score de fraude et le rapport d’explicabilité s’affichent : ils disent pourquoi la facture a été notée.',
      ],
    },
    {
      titre: 'Ma facture a été rejetée',
      contenu: [
        'Le motif est écrit dans la liste de suivi, avec le nom du champ fautif.',
        '« montant_total » hors bornes : le total dépasse le plafond accepté.',
        '« code_acte » inconnu : l’acte n’existe pas au référentiel.',
        'Corrigez la facture et redéposez-la : un rejet ne crée aucune trace en base.',
      ],
    },
    {
      titre: 'Déposer plusieurs factures',
      contenu: [
        'Onglet « Import de lot » : collez un tableau JSON ou un CSV, puis importez.',
        'Chaque facture est notée séparément : une facture invalide est rejetée seule, sans interrompre le lot.',
        'Le récapitulatif indique, ligne par ligne, la référence obtenue ou le motif du rejet.',
      ],
    },
  ],
  gestionnaire: [
    {
      titre: 'Traiter une alerte',
      contenu: [
        'La file est triée par score décroissant : la première ligne est la plus suspecte.',
        'Cliquez une alerte : le rapport SHAP et les lignes de la facture source s’affichent.',
        '« Non prescrite » sur une ligne signale un acte absent de l’ordonnance : c’est souvent là que se trouve l’anomalie.',
      ],
    },
    {
      titre: 'Décider',
      contenu: [
        'Le motif est obligatoire : il sera lu lors d’un contrôle et conservé dans le journal.',
        'Confirmer la fraude demande une confirmation explicite : la décision engage le dossier.',
        'La décision met à jour le statut de la facture : l’assuré la voit immédiatement.',
      ],
    },
    {
      titre: 'Filtrer la file',
      contenu: [
        'Les filtres portent sur l’assuré, le montant et le score : ils s’appliquent côté serveur.',
        'La file est paginée : le total affiché est celui de la base, pas celui de la page.',
      ],
    },
  ],
  administrateur: [
    {
      titre: 'Changer le seuil d’alerte',
      contenu: [
        'Onglet « Seuil » : la modification est appliquée immédiatement, sans redémarrage.',
        'Le seuil de détection décide ce qui entre dans la file ; le seuil de notification décide ce qui interrompt un humain par Slack.',
        'Le changement est tracé dans le journal d’audit avec son motif.',
      ],
    },
    {
      titre: 'Vérifier que la plateforme fonctionne',
      contenu: [
        'Onglet « Santé » : état de la base, du service d’inférence, de l’assistant et secrets manquants.',
        'Onglet « Observabilité » : latence, volume, erreurs et dérive du modèle.',
        'Onglet « Canaux » : le bouton « Tester » envoie un message d’essai et dit ce qu’il s’est passé.',
      ],
    },
    {
      titre: 'Changer de version de modèle',
      contenu: [
        'Onglet « Modèle » : charger une candidate, puis la basculer. Le service continue de répondre pendant la préparation.',
        'Le retour arrière est disponible : aucune version n’est perdue.',
      ],
    },
  ],
}

export function AidePage() {
  const { profile } = useAuth()
  if (profile === null) return null

  const rubriques = AIDES[profile.role] ?? []

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Aide</h1>
        <p>
          Les réponses aux questions les plus fréquentes pour votre rôle. Le guide complet
          est dans <span className="mono">docs/utilisateur/README.md</span>.
        </p>
      </div>

      <Carte titre={`Votre rôle : ${ROLE_LABELS[profile.role]}`}>
        <div className="resultat-meta">
          <Link className="bouton principal" to={ACCUEIL[profile.role]}>
            Revenir à mon espace
          </Link>
        </div>
      </Carte>

      {rubriques.map((rubrique) => (
        <Carte key={rubrique.titre} titre={rubrique.titre}>
          <ul className="liste-simple">
            {rubrique.contenu.map((ligne) => (
              <li key={ligne}>{ligne}</li>
            ))}
          </ul>
        </Carte>
      ))}
    </div>
  )
}
