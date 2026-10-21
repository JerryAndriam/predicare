import { useState } from 'react'

import { api, messageErreur } from '../../api/client'
import { EnTetePage } from '../../components/blocs'
import { Bouton, Carte, Champ, Erreur } from '../../components/ui'

/**
 * Les droits des personnes.
 *
 * Quatre demandes : l'acces, la rectification, l'opposition et
 * l'effacement. Elles s'exercent dossier par dossier, a partir du
 * pseudonyme que la personne porte dans la plateforme.
 */
export function RgpdPage() {
  const [pseudonymeRgpd, setPseudonymeRgpd] = useState('')
  const [messageRgpd, setMessageRgpd] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const requeteRgpd = async (
    chemin: string,
    options: { methode: string; corps?: unknown } = { methode: 'GET' },
  ) => {
    const reponse = await api<unknown>(`/api/core/rgpd${chemin}`, {
      method: options.methode,
      body: options.corps ? JSON.stringify(options.corps) : undefined,
    })
    setMessageRgpd('Opération effectuée.')
    return reponse
  }

  const exporterDossier = async () => {
    if (!pseudonymeRgpd) return
    setErreur(null)
    try {
      const dossier = await api<Record<string, unknown>>(
        `/api/core/rgpd/assures/${encodeURIComponent(pseudonymeRgpd)}/export`,
      )
      // Le dossier est téléchargé en JSON : c'est le format que la personne
      // peut relire, et le seul que l'API maintient.
      const blob = new Blob([JSON.stringify(dossier, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const lien = document.createElement('a')
      lien.href = url
      lien.download = `dossier-${pseudonymeRgpd}.json`
      lien.click()
      URL.revokeObjectURL(url)
      setMessageRgpd('Export téléchargé.')
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  const effacerDossier = async () => {
    if (!pseudonymeRgpd) return
    if (
      !window.confirm(
        `Effacer définitivement le dossier ${pseudonymeRgpd} ? Cette opération est irréversible.`,
      )
    ) {
      return
    }
    setErreur(null)
    try {
      await requeteRgpd(`/assures/${encodeURIComponent(pseudonymeRgpd)}`, { methode: 'DELETE' })
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  const rectifierIdentite = async () => {
    setErreur(null)
    try {
      await requeteRgpd(`/assures/${encodeURIComponent(pseudonymeRgpd)}/identite`, {
        methode: 'PUT',
        corps: { nom: `Rectifie ${new Date().toISOString().slice(0, 10)}` },
      })
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  const opposer = async () => {
    setErreur(null)
    try {
      await requeteRgpd(`/assures/${encodeURIComponent(pseudonymeRgpd)}/opposition`, {
        methode: 'POST',
      })
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  return (
    <>
      <EnTetePage
        fil={[
          { libelle: 'Espace administration', chemin: '/administration' },
          { libelle: 'Droits des personnes' },
        ]}
        titre="Droits des personnes"
        chapo={
          <>
            L’export, la rectification, l’opposition et l’effacement d’un dossier. L’export
            rend l’identité en clair : c’est le droit d’accès de la personne. L’effacement
            supprime les données métier et conserve une trace anonyme de l’opération.
          </>
        }
      />

      <Erreur message={erreur} />

      <div className="pile">
        <Carte titre="Droits des personnes">
          <p className="aide">
            L&apos;export, la rectification, l&apos;opposition et l&apos;effacement
            d&apos;un dossier. L&apos;export rend l&apos;identité en clair : c&apos;est le droit
            d&apos;accès de la personne. L&apos;effacement supprime les données métier et
            conserve une trace anonyme de l&apos;opération.
          </p>
          <div className="formulaire">
            <Champ
              label="Référence du dossier"
              aide="La référence affichée dans l’historique de l’assuré."
            >
              <input
                type="text"
                value={pseudonymeRgpd}
                onChange={(event) => setPseudonymeRgpd(event.target.value)}
                placeholder="assr_..."
              />
            </Champ>
            <div className="boutons-ligne">
              <Bouton
                variante="secondaire"
                desactive={!pseudonymeRgpd}
                onClick={() => void exporterDossier()}
              >
                Exporter
              </Bouton>
              <Bouton
                variante="contour"
                desactive={!pseudonymeRgpd}
                onClick={() => void rectifierIdentite()}
              >
                Rectifier
              </Bouton>
              <Bouton
                variante="contour"
                desactive={!pseudonymeRgpd}
                onClick={() => void opposer()}
              >
                Opposer
              </Bouton>
              <Bouton
                variante="danger"
                desactive={!pseudonymeRgpd}
                onClick={() => void effacerDossier()}
              >
                Effacer
              </Bouton>
            </div>
            {messageRgpd ? <p className="aide">{messageRgpd}</p> : null}
          </div>
        </Carte>

      </div>
    </>
  )
}
