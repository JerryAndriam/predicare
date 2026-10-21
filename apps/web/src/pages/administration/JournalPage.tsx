import { useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { AuditEntry, PageResult } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import { Bouton, Carte, Champ, Erreur, EtatVide, Pagination, dateCourte } from '../../components/ui'

/** Taille d'une page de journal : le journal est volumineux. */
const LIMITE_JOURNAL = 50

/**
 * Le journal d'audit.
 *
 * Il enregistre les actions sensibles de la plateforme : connexion,
 * decision du gestionnaire, changement de seuil, gestion de compte. Il se
 * filtre cote serveur, et l'export porte sur l'ecran courant.
 */
export function JournalPage() {
  const [journal, setJournal] = useState<AuditEntry[]>([])
  const [totalJournal, setTotalJournal] = useState(0)
  const [offsetJournal, setOffsetJournal] = useState(0)
  const [filtreAction, setFiltreAction] = useState('')
  const [filtreActeur, setFiltreActeur] = useState('')
  const [filtreCible, setFiltreCible] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const chargerJournal = async (decalage: number) => {
    const params = new URLSearchParams({
      limit: String(LIMITE_JOURNAL),
      offset: String(decalage),
    })
    if (filtreAction.trim() !== '') params.set('action', filtreAction.trim())
    if (filtreActeur.trim() !== '') params.set('acteur', filtreActeur.trim())
    if (filtreCible.trim() !== '') params.set('cible', filtreCible.trim())
    const page = await api<PageResult<AuditEntry>>(`/api/core/audit/journal?${params.toString()}`)
    setJournal(page.items)
    setTotalJournal(page.total)
    setOffsetJournal(page.offset)
  }

  useEffect(() => {
    const charger = async () => {
      try {
        await chargerJournal(0)
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [])

  const appliquerFiltresJournal = () => {
    void chargerJournal(0).catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }

  const reinitialiserJournal = () => {
    setFiltreAction('')
    setFiltreActeur('')
    setFiltreCible('')
    const params = new URLSearchParams({ limit: String(LIMITE_JOURNAL), offset: '0' })
    void api<PageResult<AuditEntry>>(`/api/core/audit/journal?${params.toString()}`)
      .then((page) => {
        setJournal(page.items)
        setTotalJournal(page.total)
        setOffsetJournal(page.offset)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }

  /**
   * Export CSV du journal affiché.
   *
   * L'export porte sur ce que l'écran montre (page courante, filtres
   * appliqués) : un export de TOUT le journal alors que l'écran n'en montre
   * qu'une page serait une surprise pour le lecteur.
   */
  const exporterJournal = () => {
    const entetes = ['id', 'created_at', 'acteur', 'rôle', 'action', 'cible', 'details']
    const lignes = journal.map((entree) =>
      [
        entree.id,
        entree.created_at,
        entree.acteur,
        entree.role,
        entree.action,
        entree.cible ?? '',
        JSON.stringify(entree.details ?? {}),
      ]
        .map((valeur) => `"${String(valeur).replace(/"/g, '""')}"`)
        .join(';'),
    )
    const contenu = [entetes.join(';'), ...lignes].join('\r\n')
    const blob = new Blob([`﻿${contenu}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `journal-audit-${new Date().toISOString().slice(0, 10)}.csv`
    lien.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Journal des actions' },
        ]}
        titre="Journal des actions"
        chapo={
          <>
            Le journal des actions enregistre les actions sensibles de la plateforme :
            connexion, décision du gestionnaire, changement de seuil, gestion de compte. Il
            se filtre par action, par acteur et par cible, et l’affichage courant
            s’exporte en CSV.
          </>
        }
      />

      <Erreur message={erreur} />

      <Carte
        titre={`Journal des actions (${totalJournal} entrées)`}
        actions={
          <div className="carte-actions">
            <Bouton variante="discret" onClick={exporterJournal}>
              Exporter en CSV
            </Bouton>
          </div>
        }
      >
        <div className="grille quatre">
          <Champ label="Action">
            <input
              value={filtreAction}
              placeholder="Décision, connexion…"
              onChange={(event) => setFiltreAction(event.target.value)}
            />
          </Champ>
          <Champ label="Acteur">
            <input
              value={filtreActeur}
              placeholder="Nom ou adresse e-mail"
              onChange={(event) => setFiltreActeur(event.target.value)}
            />
          </Champ>
          <Champ label="Cible">
            <input
              value={filtreCible}
              placeholder="Dossier ou compte…"
              onChange={(event) => setFiltreCible(event.target.value)}
            />
          </Champ>
          <div className="carte-actions" style={{ alignItems: 'flex-end' }}>
            <Bouton variante="principal" onClick={appliquerFiltresJournal}>
              Appliquer
            </Bouton>
            <Bouton variante="discret" onClick={reinitialiserJournal}>
              Réinitialiser
            </Bouton>
          </div>
        </div>

        {journal.length === 0 ? (
          <EtatVide
            titre="Aucune entrée pour le moment"
            texte="Le journal se remplit automatiquement : connexion, décision du gestionnaire, changement de seuil, gestion de compte."
          />
        ) : (
          <>
            <div className="table-enveloppe">
              <table className="table table-dense">
                <caption className="visuellement-cache">
                  Journal des actions de la plateforme
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Acteur</th>
                    <th scope="col">Rôle</th>
                    <th scope="col">Action</th>
                    <th scope="col">Cible</th>
                    <th scope="col">Détails</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.map((entree) => (
                    <tr key={entree.id}>
                      <td>{dateCourte(entree.created_at)}</td>
                      <td className="mono">{entree.acteur}</td>
                      <td>{entree.role}</td>
                      <td>
                        <span className="mono">{entree.action}</span>
                      </td>
                      <td className="mono">{entree.cible ?? '—'}</td>
                      <td>
                        {entree.details === null ||
                        Object.keys(entree.details).length === 0 ? (
                          <span className="aide">—</span>
                        ) : (
                          <details className="journal-details">
                            <summary>Voir</summary>
                            <dl className="journal-details-liste">
                              {Object.entries(entree.details).map(([cle, valeur]) => (
                                <div key={cle}>
                                  <dt className="mono">{cle}</dt>
                                  <dd>
                                    {typeof valeur === 'object' && valeur !== null
                                      ? JSON.stringify(valeur)
                                      : String(valeur)}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              total={totalJournal}
              offset={offsetJournal}
              limite={LIMITE_JOURNAL}
              onChange={(decalage) => {
                void chargerJournal(decalage).catch((probleme: unknown) =>
                  setErreur(messageErreur(probleme)),
                )
              }}
              libelle="entrées"
            />
          </>
        )}
      </Carte>

    </>
  )
}
