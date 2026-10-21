import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../../api/client'
import { EnTetePage } from '../../components/blocs'
import { Bouton, Carte, Champ, Erreur, Succes } from '../../components/ui'

/**
 * Le seuil de declenchement des alertes.
 *
 * Une seule regle vit ici : le score au-dessus duquel une facture entre
 * dans la file du gestionnaire. Le changement est immediat et trace.
 */
export function SeuilPage() {
  const [seuil, setSeuil] = useState('')
  const [motif, setMotif] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  useEffect(() => {
    const charger = async () => {
      try {
        const reponse = await api<{ seuil: number }>('/api/core/admin/seuil')
        setSeuil(String(reponse.seuil))
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [])

  const enregistrerSeuil = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<{ status: string }>('/api/core/admin/seuil', {
        method: 'PUT',
        body: JSON.stringify({ seuil: Number(seuil), motif }),
      })
      setSucces('Seuil enregistré. Il s’applique dès maintenant.')
      setMotif('')
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Seuil d’alerte' },
        ]}
        titre="Seuil d’alerte"
        chapo={
          <>
            Le seuil détermine le score à partir duquel une facture est signalée au
            gestionnaire. Il s’applique immédiatement, et chaque changement est conservé
            avec son motif. Un seuil bas augmente le rappel et le nombre d’alertes à
            traiter.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <div className="pile">
        <Carte titre="Seuil de déclenchement des alertes">
          <p className="aide">
            Une facture dont le score dépasse ce seuil entre dans la file du gestionnaire.
            Un seuil plus bas augmente le rappel et le nombre de fausses alertes.
          </p>
          <form className="formulaire" onSubmit={enregistrerSeuil}>
            <div className="grille deux">
              <Champ label="Seuil (entre 0 et 1)">
                <input
                  type="number"
                  min={0}
                  max={1}
                  step="0.001"
                  value={seuil}
                  onChange={(event) => setSeuil(event.target.value)}
                  required
                />
              </Champ>
              <Champ label="Motif du changement" aide="Ce motif sera conservé avec le changement.">
                <input
                  type="text"
                  minLength={3}
                  maxLength={500}
                  value={motif}
                  onChange={(event) => setMotif(event.target.value)}
                  placeholder="Exemple : arbitrage rappel / charge de travail"
                  required
                />
              </Champ>
            </div>
            <Bouton type="submit" variante="principal" desactive={enCours}>
              {enCours ? 'Application…' : 'Appliquer le seuil'}
            </Bouton>
          </form>
        </Carte>

      </div>
    </>
  )
}
