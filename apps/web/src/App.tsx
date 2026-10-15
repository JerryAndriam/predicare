const ROLES = [
  {
    id: 'assure',
    titre: 'Assure',
    description: 'Consulter ses remboursements et interroger l\'assistant sur son contrat.',
  },
  {
    id: 'professionnel_sante',
    titre: 'Professionnel de sante',
    description: 'Deposer factures et ordonnances, suivre l\'etat de ses dossiers.',
  },
  {
    id: 'gestionnaire',
    titre: 'Gestionnaire',
    description: 'Traiter la file d\'alertes, lire le rapport SHAP, valider ou rejeter.',
  },
  {
    id: 'administrateur',
    titre: 'Administrateur',
    description: 'Seuil, canaux, secrets, metriques, sante et retour arriere du modele.',
  },
] as const

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export default function App() {
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', margin: '0 auto', maxWidth: 960, padding: 32 }}>
      <h1>PrediCare TPA</h1>
      <p>
        Detection de fraude medicale, assistant agentique et pilotage decisionnel.
      </p>

      <h2>Quatre roles, une seule application</h2>
      <ul>
        {ROLES.map((role) => (
          <li key={role.id}>
            <strong>{role.titre}</strong> — {role.description}
          </li>
        ))}
      </ul>

      <h2>Sante de la plateforme</h2>
      <p>
        <a href={`${API_BASE}/api/core/health`}>API coeur</a> ·{' '}
        <a href={`${API_BASE}/api/inference/health`}>API inference</a> ·{' '}
        <a href={`${API_BASE}/api/rag/health`}>API RAG</a>
      </p>
    </main>
  )
}