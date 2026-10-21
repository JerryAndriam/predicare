import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  Bell,
  Brain,
  ChartColumn,
  FilePlus2,
  FileText,
  HeartPulse,
  House,
  ListChecks,
  MessageSquareText,
  Receipt,
  ScrollText,
  ShieldCheck,
  Siren,
  SlidersHorizontal,
  Upload,
  Users,
} from 'lucide-react'

import type { Role } from './api/types'

/**
 * La carte de navigation de l'application.
 *
 * Elle est la seule source de verite : la sidebar, la topbar et les pages
 * d'accueil la lisent. Ajouter une section, c'est ajouter une ligne ici --
 * pas toucher trois composants.
 */
export interface Section {
  /** Le chemin de la page, relatif a la racine du site. */
  chemin: string
  libelle: string
  /** Une phrase : elle sert d'introduction a la section. */
  description: string
  icone: LucideIcon
}

export interface Espace {
  cle: string
  libelle: string
  libelleCourt: string
  roles: Role[]
  /** La page d'accueil de l'espace. */
  accueil: string
  sections: Section[]
}

export const ESPACES: Espace[] = [
  {
    cle: 'assure',
    libelle: 'Espace assuré',
    libelleCourt: 'Assuré',
    roles: ['assure'],
    accueil: '/assure',
    sections: [
      {
        chemin: '/assure',
        libelle: 'Accueil',
        description:
          'Vos droits, vos remboursements, et comment poser une question sur vos garanties.',
        icone: House,
      },
      {
        chemin: '/assure/remboursements',
        libelle: 'Mes remboursements',
        description:
          'Chaque facture déposée par vos professionnels de santé, avec le montant repris en charge et le reste à charge.',
        icone: Receipt,
      },
      {
        chemin: '/assure/assistant',
        libelle: 'Assistant garanties',
        description:
          'Une question sur votre contrat, posée en langage courant. Chaque réponse cite le passage du contrat qui la fonde.',
        icone: MessageSquareText,
      },
    ],
  },
  {
    cle: 'professionnel',
    libelle: 'Espace professionnel de santé',
    libelleCourt: 'Professionnel',
    roles: ['professionnel_sante'],
    accueil: '/professionnel',
    sections: [
      {
        chemin: '/professionnel',
        libelle: 'Accueil',
        description:
          'Déposer une facture, suivre un lot, vérifier un dossier : les trois gestes du quotidien et leurs règles.',
        icone: House,
      },
      {
        chemin: '/professionnel/depot',
        libelle: 'Déposer une facture',
        description:
          'Saisir les lignes d’une facture. Elle est vérifiée, notée, puis expliquée : la note et son explication reviennent dans le dossier.',
        icone: FilePlus2,
      },
      {
        chemin: '/professionnel/import-lot',
        libelle: 'Importer un lot',
        description:
          'Déposer un tableau de factures en une fois. Chaque ligne est traitée séparément : une facture invalide n’interrompt pas le lot.',
        icone: Upload,
      },
      {
        chemin: '/professionnel/suivi',
        libelle: 'Suivi des dossiers',
        description:
          'L’état de chaque dossier déposé : la date, le montant, le score de fraude et le motif en cas de rejet.',
        icone: ListChecks,
      },
      {
        chemin: '/professionnel/ordonnance',
        libelle: 'Déposer une ordonnance',
        description:
          'Transmettre une ordonnance pour compléter un dossier. Le document est rapproché des lignes de la facture.',
        icone: FileText,
      },
    ],
  },
  {
    cle: 'gestionnaire',
    libelle: 'Espace gestionnaire',
    libelleCourt: 'Gestionnaire',
    roles: ['gestionnaire'],
    accueil: '/gestionnaire',
    sections: [
      {
        chemin: '/gestionnaire',
        libelle: 'File d’alertes',
        description:
          'Les factures dont le score dépasse le seuil, triées de la plus suspecte à la moins suspecte.',
        icone: Siren,
      },
      {
        chemin: '/gestionnaire/historique',
        libelle: 'Historique',
        description:
          'Les alertes déjà traitées : la décision, son motif, et qui l’a prise. La trace est conservée.',
        icone: ScrollText,
      },
    ],
  },
  {
    cle: 'administration',
    libelle: 'Espace administration',
    libelleCourt: 'Administration',
    roles: ['administrateur'],
    accueil: '/administration',
    sections: [
      {
        chemin: '/administration',
        libelle: 'Vue d’ensemble',
        description:
          'L’état de la plateforme, le seuil en vigueur, la version du modèle et l’accès direct à chaque réglage.',
        icone: House,
      },
      {
        chemin: '/administration/seuil',
        libelle: 'Seuil d’alerte',
        description:
          'Le seuil qui décide de ce qui entre dans la file du gestionnaire. Il s’applique immédiatement.',
        icone: SlidersHorizontal,
      },
      {
        chemin: '/administration/modele',
        libelle: 'Modèle',
        description:
          'Les versions disponibles, celle en service, et la bascule d’une version à l’autre.',
        icone: Brain,
      },
      {
        chemin: '/administration/sante',
        libelle: 'Santé',
        description:
          'L’état du traitement des factures et de l’assistant, au moment de la vérification.',
        icone: HeartPulse,
      },
      {
        chemin: '/administration/canaux',
        libelle: 'Canaux',
        description:
          'Les notifications par e-mail ou vers un outil de votre choix. Chaque canal se teste avant d’être activé.',
        icone: Bell,
      },
      {
        chemin: '/administration/observabilite',
        libelle: 'Observabilité',
        description:
          'Volume, alertes, erreurs et temps de réponse sur la période choisie.',
        icone: Activity,
      },
      {
        chemin: '/administration/comptes',
        libelle: 'Comptes',
        description:
          'Les utilisateurs de la plateforme, leur rôle, leur état, et la création d’un compte supplémentaire.',
        icone: Users,
      },
      {
        chemin: '/administration/journal',
        libelle: 'Journal des actions',
        description:
          'Les actions sensibles, avec leur auteur et leur date. Le journal est exportable.',
        icone: ScrollText,
      },
      {
        chemin: '/administration/rgpd',
        libelle: 'Droits des personnes',
        description:
          'Export, rectification, opposition et effacement : les quatre demandes que toute personne peut formuler.',
        icone: ShieldCheck,
      },
    ],
  },
]

/** Les pages transverses, accessibles depuis le menu du profil. */
export const PAGES_COMMUNES: Record<string, string> = {
  '/compte': 'Mon compte',
  '/aide': 'Aide',
}

export function libellePage(chemin: string): string {
  return PAGES_COMMUNES[chemin] ?? 'Accueil'
}

export const LIEN_PILOTAGE: Section = {
  chemin: '/pilotage',
  libelle: 'Pilotage BI',
  description: 'Le tableau de bord décisionnel, en lecture seule sur les données de la plateforme.',
  icone: ChartColumn,
}

/** L'espace qui correspond au role connecte, s'il y en a un. */
export function espaceDe(role: Role | undefined): Espace | null {
  if (role === undefined) return null
  return ESPACES.find((espace) => espace.roles.includes(role)) ?? null
}

/** La section correspondant a un chemin donne, dans tous les espaces. */
export function sectionDe(chemin: string): { espace: Espace; section: Section } | null {
  for (const espace of ESPACES) {
    for (const section of espace.sections) {
      if (section.chemin === chemin) return { espace, section }
    }
  }
  return null
}
