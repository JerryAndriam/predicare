import { useEffect, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { ChannelTestResult, NotificationChannel } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import { Badge, Bouton, Carte, Chargement, Erreur, Succes } from '../../components/ui'

/**
 * Les canaux de notification : destinataire, activation et envoi d'essai.
 */
export function CanauxPage() {
  const [canaux, setCanaux] = useState<NotificationChannel[]>([])
  const [canauxEdition, setCanauxEdition] = useState<
    Record<string, { actif: boolean; destinataire: string }>
  >({})
  const [testCanal, setTestCanal] = useState<ChannelTestResult | null>(null)
  const [testEnCours, setTestEnCours] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  useEffect(() => {
    const charger = async () => {
      try {
        const valeurs = await api<NotificationChannel[]>('/api/core/admin/canaux')
        setCanaux(valeurs)
        setCanauxEdition(
          Object.fromEntries(
            valeurs.map((canal) => [
              canal.nom,
              { actif: canal.actif, destinataire: canal.destinataire },
            ]),
          ),
        )
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [])

  const enregistrerCanal = async (nom: string) => {
    const reglage = canauxEdition[nom]
    if (reglage === undefined) return
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<NotificationChannel>(`/api/core/admin/canaux/${encodeURIComponent(nom)}`, {
        method: 'PUT',
        body: JSON.stringify(reglage),
      })
      setSucces(`Canal ${nom} enregistré.`)
      setCanaux(await api<NotificationChannel[]>('/api/core/admin/canaux'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const testerUnCanal = async (nom: string) => {
    setTestEnCours(true)
    setTestCanal(null)
    setErreur(null)
    try {
      setTestCanal(
        await api<ChannelTestResult>(`/api/core/admin/canaux/${encodeURIComponent(nom)}/test`, {
          method: 'POST',
        }),
      )
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setTestEnCours(false)
    }
  }



  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Canaux' },
        ]}
        titre="Canaux de notification"
        chapo={
          <>
            Chaque canal se règle ici : destinataire, activation et envoi d’essai. Un
            canal actif mais sans destinataire reste « non configuré » : le badge Actif
            ne garantit pas qu’une alerte parte.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <div className="pile">
        <Carte titre="Canaux de notification">
          <p className="aide">
            Un canal sans destinataire reste « non configuré » : le badge Actif ne
            garantit pas qu’une alerte parte.
          </p>
          {canaux.length === 0 ? (
            <Chargement />
          ) : (
            <div className="table-enveloppe">
              <table className="table">
                <caption className="visuellement-cache">
                  Canaux de notification configurés et leur état
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Nom</th>
                    <th scope="col">Type</th>
                    <th scope="col">Configuré</th>
                    <th scope="col">Actif</th>
                    <th scope="col">Destinataire</th>
                    <th scope="col">
                      <span className="visuellement-cache">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {canaux.map((canal) => {
                    const reglage = canauxEdition[canal.nom] ?? {
                      actif: canal.actif,
                      destinataire: canal.destinataire,
                    }
                    return (
                      <tr key={canal.nom}>
                        <td>{canal.nom}</td>
                        <td>{canal.type}</td>
                        <td>
                          <Badge ton={canal.configure ? 'ok' : 'alerte'}>
                            {canal.configure ? 'configuré' : 'non configuré'}
                          </Badge>
                        </td>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Activer ${canal.nom}`}
                            checked={reglage.actif}
                            onChange={(event) =>
                              setCanauxEdition((precedent) => ({
                                ...precedent,
                                [canal.nom]: {
                                  ...reglage,
                                  actif: event.target.checked,
                                },
                              }))
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className="mono"
                            aria-label={`Destinataire ${canal.nom}`}
                            value={reglage.destinataire}
                            onChange={(event) =>
                              setCanauxEdition((precedent) => ({
                                ...precedent,
                                [canal.nom]: {
                                  ...reglage,
                                  destinataire: event.target.value,
                                },
                              }))
                            }
                          />
                        </td>
                        <td className="droite">
                          <div className="carte-actions">
                            <Bouton
                              variante="discret"
                              desactive={testEnCours}
                              onClick={() => void testerUnCanal(canal.nom)}
                            >
                              {testEnCours ? 'Envoi…' : 'Tester'}
                            </Bouton>
                            <Bouton
                              variante="principal"
                              desactive={enCours}
                              onClick={() => void enregistrerCanal(canal.nom)}
                            >
                              Enregistrer
                            </Bouton>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {testCanal !== null && (
            <p className={testCanal.envoye ? 'succes' : 'erreur'} role="status">
              {testCanal.envoye ? '✓ ' : '✕ '}
              {testCanal.message}
            </p>
          )}
        </Carte>

      </div>
    </>
  )
}
