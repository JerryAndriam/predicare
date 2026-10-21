// Client HTTP unique. Toutes les requetes passent par ici pour deux raisons :
//  - le jeton est ajoute au meme endroit, donc aucun ecran ne peut l'oublier ;
//  - une seule origine (`/api`), comme en production derriere Traefik.

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

const TOKEN_KEY = 'predicare.token'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export function getToken(): string | null {
  // sessionStorage : le jeton disparait a la fermeture de l'onglet, et n'est
  // jamais partage entre deux onglets (choix du README de l'interface).
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}

/**
 * Executeur commun : jeton, appel reseau, et traitement uniforme de la
 * reponse. `api()` et `apiFormData()` ne different que par les en-tetes
 * qu'ils posent AVANT d'arriver ici.
 */
async function executer<T>(path: string, options: RequestInit): Promise<T> {
  const headers = new Headers(options.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { ...options, headers })
  } catch {
    throw new ApiError(0, 'réseau', 'Serveur injoignable. Verifiez que la plateforme est demarree.')
  }

  if (response.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('predicare:unauthorized'))
  }

  if (!response.ok) {
    let corps: { code?: string; message?: string; details?: unknown } = {}
    try {
      corps = (await response.json()) as typeof corps
    } catch {
      corps = { message: await response.text().catch(() => '') }
    }
    throw new ApiError(
      response.status,
      corps.code ?? 'http_error',
      corps.message ?? `Erreur ${response.status}`,
      corps.details,
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return executer<T>(path, { ...options, headers })
}

/**
 * Envoi multipart.
 *
 * On ne pose JAMAIS `Content-Type` : le navigateur doit le generer lui-meme
 * pour y inclure la frontiere (`boundary`) du `multipart/form-data`. Le
 * forcer a `application/json` rendrait le corps illisible cote serveur.
 */
export async function apiFormData<T>(
  path: string,
  form: FormData,
  method = 'POST',
): Promise<T> {
  return executer<T>(path, { method, body: form })
}

export function messageErreur(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return error.message
    return `${error.message} (${error.status})`
  }
  if (error instanceof Error) return error.message
  return 'Erreur inconnue.'
}
