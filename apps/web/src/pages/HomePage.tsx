import { ROLE_LABELS } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { EnTetePage, Tuile } from '../components/blocs'
import { espaceDe } from '../navigation'

export function HomePage() {
  const { profile } = useAuth()
  if (profile === null) return null

  const espace = espaceDe(profile.role)
  const nom = profile.display_name ?? profile.subject

  return (
    <>
      <EnTetePage
        fil={[{ libelle: 'Accueil' }]}
        titre={`Bonjour ${nom}`}
        chapo={`Vous êtes connecté en tant que ${ROLE_LABELS[profile.role].toLowerCase()}. Retrouvez ici les accès de votre espace.`}
      />

      {espace !== null && (
        <div className="tuiles">
          {espace.sections.map((section) => (
            <Tuile
              key={section.chemin}
              icone={section.icone}
              titre={section.libelle}
              texte={section.description}
              chemin={section.chemin}
            />
          ))}
        </div>
      )}
    </>
  )
}
