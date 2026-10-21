import { useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { PlatformHealth } from '../../api/types'
import { EnTetePage, StatCle } from '../../components/blocs'
import { Badge, Carte, Chargement, Erreur, dateCourte, pourcentage } from '../../components/ui'

function tonSante(statut: string): 'ok' | 'alerte' | 'neutre' {
  if (statut === 'ok') return 'ok'
  if (statut === 'degraded') return 'alerte'
  return 'neutre'
}

function tonStatut(statut: string): 'primaire' | 'alerte' | 'info' {
  if (statut === 'ok') return 'primaire'
  if (statut === 'degraded') return 'alerte'
  return 'info'
}

function etatLisible(statut: string): string {
  if (statut === 'ok') return 'Disponible'
  if (statut === 'degraded') return 'Dégradé'
  return 'Indisponible'
}

export function SantePage() {
  const [sante, setSante] = useState<PlatformHealth | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    const charger = async () => {
      try {
        setSante(await api<PlatformHealth>('/api/core/admin/sante'))
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [])

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Santé' },
        ]}
        titre="Santé de la plateforme"
        chapo="L’état des services au moment de la vérification. Un service dégradé reste utilisable : consultez les erreurs et les temps de réponse s’il persiste."
      />

      <Erreur message={erreur} />

      {sante === null ? (
        <Chargement />
      ) : (
        <div className="pile">
          <div className="stats">
            <StatCle
              valeur={
                sante.dependances.base
                  ? etatLisible(sante.dependances.inference.status)
                  : 'Indisponible'
              }
              libelle="Traitement des factures"
              contexte="Dépôt, contrôle et notation"
              ton={tonStatut(sante.dependances.inference.status)}
            />
            <StatCle
              valeur={etatLisible(sante.dependances.rag.status)}
              libelle="Assistant garanties"
              contexte={`${sante.dependances.rag.documents ?? 0} document(s) disponible(s)`}
              ton={tonStatut(sante.dependances.rag.status)}
            />
            <StatCle
              valeur={pourcentage(sante.seuil)}
              libelle="Seuil d’alerte"
              contexte="Score au-delà duquel un dossier est signalé"
            />
          </div>

          <Carte titre="État des services">
            <div className="grille deux">
              <div className="sonde">
                <span className="champ-label">Traitement des factures</span>
                <Badge ton={tonSante(sante.dependances.inference.status)}>
                  {etatLisible(sante.dependances.inference.status)}
                </Badge>
                <span className="aide">Dépôt, contrôle des références et notation.</span>
              </div>
              <div className="sonde">
                <span className="champ-label">Assistant garanties</span>
                <Badge ton={tonSante(sante.dependances.rag.status)}>
                  {etatLisible(sante.dependances.rag.status)}
                </Badge>
                <span className="aide">
                  {sante.dependances.rag.documents ?? 0} document(s) disponible(s) pour
                  répondre aux questions.
                </span>
              </div>
            </div>
            <p className="aide">
              Vérification du {dateCourte(sante.timestamp)}.
            </p>
          </Carte>
        </div>
      )}
    </>
  )
}
