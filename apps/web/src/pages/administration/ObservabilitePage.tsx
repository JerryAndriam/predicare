import { useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { Observability } from '../../api/types'
import { Barres } from '../../components/Barres'
import { EnTetePage } from '../../components/blocs'
import {
  Badge,
  Carte,
  Chargement,
  Erreur,
  Kpi,
  Vide,
  dateCourte,
  pourcentage,
} from '../../components/ui'

type Fenetre = '24h' | '7j' | '30j' | '90j'

/** Un nombre lisible, tire de la reponse du serveur. */
function nombre(valeur: number | null | undefined): string {
  if (valeur === null || valeur === undefined || Number.isNaN(valeur)) return '-'
  return new Intl.NumberFormat('fr-FR').format(valeur)
}


/**
 * L'observabilite de la plateforme.
 *
 * La page repond a trois questions : combien de volume est passe, avec
 * quel taux d'erreur, et avec quelle latence. La fenetre se change sans
 * quitter la page.
 */
export function ObservabilitePage() {
  const [observabilite, setObservabilite] = useState<Observability | null>(null)
  const [fenetre, setFenetre] = useState<Fenetre>('30j')
  const [erreur, setErreur] = useState<string | null>(null)

  const chargerObservabilite = async (choix: Fenetre) => {
    try {
      setObservabilite(await api<Observability>(`/api/core/admin/observabilite?fenetre=${choix}`))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  useEffect(() => {
    void chargerObservabilite(fenetre)
  }, [fenetre])

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Observabilité' },
        ]}
        titre="Observabilité"
        chapo="Le volume traité, les alertes, les décisions et les temps de réponse sur la période choisie."

      />

      <Erreur message={erreur} />

      {observabilite === null ? (
        <Carte titre="Observabilité">
          <Chargement />
        </Carte>
      ) : (
        <div className="pile">
          <Carte
            titre="Synthèse d’exploitation"
            actions={
              <>
                <label className="champ-label" htmlFor="fenetre-observabilite">
                  Période
                </label>
                <select
                  id="fenetre-observabilite"
                  value={fenetre}
                  onChange={(event) => setFenetre(event.target.value as Fenetre)}
                >
                  <option value="24h">24 heures</option>
                  <option value="7j">7 jours</option>
                  <option value="30j">30 jours</option>
                  <option value="90j">90 jours</option>
                </select>
              </>
            }
          >
            <div className="resultat-meta">
              <Badge ton={observabilite.base.disponible ? 'ok' : 'alerte'}>
                Données {observabilite.base.disponible ? 'disponibles' : 'indisponibles'}
              </Badge>
              <Badge ton={observabilite.inference.disponible === false ? 'alerte' : 'ok'}>
                Notation {observabilite.inference.disponible === false ? 'indisponible' : 'disponible'}
              </Badge>
              <Badge ton={observabilite.rag.disponible ? 'ok' : 'alerte'}>
                Assistant {observabilite.rag.disponible ? 'disponible' : 'indisponible'}
              </Badge>
              <span className="aide">Relevé du {dateCourte(observabilite.timestamp)}</span>
            </div>
          </Carte>

          <Carte
            titre={`Volume traité par jour (${fenetre})`}
            actions={
              <span className="aide">
                {nombre(
                  observabilite.serie?.reduce((somme, point) => somme + point.factures, 0) ?? 0,
                )}{' '}
                facture(s) sur la période
              </span>
            }
          >
            <Barres
              libelle="Factures déposées par jour"
              points={(observabilite.serie ?? []).map((point) => ({
                etiquette: point.jour.slice(5),
                valeur: point.factures,
                valeurSecondaire: point.alertes,
              }))}
              format={(valeur) => nombre(valeur)}
            />
            <p className="aide">
              Barres pleines : factures déposées. Part rouge : factures ayant déclenché une
              alerte.
            </p>
          </Carte>

          <div className="grille trois grille-kpi">
            <Carte titre="Volume">
              <Kpi titre="Factures enregistrées" valeur={nombre(observabilite.base.factures)} />
              <Kpi titre="Alertes" valeur={nombre(observabilite.base.alertes)} ton="alerte" />
            </Carte>
            <Carte titre="Activité">
              <Kpi titre="Factures notées" valeur={nombre(observabilite.base.predictions)} />
              <Kpi
                titre="Décisions gestionnaire"
                valeur={nombre(observabilite.base.decisions)}
                ton="info"
              />
            </Carte>
            <Carte titre="Erreurs">
              <Kpi
                titre="Erreurs"
                valeur={nombre(observabilite.inference.erreurs_total)}
                ton="avert"
              />
              <p className="aide">
                {nombre(observabilite.inference.requetes_total)} traitement(s) mesuré(s)
                {observabilite.inference.requetes_total
                  ? ` - taux ${pourcentage(
                      (observabilite.inference.erreurs_total ?? 0) /
                        observabilite.inference.requetes_total,
                    )}`
                  : ''}
              </p>
            </Carte>
          </div>

          <Carte titre="Temps de réponse">
            {observabilite.inference.latence_ms?.disponible ? (
              <div className="grille trois grille-kpi">
                <Kpi
                  titre="P50"
                  valeur={`${observabilite.inference.latence_ms.p50?.toFixed(2)} ms`}
                />
                <Kpi
                  titre="P95"
                  valeur={`${observabilite.inference.latence_ms.p95?.toFixed(2)} ms`}
                />
                <Kpi
                  titre="P99"
                  valeur={`${observabilite.inference.latence_ms.p99?.toFixed(2)} ms`}
                />
              </div>
            ) : (
              <Vide>Aucune notation mesurée sur la période.</Vide>
            )}
            <p className="aide">
              {observabilite.inference.latence_ms?.echantillons ?? 0} mesure(s) sur la période.
            </p>
          </Carte>
        </div>
      )}
    </>
  )
}
