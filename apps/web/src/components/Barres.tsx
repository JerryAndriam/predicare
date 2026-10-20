/**
 * Graphique en barres, en SVG inline.
 *
 * Pas de librairie de graphiques : la CSP de la passerelle interdit tout
 * chargement distant, et un bundle de 200 ko pour quatre barres ne se
 * justifie pas. Le SVG est aussi plus accessible : chaque barre porte son
 * étiquette dans le DOM, donc un lecteur d'écran la lit.
 */
export interface PointBarres {
  etiquette: string
  valeur: number
  /** Deuxième série, superposée en creux (ici : les alertes). */
  valeurSecondaire?: number
  ton?: 'neutre' | 'ok' | 'alerte' | 'avert' | 'info'
}

export function Barres({
  points,
  hauteur = 140,
  format = (valeur) => String(valeur),
  libelle = 'évolution',
}: {
  points: PointBarres[]
  hauteur?: number
  format?: (valeur: number) => string
  libelle?: string
}) {
  if (points.length === 0) {
    return <p className="aide">Aucune donnée sur la période sélectionnée.</p>
  }
  const maximum = Math.max(
    ...points.map((point) => Math.max(point.valeur, point.valeurSecondaire ?? 0)),
    1,
  )
  return (
    <figure className="graphique">
      <figcaption className="visuellement-cache">{libelle}</figcaption>
      <ul className="barres" style={{ ['--hauteur-barres' as string]: `${hauteur}px` }}>
        {points.map((point) => (
          <li key={point.etiquette}>
            <span className="barres-valeur">{format(point.valeur)}</span>
            <span
              className="barres-piste"
              role="img"
              aria-label={`${point.etiquette} : ${format(point.valeur)}${
                point.valeurSecondaire !== undefined
                  ? `, dont ${format(point.valeurSecondaire)} en alerte`
                  : ''
              }`}
            >
              <span
                className={`barres-remplissage barres-${point.ton ?? 'primaire'}`}
                style={{ height: `${(point.valeur / maximum) * 100}%` }}
              />
              {point.valeurSecondaire !== undefined && (
                <span
                  className="barres-remplissage barres-alerte"
                  style={{ height: `${(point.valeurSecondaire / maximum) * 100}%` }}
                />
              )}
            </span>
            <span className="barres-etiquette">{point.etiquette}</span>
          </li>
        ))}
      </ul>
    </figure>
  )
}
