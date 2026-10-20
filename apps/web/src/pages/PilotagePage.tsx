import { useEffect, useState } from 'react'

import { Carte, Chargement, EtatVide } from '../components/ui'

/**
 * Tableau de bord BI, integre a l'application.
 *
 * Le tableau Superset est PROXYFIE par la passerelle sous `/bi` : l'iframe
 * est donc de MEME ORIGINE que l'application, et la politique de securite
 * (CSP) n'a besoin d'aucune derogation pour un tiers.
 *
 * Superset ne demarre que si le profil `bi` est actif (`make up-bi`). Le
 * repli n'est donc pas une precaution theorique : sans le service, l'iframe
 * affiche une erreur de la passerelle. On detecte cet echec et on propose
 * le lien direct plutot que de laisser une page blanche.
 */
const URL_BI = '/bi'

export function PilotagePage() {
  const [etat, setEtat] = useState<'chargement' | 'ok' | 'indisponible'>('chargement')

  useEffect(() => {
    // On teste la disponibilite du service AVANT de rendre l'iframe : une
    // iframe qui recoit la page d'erreur 502 de la passerelle s'affiche
    // quand meme, et l'utilisateur y verrait une erreur brute au lieu du
    // repli qui explique comment demarrer le profil `bi`.
    const controller = new AbortController()
    const minuteur = setTimeout(() => controller.abort(), 5000)
    fetch('/bi/health', { signal: controller.signal })
      .then((reponse) => {
        // La SPA renvoie du HTML pour toute route inconnue : repondre
        // « ok » sur la seule base du code HTTP donnerait un faux
        // positif. Seule une reponse non-HTML atteste que le service de
        // pilotage repond derriere la passerelle.
        const type = reponse.headers.get('content-type') ?? ''
        setEtat(reponse.ok && !type.includes('text/html') ? 'ok' : 'indisponible')
      })
      .catch(() => setEtat('indisponible'))
      .finally(() => clearTimeout(minuteur))
    return () => controller.abort()
  }, [])

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Pilotage décisionnel</h1>
        <p>
          Le tableau de bord Superset est branché en lecture seule sur la base. Il est
          servi par la même passerelle que l’application : aucune seconde connexion à
          ouvrir.
        </p>
      </div>

      {etat === 'chargement' && <Chargement texte="Test du service de pilotage…" />}

      {etat === 'indisponible' && (
        <Carte titre="Tableau de bord indisponible">
          <EtatVide
            titre="Le service de pilotage n’est pas démarré"
            texte="Le tableau de bord est un profil optionnel de la plateforme. Lancez « make up-bi » pour le démarrer, puis rechargez cette page."
            action={
              <a className="bouton principal" href={URL_BI} target="_blank" rel="noreferrer">
                Ouvrir le tableau de bord
              </a>
            }
          />
        </Carte>
      )}

      {etat === 'ok' && (
        <Carte
          titre="Tableau de bord"
          actions={
            <a className="bouton discret" href={URL_BI} target="_blank" rel="noreferrer">
              Ouvrir dans un onglet
            </a>
          }
        >
          <iframe
            className="bi-frame"
            src={URL_BI}
            title="Tableau de bord décisionnel PrediCare"
          />
        </Carte>
      )}
    </div>
  )
}
