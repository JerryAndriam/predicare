import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { api, clearToken, getToken, setToken } from '../api/client'
import type { Profile, Role, TokenResponse } from '../api/types'

interface AuthContextValue {
  profile: Profile | null
  chargement: boolean
  connexion: (email: string, password: string) => Promise<Profile>
  deconnexion: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [chargement, setChargement] = useState(true)

  // Au rechargement de la page, le jeton est encore dans sessionStorage :
  // on redemande le profil au serveur au lieu de faire confiance au jeton
  // seul. Un compte desactive est donc refuse immediatement.
  useEffect(() => {
    if (!getToken()) {
      setChargement(false)
      return
    }
    api<Profile>('/api/core/auth/me')
      .then(setProfile)
      .catch(() => {
        clearToken()
        setProfile(null)
      })
      .finally(() => setChargement(false))
  }, [])

  // Un 401 sur n'importe quel ecran deconnecte proprement : sans cela,
  // l'utilisateur resterait sur une page vide en croyant etre connecte.
  useEffect(() => {
    const surExpiration = () => setProfile(null)
    window.addEventListener('predicare:unauthorized', surExpiration)
    return () => window.removeEventListener('predicare:unauthorized', surExpiration)
  }, [])

  const connexion = useCallback(async (email: string, password: string) => {
    const reponse = await api<TokenResponse>('/api/core/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    setToken(reponse.access_token)
    const profil = await api<Profile>('/api/core/auth/me')
    setProfile(profil)
    return profil
  }, [])

  const deconnexion = useCallback(() => {
    clearToken()
    setProfile(null)
  }, [])

  const valeur = useMemo(
    () => ({ profile, chargement, connexion, deconnexion }),
    [profile, chargement, connexion, deconnexion],
  )

  return <AuthContext.Provider value={valeur}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const contexte = useContext(AuthContext)
  if (contexte === null) {
    throw new Error("useAuth doit etre utilise dans <AuthProvider>.")
  }
  return contexte
}

/** Un administrateur herite de tous les droits, comme cote API. */
export function peut(profile: Profile | null, ...roles: Role[]): boolean {
  if (profile === null) return false
  if (profile.role === 'administrateur') return true
  return roles.includes(profile.role)
}
