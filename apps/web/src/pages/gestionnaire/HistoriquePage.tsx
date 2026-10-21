import { useCallback, useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { DecisionRecord, PageResult } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import {
  Carte,
  Erreur,
  EtatVide,
  Pagination,
  dateCourte,
  pourcentage,
} from '../../components/ui'

const LIMITE = 20

export function HistoriquePage() {
  const [historique, setHistorique] = useState<DecisionRecord[]>([])
  const [totalHistorique, setTotalHistorique] = useState(0)
  const [offsetHistorique, setOffsetHistorique] = useState(0)
  const chargerHistorique = useCallback((decalage: number) => {
    api<PageResult<DecisionRecord>>(
      `/api/core/alertes/historique?limit=${LIMITE}&offset=${decalage}`,
    )
      .then((page) => {
        setHistorique(page.items)
        setTotalHistorique(page.total)
        setOffsetHistorique(page.offset)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }, [])
  useEffect(() => {
    chargerHistorique(0)
  }, [chargerHistorique])
  const exporterHistorique = () => {
    const entetes = ['decided_at', 'prediction_id', 'decision', 'score_fraude', 'commentaire']
    const lignes = historique.map((ligne) =>
      [
        ligne.decided_at,
        ligne.prediction_id,
        ligne.decision,
        String(ligne.score_fraude),
        ligne.commentaire ?? '',
      ]
        .map((valeur) => `"${String(valeur).replace(/"/g, '""')}"`)
        .join(';'),
    )
    const contenu = [entetes.join(';'), ...lignes].join('\r\n')
    const blob = new Blob([`﻿${contenu}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `decisions-${new Date().toISOString().slice(0, 10)}.csv`
    lien.click()
    URL.revokeObjectURL(url)
  }

  const [erreur, setErreur] = useState<string | null>(null)

  return (
    <>
      <EnTetePage
        fil={[{ libelle: 'Espace gestionnaire', chemin: '/gestionnaire' }, { libelle: 'Historique' }]}
        titre="Historique des décisions"
        chapo={
          <>
            Les alertes déjà traitées : la décision, son motif, son auteur et son
            horodatage. L’export porte sur la page affichée, afin de correspondre
            exactement à ce que vous voyez.
          </>
        }
      />

      <Erreur message={erreur} />

      <Carte
        titre={`${totalHistorique} décision(s)`}
        actions={
          <div className="carte-actions">
            <button
              type="button"
              className="bouton discret"
              onClick={exporterHistorique}
            >
              Exporter en CSV
            </button>
          </div>
        }
      >
        {historique.length === 0 ? (
          <EtatVide
            titre="Aucune décision enregistrée"
            texte="Les alertes que vous traiterez apparaîtront ici, avec leur motif et leur horodatage."
          />
        ) : (
          <>
            <div className="table-enveloppe">
              <table className="table table-dense">
                <caption className="visuellement-cache">
                  Les décisions prises sur les alertes, avec leur motif et leur auteur
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Alerte</th>
                    <th scope="col">Décision</th>
                    <th scope="col">Score</th>
                    <th scope="col">Motif</th>
                    <th scope="col">Décideur</th>
                  </tr>
                </thead>
                <tbody>
                  {historique.map((ligne) => (
                    <tr key={ligne.prediction_id}>
                      <td>{dateCourte(ligne.decided_at)}</td>
                      <td className="mono">{ligne.prediction_id}</td>
                      <td>{ligne.decision === 'valider_fraude' ? 'Fraude confirmée' : ligne.decision === 'rejeter' ? 'Rejetée (faux positif)' : 'Pièce demandée'}</td>
                      <td>{pourcentage(ligne.score_fraude)}</td>
                      <td>{ligne.commentaire ?? '—'}</td>
                      <td>{ligne.decided_by ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              total={totalHistorique}
              offset={offsetHistorique}
              limite={LIMITE}
              onChange={chargerHistorique}
              libelle="décisions"
            />
          </>
        )}
      </Carte>
    </>
  )
}
