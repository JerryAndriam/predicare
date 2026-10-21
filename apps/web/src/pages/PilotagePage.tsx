import { useEffect, useState } from 'react'

import { EnTetePage } from '../components/blocs'
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
// Le tableau lui-meme, pas la page d'accueil de Superset. Le parametre
// `standalone` masque la navigation de l'outil : le lecteur reste dans la
// plateforme. Superset sert ses pages sous `/superset/...` ; la passerelle
// retire le prefixe `/bi` (middleware `stripPrefix`).
const URL_TABLEAU = `${URL_BI}/superset/dashboard/pilotage-mensuel/?standalone=true`
// Sonde de disponibilite : l'API de Superset repond en JSON (401 sans
// session). Une reponse HTML prouverait que c'est l'application web qui a
// repondu, donc que le service de pilotage est absent.
const URL_SONDE = `${URL_BI}/api/v1/dashboard/?q=(page:0,page_size=1)`

export function PilotagePage() {
  const [etat, setEtat] = useState<'chargement' | 'ok' | 'indisponible'>('chargement')

  useEffect(() => {
    // On teste la disponibilite du service AVANT de rendre l'iframe : une
    // iframe qui recoit la page d'erreur 502 de la passerelle s'affiche
    // quand meme, et l'utilisateur y verrait une erreur brute au lieu du
    // repli qui explique comment demarrer le profil `bi`.
    const controller = new AbortController()
    const minuteur = setTimeout(() => controller.abort(), 5000)
    fetch(URL_SONDE, { signal: controller.signal })
      .then((reponse) => {
        // La SPA renvoie du HTML pour toute route inconnue : repondre
        // « ok » sur la seule base du code HTTP donnerait un faux
        // positif. Seule une reponse non-HTML atteste que le service de
        // pilotage repond derriere la passerelle.
        const type = reponse.headers.get('content-type') ?? ''
        // Sans session, Superset repond 401 en JSON : c'est deja la preuve
        // que le service repond. Seule une reponse HTML signifie que c'est
        // l'application web qui a repondu a la place.
        const json = type.includes('application/json')
        setEtat(json ? 'ok' : 'indisponible')
      })
      .catch(() => setEtat('indisponible'))
      .finally(() => clearTimeout(minuteur))
    return () => controller.abort()
  }, [])

  return (
    <div className="pile">
      <EnTetePage
        fil={[{ libelle: 'Pilotage décisionnel' }]}
        titre="Pilotage décisionnel"
        chapo={
          <>
            Le tableau de bord Superset est branché en lecture seule sur la base : il
            montre le volume de factures, la fraude détectée, le cycle de décision et les
            meilleurs prestataires. Il est servi par la même passerelle que
            l’application, sans seconde connexion à ouvrir.
          </>
        }
      />

      {etat === 'chargement' && <Chargement texte="Test du service de pilotage…" />}

      {etat === 'indisponible' && (
        <Carte titre="Tableau de bord indisponible">
          <EtatVide
            titre="Le service de pilotage n’est pas démarré"
            texte="Le tableau de bord est un profil optionnel de la plateforme. Lancez « make up-bi » pour le démarrer, puis rechargez cette page."
            action={
              <a className="bouton principal" href={URL_TABLEAU} target="_blank" rel="noreferrer">
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
            <a className="bouton discret" href={URL_TABLEAU} target="_blank" rel="noreferrer">
              Ouvrir dans un onglet
            </a>
          }
        >
          <iframe
            className="bi-frame"
            src={URL_TABLEAU}
            title="Tableau de bord décisionnel PrediCare"
          />
        </Carte>
      )}
    </div>
  )
}
