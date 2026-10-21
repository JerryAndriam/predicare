import { useEffect, useRef, useState } from 'react'

import { api, messageErreur } from '../../api/client'
import type { ModelInfo } from '../../api/types'
import { EnTetePage } from '../../components/blocs'
import {
  Badge,
  Bouton,
  Carte,
  Champ,
  Chargement,
  Erreur,
  Succes,
  Vide,
  dateCourte,
  pourcentage,
} from '../../components/ui'

/**
 * Le registre des modeles.
 *
 * Trois gestes : re-controler un stock de factures, charger une version
 * candidate, puis basculer. Charger ne bascule pas : c'est ce qui rend le
 * deploiement sans interruption.
 */
export function ModelePage() {
  const [modele, setModele] = useState<ModelInfo | null>(null)
  const [version, setVersion] = useState('')
  const [recontrole, setRecontrole] = useState<{
    etat: string
    resume: Record<string, unknown>
  } | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)
  const minuteur = useRef<number | undefined>(undefined)

  const chargerModele = async () => {
    const etat = await api<ModelInfo>('/api/core/admin/modele')
    setModele(etat)
    if (etat.active_version !== null) setVersion(etat.active_version)
  }

  useEffect(() => {
    const charger = async () => {
      try {
        await chargerModele()
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
    // Le sondage du re-controle tourne en arriere-plan : il doit s'arreter
    // avec la page.
    return () => {
      if (minuteur.current !== undefined) window.clearInterval(minuteur.current)
    }
  }, [])

  const agirModele = async (chemin: string) => {
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<Record<string, unknown>>(chemin, { method: 'POST' })
      setSucces('Opération appliquée sur le registre de modèles.')
      await chargerModele()
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const lancerRecontrole = async (portee: 'historique' | 'nouvelles') => {
    setRecontrole({ etat: 'en_cours', resume: {} })
    try {
      await api<unknown>('/api/core/admin/modele/recontroler', {
        method: 'POST',
        body: JSON.stringify({ portee }),
      })
    } catch (probleme) {
      setErreur(messageErreur(probleme))
      setRecontrole(null)
      return
    }
    if (minuteur.current !== undefined) window.clearInterval(minuteur.current)
    minuteur.current = window.setInterval(async () => {
      try {
        const etat = await api<{ etat: string; resume: Record<string, unknown> }>(
          '/api/core/admin/modele/recontroler/etat',
        )
        setRecontrole(etat)
        if (etat.etat !== 'en_cours') {
          window.clearInterval(minuteur.current)
          minuteur.current = undefined
        }
      } catch (probleme) {
        setErreur(messageErreur(probleme))
        window.clearInterval(minuteur.current)
        minuteur.current = undefined
      }
    }, 3000)
  }

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Modèle' },
        ]}
        titre="Modèle"
        chapo={
          <>
            Le registre liste les versions disponibles, celle qui est en service et
            celle qui est candidate. Charger une version ne la bascule pas : la version
            en service reste active jusqu’à la bascule. Le retour à une version
            antérieure se fait depuis cette page.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <div className="grille deux">
        <Carte titre="Registre des modèles">
          {modele === null ? (
            <Chargement />
          ) : (
            <div className="pile-serre">
              <div className="resultat-meta">
                <Badge ton={modele.active_version === null ? 'alerte' : 'ok'}>
                  Active : {modele.active_version ?? 'aucune'}
                </Badge>
                <Badge ton="info">Candidate : {modele.candidate_version ?? 'aucune'}</Badge>
                <span>Seuil : {pourcentage(modele.threshold)}</span>
                <span>Charge : {dateCourte(modele.loaded_at)}</span>
              </div>

              <h3>Versions disponibles</h3>
              {modele.available_versions.length === 0 ? (
                <Vide>Aucune autre version n’est disponible.</Vide>
              ) : (
                <p className="mono">{modele.available_versions.join(', ')}</p>
              )}
            </div>
          )}
        </Carte>

        <Carte titre="Re-contrôler un stock de factures">
          <p className="aide">
            Relance la notation des factures déjà enregistrées. Les notes de l’historique
            ne nourrissent pas la file du gestionnaire.
          </p>
          <div className="boutons-ligne">
            <Bouton
              variante="secondaire"
              desactive={recontrole?.etat === 'en_cours'}
              onClick={() => void lancerRecontrole('historique')}
            >
              {recontrole?.etat === 'en_cours'
                ? 'Re-contrôle en cours…'
                : 'Re-contrôler l’historique'}
            </Bouton>
            <Bouton
              variante="discret"
              desactive={recontrole?.etat === 'en_cours'}
              onClick={() => void lancerRecontrole('nouvelles')}
            >
              Re-contrôler les nouvelles
            </Bouton>
          </div>
          {recontrole &&
          recontrole.etat !== 'en_cours' &&
          recontrole.resume &&
          Object.keys(recontrole.resume).length > 0 ? (
            <ul className="liste-simple">
              {Object.entries(recontrole.resume).map(([cle, valeur]) => (
                <li key={cle}>
                  <span className="mono">{cle}</span> : {String(valeur)}
                </li>
              ))}
            </ul>
          ) : null}
        </Carte>

        <Carte titre="Changer de version">
          <div className="formulaire">
            <Champ label="Version" aide="Le numéro d’une version disponible.">
              <input
                type="text"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                placeholder="2"
              />
            </Champ>
            <div className="boutons-ligne">
              <Bouton
                variante="secondaire"
                desactive={enCours || version === ''}
                onClick={() =>
                  void agirModele(
                    `/api/core/admin/modele/candidat?version=${encodeURIComponent(version)}`,
                  )
                }
              >
                Charger la candidate
              </Bouton>
              <Bouton
                variante="principal"
                desactive={enCours}
                onClick={() => void agirModele('/api/core/admin/modele/bascule')}
              >
                Basculer sur la candidate
              </Bouton>
              <Bouton
                variante="danger"
                desactive={enCours || version === ''}
                onClick={() =>
                  void agirModele(
                    `/api/core/admin/modele/retour-arriere?version=${encodeURIComponent(version)}`,
                  )
                }
              >
                Revenir à cette version
              </Bouton>
            </div>
            <p className="aide">
              Charger ne bascule pas : la version en service reste active jusqu’à la
              bascule.
            </p>
          </div>
        </Carte>
      </div>

    </>
  )
}
