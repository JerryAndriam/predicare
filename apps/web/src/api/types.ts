// Contrats de l'API, recopies depuis les schemas Pydantic de predicare-core.
// Une divergence entre ce fichier et le back est un bug : il n'y a pas de
// generation automatique dans le projet, donc ces types sont la reference
// cote navigateur.

export type Role = 'assure' | 'professionnel_sante' | 'gestionnaire' | 'administrateur'

export const ROLE_LABELS: Record<Role, string> = {
  assure: 'Assure',
  professionnel_sante: 'Professionnel de santé',
  gestionnaire: 'Gestionnaire',
  administrateur: 'Administrateur',
}

/** Ecran d'accueil de chaque role, apres connexion. */
export const ACCUEIL: Record<Role, string> = {
  assure: '/assure',
  professionnel_sante: '/professionnel',
  gestionnaire: '/gestionnaire',
  administrateur: '/administration',
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  role: Role
  subject: string
}

export interface Profile {
  subject: string
  role: Role
  assured_pseudonym: string | null
  display_name: string | null
  last_login: string | null
}

export interface InvoiceSummary {
  facture_id: string
  assure_pseudonyme: string
  prestataire_id: string
  date_facture: string
  montant_total: number
  montant_eligible: number | null
  montant_pris_en_charge: number | null
  reste_a_charge: number | null
  statut: string
  score_fraude: number | null
  is_fraud: boolean | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type Direction = 'pousse_vers_fraude' | 'pousse_vers_legitime'

export interface ShapContribution {
  feature: string
  value: number
  shap_value: number
  base_value: number | null
  direction: Direction
  human_readable: string
}

export interface Prediction {
  facture_id: string
  score_fraude: number
  is_fraud: boolean
  seuil_applique: number
  model_version: string
  shap: ShapContribution[]
  top_features: string[]
  inference_ms: number
  predicted_at: string
  rapport_shap?: string
  /** Etat de la notification declenchee par le depot (Flux 1). */
  notification?: NotificationStatus
}

export interface AlertSummary {
  prediction_id: string
  facture_id: string
  assure_pseudonyme: string
  score_fraude: number
  montant_total: number
  statut: string
  created_at: string
  /** Age de l'alerte en minutes : indicateur de charge de la file. */
  age_minutes: number
}

/** Une ligne de la facture suspecte, avec l'acte qui la porte. */
export interface AlertLine {
  code_acte: string
  libelle: string
  quantite: number
  montant_unitaire: number
  montant_total: number
  /** L'acte figure dans l'ordonnance liee a la facture. */
  prescrite: boolean
}

export interface AlertDetail extends AlertSummary {
  shap: ShapContribution[]
  lignes: AlertLine[]
}

/** Reponse paginee : `total` vient du serveur, jamais de la page. */
export interface PageResult<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type Decision = 'valider_fraude' | 'rejeter' | 'demander_piece'

export interface DecisionRecord {
  prediction_id: string
  decision: Decision
  commentaire: string | null
  decided_at: string
  score_fraude: number
  decided_by?: string
  facture_id?: string
}

/** Etat de la notification declenchee par le depot d'une facture. */
export interface NotificationStatus {
  envoye: boolean
  message: string
}

export interface ModelInfo {
  active_version: string | null
  candidate_version: string | null
  loaded_at: string | null
  threshold: number
  metrics: Record<string, number>
  available_versions: string[]
}

export interface Health {
  status: 'ok' | 'degraded' | 'down'
  service: string
  version: string
  checks: Record<string, boolean>
  missing_secrets: string[]
}

export interface PlatformHealth {
  service: string
  version: string
  seuil: number
  secrets_manquants: string[]
  timestamp: string
  dependances: {
    base: boolean
    inference: { status: string; version: string | null }
    rag: {
      status: string
      version: string | null
      documents?: number
      embedding_configure?: boolean
      llm_configure?: boolean
    }
  }
}

export interface RagSource {
  contrat: string
  article: string
  garantie: string
  extrait: string
  score: number
  source_fichier: string
}

export interface RagStep {
  outil: string
  args?: Record<string, unknown>
  resultat: string
  duree_ms?: number
}

export interface RagAnswer {
  reponse: string
  sources: RagSource[]
  etapes_agent: RagStep[]
  latence_ms: number
  tokens: number
  cache_semantique: boolean
  limite_atteinte: boolean
  tokens_entree: number
  tokens_sortie: number
  cout_estime_usd: number
  cout_estime_eur: number
  succes: boolean
}

export interface ReferenceAssure {
  pseudonyme: string
}

export interface ReferencePrestataire {
  code: string
  nom: string
  specialite: string
}

export interface ReferenceActe {
  code: string
  libelle: string
  prix_unitaire: number
}

export interface References {
  assures: ReferenceAssure[]
  prestataires: ReferencePrestataire[]
  actes: ReferenceActe[]
  prestataire_du_compte?: string | null
}

export interface NotificationChannel {
  nom: string
  type: 'slack' | 'email'
  actif: boolean
  destinataire: string
  configure: boolean
}

/** Resultat d'un envoi d'essai sur un canal de notification. */
export interface ChannelTestResult {
  nom: string
  type: 'slack' | 'email'
  envoye: boolean
  message: string
  destinataire: string
}

/** Etat d'un secret : configure ou non, et quoi faire sinon. */
export interface SecretState {
  nom: string
  variable: string
  configure: boolean
  effet: string
}

/** Une ligne de facture, avec l'acte qui la porte. */
export interface InvoiceLine {
  code_acte: string
  libelle: string
  quantite: number
  montant_unitaire: number
  montant_total: number
  date_acte: string
}

/** Facture complete : lignes, notation et historique de decision. */
export interface InvoiceDetail extends InvoiceSummary {
  lignes: InvoiceLine[]
  seuil_applique: number | null
  model_version: string | null
  predictions: Record<string, unknown>[]
  decisions: Record<string, unknown>[]
}

export interface Observability {
  timestamp: string
  fenetre?: '24h' | '7j' | '30j' | '90j'
  secrets_manquants: string[]
  base: {
    disponible: boolean
    factures?: number
    predictions?: number
    alertes?: number
    decisions?: number
    journal?: number
  }
  /** Serie quotidienne sur la fenetre choisie : c'est elle qui donne la tendance. */
  serie?: { jour: string; factures: number; alertes: number }[]
  inference: {
    disponible?: boolean
    service?: string
    version?: string | null
    seuil?: number
    latence_ms?: {
      disponible: boolean
      echantillons: number
      moyenne: number | null
      p50: number | null
      p95: number | null
      p99: number | null
    }
    erreurs_total?: number
    requetes_total?: number
    volume?: {
      disponible: boolean
      predictions_total?: number
      alertes_total?: number
      derniere_prediction?: string | null
    }
  }
  derive: Record<string, unknown>
  rag: {
    disponible: boolean
    cache: Record<string, unknown>
    securite: Record<string, unknown>
  }
}

export interface AuditEntry {
  id: number
  acteur: string
  role: string
  action: string
  cible: string | null
  details: Record<string, unknown> | null
  created_at: string
}

export interface AdminUser {
  id: number
  email: string
  role: Role
  display_name: string | null
  is_active: boolean
  assured_pseudonyme: string | null
  prestataire_code: string | null
  last_login: string | null
}

export interface AdminUserCreate {
  email: string
  password: string
  role: Role
  display_name?: string
  assured_pseudonyme?: string
  prestataire_code?: string
}

export interface InvoiceLineInput {
  code_acte: string
  quantite: number
  montant_unitaire: number
  date_acte: string
}

export interface InvoiceInput {
  facture_id?: string
  assure_pseudonyme: string
  prestataire_id: string
  date_facture: string
  montant_total: number
  lignes: InvoiceLineInput[]
}
