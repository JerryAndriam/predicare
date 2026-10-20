import { Link } from 'react-router-dom'

import { ACCUEIL, ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Badge, Carte } from '../components/ui'

const PARCOURS = [
  {
    numero: '1',
    titre: 'Dépôt',
    texte: 'Le professionnel de santé déposé une facture. Le serveur vérifié les references avant tout enregistrement.',
  },
  {
    numero: '2',
    titre: 'Notation',
    texte: 'Le modele XGBoost calcule un score. Un rapport SHAP explique, champ par champ, ce qui a pese.',
  },
  {
    numero: '3',
    titre: 'Decision',
    texte: 'Au-dessus du seuil, une alerte arrive au gestionnaire. Il valide ou rejette, et la decision est tracee.',
  },
]

export function HomePage() {
  const { profile } = useAuth()
  if (profile === null) return null

  return (
    <div className="pile">
      <section className="hero">
        <div>
          <p className="surtitre">Espace {ROLE_LABELS[profile.role]}</p>
          <h1>Bonjour {profile.display_name ?? profile.subject}</h1>
          <p className="hero-texte">
            Vous etes connecte avec le role <Badge ton="info">{ROLE_LABELS[profile.role]}</Badge>.
            Les droits sont verifies par l API a chaque requete, pas seulement par cet ecran.
          </p>
        </div>
      </section>

      <div className="grille deux">
        <Carte titre="Votre espace">
          <p>
            {profile.role === 'assure' &&
              'Consultez vos remboursements et posez vos questions a l assistant.'}
            {profile.role === 'professionnel_sante' &&
              'Deposez une facture ou une ordonnance et suivez les dossiers déjà transmis.'}
            {profile.role === 'gestionnaire' &&
              'Traitez la file d alertes : score, rapport SHAP, puis decision motivee.'}
            {profile.role === 'administrateur' &&
              'Reglez le seuil, supervisez la sante de la plateforme et gerez les versions du modele.'}
          </p>
          <Link className="bouton principal" to={ACCUEIL[profile.role]}>
            Ouvrir mon espace
          </Link>
        </Carte>

        <Carte titre="Vos droits">
          <ul className="liste-simple">
            {profile.role === 'assure' && (
              <>
                <li>Lire uniquement vos propres factures</li>
                <li>Interroger l assistant sur vos garanties</li>
              </>
            )}
            {profile.role === 'professionnel_sante' && (
              <>
                <li>Deposer des factures et des ordonnances</li>
                <li>Suivre les dossiers deposes</li>
              </>
            )}
            {profile.role === 'gestionnaire' && (
              <>
                <li>Lire la file d alertes et le detail SHAP</li>
                <li>Valider, rejeter ou demander une pièce</li>
                <li>Consulter l historique des decisions</li>
              </>
            )}
            {profile.role === 'administrateur' && (
              <>
                <li>Modifier le seuil sans redemarrage</li>
                <li>Charger, basculer ou revenir a une version du modèle</li>
                <li>Lire la santé, les canaux et le journal d audit</li>
              </>
            )}
          </ul>
        </Carte>
      </div>

      <Carte titre="Le parcours d une facture">
        <div className="grille trois">
          {PARCOURS.map((etape) => (
            <div key={etape.numero} className="etape">
              <span className="etape-numero">{etape.numero}</span>
              <h3>{etape.titre}</h3>
              <p>{etape.texte}</p>
            </div>
          ))}
        </div>
      </Carte>
    </div>
  )
}
