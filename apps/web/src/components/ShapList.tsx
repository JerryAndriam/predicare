import type { ShapContribution } from '../api/types'
import { Vide } from './ui'

/**
 * Barres SHAP : longueur proportionnelle a la contribution, couleur selon le
 * sens. Une valeur positive pousse vers la fraude, une valeur negative vers
 * la legitimite. C'est exactement le signe renvoye par le modele.
 */
export function ShapList({ contributions }: { contributions: ShapContribution[] }) {
  if (contributions.length === 0) {
    return <Vide>Aucune contribution SHAP enregistrée pour cette facture.</Vide>
  }

  const maximum = Math.max(...contributions.map((item) => Math.abs(item.shap_value)), 0.0001)

  return (
    <ul className="shap">
      {contributions.map((item) => (
        <li key={`${item.feature}-${item.shap_value}`}>
          <div className="shap-ligne">
            <span className="shap-libelle">{item.human_readable}</span>
            <span className={`shap-valeur ${item.direction}`}>
              {item.shap_value > 0 ? '+' : ''}
              {item.shap_value.toFixed(3)}
            </span>
          </div>
          <div className="barre">
            <span
              className={item.direction}
              style={{ width: `${Math.max(2, (Math.abs(item.shap_value) / maximum) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  )
}
