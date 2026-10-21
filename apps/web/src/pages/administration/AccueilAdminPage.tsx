import { useEffect, useState } from 'react'
import {
  Activity,
  Bell,
  Brain,
  HeartPulse,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  Users,
} from 'lucide-react'

import { api, messageErreur } from '../../api/client'
import { ROLE_LABELS, type ModelInfo } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { EnTetePage, StatCle, Tuile } from '../../components/blocs'
import { Erreur, pourcentage } from '../../components/ui'

/**
 * L'accueil de l'espace administration.
 *
 * La page ne regle rien : elle montre l'etat courant (role, version du
 * modele, seuil) et donne acces aux neuf sections.
 */
export function AccueilAdminPage() {
  const { profile } = useAuth()
  const [resume, setResume] = useState<{ version: string | null; seuil: number } | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    const charger = async () => {
      try {
        const [etat, seuil] = await Promise.all([
          api<ModelInfo>('/api/core/admin/modele'),
          api<{ seuil: number }>('/api/core/admin/seuil'),
        ])
        setResume({ version: etat.active_version, seuil: seuil.seuil })
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [])

  const role = profile === null ? 'Administrateur' : ROLE_LABELS[profile.role]

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Vue d’ensemble' },
        ]}
        titre="Administration"
        chapo={
          <>
            Cet espace regroupe les réglages de la plateforme : le seuil qui déclenche les
            alertes, la version du modèle en service et les comptes utilisateurs. Les
            neuf sections ci-dessous mènent à chaque écran de l’espace.
          </>
        }
      />

      <Erreur message={erreur} />

      <div className="stats">
        <StatCle
          valeur={role}
          libelle="Votre rôle"
          contexte="Droits complets sur les réglages de la plateforme"
        />
        <StatCle
          valeur={resume?.version ?? '-'}
          libelle="Version du modèle en service"
          contexte="Version actuellement utilisée"
          ton="info"
        />
        <StatCle
          valeur={resume === null ? '-' : pourcentage(resume.seuil)}
          libelle="Seuil de déclenchement"
          contexte="Score au-delà duquel une facture est signalée"
        />
      </div>

      <section className="accueil-section">
        <h2>Les neuf sections de l’espace</h2>
        <p className="accueil-section-chapo">
          Chaque réglage se fait là où il s’applique, et il est conservé avec son auteur
          et sa date.
        </p>
        <div className="tuiles">
          <Tuile
            icone={Upload}
            titre="Import de lot"
            texte="Déposer les factures PDF du jury en un seul lot. Le bilan indique, fichier par fichier, ce qui est noté et ce qui est rejeté."
            chemin="/administration/import-lot"
          />
          <Tuile
            icone={SlidersHorizontal}
            titre="Seuil d’alerte"
            texte="Le score à partir duquel une facture entre dans la file du gestionnaire. Il s’applique immédiatement."
            chemin="/administration/seuil"
          />
          <Tuile
            icone={Brain}
            titre="Modèle"
            texte="Les versions disponibles, celle en service, et la bascule d’une version à l’autre."
            chemin="/administration/modele"
          />
          <Tuile
            icone={HeartPulse}
            titre="Santé"
            texte="L’état du traitement des factures et de l’assistant, au moment de la vérification."
            chemin="/administration/sante"
          />
          <Tuile
            icone={Bell}
            titre="Canaux"
            texte="Les notifications par e-mail ou vers un outil de votre choix. Chaque canal se teste avant d’être activé."
            chemin="/administration/canaux"
          />
          <Tuile
            icone={Activity}
            titre="Observabilité"
            texte="Volume, alertes, erreurs et temps de réponse sur la période choisie."
            chemin="/administration/observabilite"
          />
          <Tuile
            icone={Users}
            titre="Comptes"
            texte="Les utilisateurs de la plateforme, leur rôle, leur état, et la création d’un compte supplémentaire."
            chemin="/administration/comptes"
          />
          <Tuile
            icone={ScrollText}
            titre="Journal des actions"
            texte="Les actions sensibles, avec leur auteur et leur date. Le journal est exportable."
            chemin="/administration/journal"
          />
          <Tuile
            icone={ShieldCheck}
            titre="Droits des personnes"
            texte="Export, rectification, opposition et effacement : les quatre demandes que toute personne peut formuler."
            chemin="/administration/rgpd"
          />
        </div>
      </section>

    </>
  )
}

