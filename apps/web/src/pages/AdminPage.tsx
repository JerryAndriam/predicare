import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import {
  ROLE_LABELS,
  type AdminUser,
  type AdminUserCreate,
  type AuditEntry,
  type ChannelTestResult,
  type ModelInfo,
  type NotificationChannel,
  type Observability,
  type PageResult,
  type PlatformHealth,
  type References,
  type Role,
  type SecretState,
  type SecretTestResult,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Barres } from '../components/Barres'
import { SchemaProjet } from '../components/SchemaProjet'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  EtatVide,
  Pagination,
  Succes,
  Vide,
  dateCourte,
  pourcentage,
} from '../components/ui'

/** Taille d'une page de journal : le journal est volumineux. */
const LIMITE_JOURNAL = 50

type Onglet =
  | 'seuil'
  | 'modele'
  | 'sante'
  | 'canaux'
  | 'observabilite'
  | 'audit'
  | 'utilisateurs'
  | 'rgpd'

function tonSante(statut: string): 'ok' | 'alerte' | 'neutre' {
  if (statut === 'ok') return 'ok'
  if (statut === 'degraded') return 'alerte'
  return 'neutre'
}

function nombre(valeur: number | null | undefined): string {
  if (valeur === null || valeur === undefined || Number.isNaN(valeur)) return '-'
  return new Intl.NumberFormat('fr-FR').format(valeur)
}

function valeurLisible(valeur: unknown): string {
  if (Array.isArray(valeur)) return valeur.join(', ')
  if (typeof valeur === 'object' && valeur !== null) return JSON.stringify(valeur)
  return String(valeur)
}

export function AdminPage() {
  const [onglet, setOnglet] = useState<Onglet>('seuil')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const [seuil, setSeuil] = useState('')
  const [motif, setMotif] = useState('')

  const [modele, setModele] = useState<ModelInfo | null>(null)
  const [version, setVersion] = useState('')

  const [sante, setSante] = useState<PlatformHealth | null>(null)
  const [canaux, setCanaux] = useState<NotificationChannel[]>([])
  const [canauxEdition, setCanauxEdition] = useState<
    Record<string, { actif: boolean; destinataire: string }>
  >({})
  const [observabilite, setObservabilite] = useState<Observability | null>(null)
  const [fenetreObservabilite, setFenetreObservabilite] = useState<
    '24h' | '7j' | '30j' | '90j'
  >('30j')
  const [resume, setResume] = useState<{ version: string | null; seuil: number } | null>(null)
  const [journal, setJournal] = useState<AuditEntry[]>([])
  const [totalJournal, setTotalJournal] = useState(0)
  const [offsetJournal, setOffsetJournal] = useState(0)
  const [filtreAction, setFiltreAction] = useState('')
  const [filtreActeur, setFiltreActeur] = useState('')
  const [filtreCible, setFiltreCible] = useState('')
  const [secrets, setSecrets] = useState<SecretState[]>([])
  const [recontrole, setRecontrole] = useState<{ etat: string; resume: Record<string, unknown> } | null>(
    null,
  )
  const [pseudonymeRgpd, setPseudonymeRgpd] = useState('')
  const [messageRgpd, setMessageRgpd] = useState('')
  const [secretEnEdition, setSecretEnEdition] = useState<Record<string, string>>({})
  const [secretTest, setSecretTest] = useState<Record<string, SecretTestResult>>({})
  const [testCanal, setTestCanal] = useState<ChannelTestResult | null>(null)
  const [testEnCours, setTestEnCours] = useState(false)

  const { profile } = useAuth()
  const [utilisateurs, setUtilisateurs] = useState<AdminUser[]>([])
  const [assures, setAssures] = useState<string[]>([])
  const [form, setForm] = useState({
    email: '',
    password: '',
    role: 'assure' as Role,
    display_name: '',
    assured_pseudonyme: '',
    prestataire_code: '',
  })

  async function chargerModele() {
    const etat = await api<ModelInfo>('/api/core/admin/modele')
    setModele(etat)
    if (etat.active_version !== null) setVersion(etat.active_version)
  }

  useEffect(() => {
    // En-tete : la version et le seuil affiches doivent venir du serveur.
    // Les figer en dur (ancien « Version 2 / 28,76 % ») mentait des qu'un
    // administrateur changeait l'un ou l'autre.
    void chargerResume()
  }, [onglet])

  const chargerResume = async () => {
    try {
      const [etat, seuil] = await Promise.all([
        api<ModelInfo>('/api/core/admin/modele'),
        api<{ seuil: number }>('/api/core/admin/seuil'),
      ])
      setResume({ version: etat.active_version, seuil: seuil.seuil })
    } catch {
      setResume(null)
    }
  }

  const chargerObservabilite = async (fenetre: '24h' | '7j' | '30j' | '90j') => {
    try {
      setObservabilite(await api<Observability>(`/api/core/admin/observabilite?fenetre=${fenetre}`))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    }
  }

  const chargerJournal = async (decalage: number) => {    const params = new URLSearchParams({ limit: String(LIMITE_JOURNAL), offset: String(decalage) })
    if (filtreAction.trim() !== '') params.set('action', filtreAction.trim())
    if (filtreActeur.trim() !== '') params.set('acteur', filtreActeur.trim())
    if (filtreCible.trim() !== '') params.set('cible', filtreCible.trim())
    const page = await api<PageResult<AuditEntry>>(`/api/core/audit/journal?${params.toString()}`)
    setJournal(page.items)
    setTotalJournal(page.total)
    setOffsetJournal(page.offset)
  }

  const appliquerFiltresJournal = () => {
    void chargerJournal(0).catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }

  const reinitialiserJournal = () => {
    setFiltreAction('')
    setFiltreActeur('')
    setFiltreCible('')
    const params = new URLSearchParams({ limit: String(LIMITE_JOURNAL), offset: '0' })
    void api<PageResult<AuditEntry>>(`/api/core/audit/journal?${params.toString()}`)
      .then((page) => {
        setJournal(page.items)
        setTotalJournal(page.total)
        setOffsetJournal(page.offset)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }

  /**
   * Export CSV du journal affiché.
   *
   * L'export porte sur ce que l'écran montre (page courante, filtres
   * appliqués) : un export de TOUT le journal alors que l'écran n'en montre
   * qu'une page serait une surprise pour le lecteur.
   */
  const exporterJournal = () => {
    const entetes = ['id', 'created_at', 'acteur', 'rôle', 'action', 'cible', 'details']
    const lignes = journal.map((entree) =>
      [
        entree.id,
        entree.created_at,
        entree.acteur,
        entree.role,
        entree.action,
        entree.cible ?? '',
        JSON.stringify(entree.details ?? {}),
      ]
        .map((valeur) => `"${String(valeur).replace(/"/g, '""')}"`)
        .join(';'),
    )
    const contenu = [entetes.join(';'), ...lignes].join('\r\n')
    const blob = new Blob([`﻿${contenu}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `journal-audit-${new Date().toISOString().slice(0, 10)}.csv`
    lien.click()
    URL.revokeObjectURL(url)
  }

  const testerUnCanal = async (nom: string) => {
    setTestEnCours(true)
    setTestCanal(null)
    setErreur(null)
    try {
      setTestCanal(await api<ChannelTestResult>(`/api/core/admin/canaux/${encodeURIComponent(nom)}/test`, {
        method: 'POST',
      }))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setTestEnCours(false)
    }
  }

  useEffect(() => {
    setErreur(null)
    const charger = async () => {
      try {
        if (onglet === 'seuil') {
          const reponse = await api<{ seuil: number }>('/api/core/admin/seuil')
          setSeuil(String(reponse.seuil))
        }
        if (onglet === 'modele') await chargerModele()
        if (onglet === 'sante') {
          setSante(await api<PlatformHealth>('/api/core/admin/sante'))
        }
        if (onglet === 'canaux') {
          const valeurs = await api<NotificationChannel[]>('/api/core/admin/canaux')
          setCanaux(valeurs)
          setCanauxEdition(
            Object.fromEntries(
              valeurs.map((canal) => [
                canal.nom,
                { actif: canal.actif, destinataire: canal.destinataire },
              ]),
            ),
          )
          setSecrets(await api<SecretState[]>('/api/core/admin/secrets'))
        }
        if (onglet === 'observabilite') {
          setObservabilite(
            await api<Observability>(`/api/core/admin/observabilite?fenetre=${fenetreObservabilite}`),
          )
        }
        if (onglet === 'audit') {
          await chargerJournal(0)
        }
        if (onglet === 'utilisateurs') {
          const [comptes, references] = await Promise.all([
            api<AdminUser[]>('/api/core/admin/utilisateurs'),
            api<References>('/api/core/factures/references'),
          ])
          setUtilisateurs(comptes)
          const pseudonymes = references.assures.map((valeur) => valeur.pseudonyme)
          setAssures(pseudonymes)
          setForm((precedent) => ({
            ...precedent,
            assured_pseudonyme: precedent.assured_pseudonyme || pseudonymes[0] || '',
          }))
        }
      } catch (probleme) {
        setErreur(messageErreur(probleme))
      }
    }
    void charger()
  }, [onglet])

  const enregistrerSeuil = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<{ status: string }>('/api/core/admin/seuil', {
        method: 'PUT',
        body: JSON.stringify({ seuil: Number(seuil), motif }),
      })
      setSucces('Seuil enregistré et pousse au service d inference.')
      setMotif('')
      // L'en-tete affiche le seuil courant : il doit changer AU MOMENT du
      // reglage, pas au prochain rechargement de la page.
      await chargerResume()
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const enregistrerCanal = async (nom: string) => {
    const reglage = canauxEdition[nom]
    if (reglage === undefined) return
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<NotificationChannel>(`/api/core/admin/canaux/${encodeURIComponent(nom)}`, {
        method: 'PUT',
        body: JSON.stringify(reglage),
      })
      setSucces(`Canal ${nom} enregistre.`)
      setCanaux(await api<NotificationChannel[]>('/api/core/admin/canaux'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const agirModele = async (chemin: string) => {
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<Record<string, unknown>>(chemin, { method: 'POST' })
      setSucces('Opération appliquée sur le registre de modèles.')
      await chargerModele()
      // Idem pour l'en-tete : la version affichee doit suivre la bascule.
      await chargerResume()
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const creerCompte = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      const charge: AdminUserCreate = {
        email: form.email.trim(),
        password: form.password,
        role: form.role,
        display_name: form.display_name.trim() || undefined,
        assured_pseudonyme:
          form.role === 'assure' ? form.assured_pseudonyme : undefined,
        prestataire_code:
          form.role === 'professionnel_sante' ? form.prestataire_code.trim() : undefined,
      }
      await api<AdminUser>('/api/core/admin/utilisateurs', {
        method: 'POST',
        body: JSON.stringify(charge),
      })
      setSucces('Compte créé.')
      setForm({
        email: '',
        password: '',
        role: 'assure',
        display_name: '',
        assured_pseudonyme: assures[0] ?? '',
        prestataire_code: '',
      })
      setUtilisateurs(await api<AdminUser[]>('/api/core/admin/utilisateurs'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const changerStatut = async (compte: AdminUser) => {
    if (compte.is_active && !window.confirm(`Desactiver le compte ${compte.email} ?`)) {
      return
    }
    setErreur(null)
    setSucces(null)
    setEnCours(true)
    try {
      await api<AdminUser>(`/api/core/admin/utilisateurs/${compte.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !compte.is_active }),
      })
      setSucces(compte.is_active ? 'Compte désactivé.' : 'Compte active.')
      setUtilisateurs(await api<AdminUser[]>('/api/core/admin/utilisateurs'))
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnCours(false)
    }
  }

  const requeteRgpd = async (chemin: string, options: { methode: string; corps?: unknown } = { methode: 'GET' }) => {
    const reponse = await api<unknown>(`/api/core/rgpd${chemin}`, {
      method: options.methode,
      body: options.corps ? JSON.stringify(options.corps) : undefined,
    })
    setMessageRgpd('Operation effectuee.')
    return reponse
  }

  const exporterDossier = async () => {
    if (!pseudonymeRgpd) return
    const dossier = await api<Record<string, unknown>>(
      `/api/core/rgpd/assures/${encodeURIComponent(pseudonymeRgpd)}/export`,
    )
    // Le dossier est telecharge en JSON : c'est le format que la personne
    // peut relire, et le seul que l'API maintient.
    const blob = new Blob([JSON.stringify(dossier, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `dossier-${pseudonymeRgpd}.json`
    lien.click()
    URL.revokeObjectURL(url)
    setMessageRgpd('Export telecharge.')
  }

  const effacerDossier = async () => {
    if (!pseudonymeRgpd) return
    if (
      !window.confirm(
        `Effacer definitivement le dossier ${pseudonymeRgpd} ? Cette operation est irreversible.`,
      )
    ) {
      return
    }
    await requeteRgpd(`/assures/${encodeURIComponent(pseudonymeRgpd)}`, { methode: 'DELETE' })
  }

  const lancerRecontrole = async (portee: 'historique' | 'nouvelles') => {
    setRecontrole({ etat: 'en_cours', resume: {} })
    await api('/api/core/admin/modele/recontroler', {
      method: 'POST',
      body: JSON.stringify({ portee }),
    })
    const timer = setInterval(async () => {
      const etat = await api<{ etat: string; resume: Record<string, unknown> }>(
        '/api/core/admin/modele/recontroler/etat',
      )
      setRecontrole(etat)
      if (etat.etat !== 'en_cours') clearInterval(timer)
    }, 3000)
  }

  const enregistrerSecret = async (nom: string, valeur: string) => {
    await api<SecretState>(`/api/core/admin/secrets/${encodeURIComponent(nom)}`, {
      method: 'PUT',
      body: JSON.stringify({ valeur }),
    })
    setSecrets(await api<SecretState[]>('/api/core/admin/secrets'))
    setSecretEnEdition({ ...secretEnEdition, [nom]: '' })
  }

  const testerSecret = async (nom: string) => {
    const resultat = await api<SecretTestResult>(
      `/api/core/admin/secrets/${encodeURIComponent(nom)}/test`,
      { method: 'POST' },
    )
    setSecretTest({ ...secretTest, [nom]: resultat })
  }

  return (
    <div className="pile">
      <div className="titre-page" style={{
        background: 'linear-gradient(160deg, #0e1a27 0%, #0f766e 70%, #0b5c56 100%)',
        color: '#fff',
        padding: '1.8rem 1.5rem 1.4rem',
        borderRadius: 'var(--rayon)',
        boxShadow: 'var(--ombre-levite)',
        marginBottom: '1.2rem',
        position: 'relative',
        overflow: 'hidden'
      }}>
        <h1 style={{ fontSize: '1.8rem', letterSpacing: '-0.03em', marginBottom: '0.2rem', color: '#fff' }}>Administration</h1>
        <p style={{ opacity: 0.9, maxWidth: '60ch', color: '#e8f0f6', marginBottom: '0.6rem' }}>
          Seuil, versions du modele, sante, comptes et journal. Aucun reglage ne
          demande de redemarrer un conteneur.
        </p>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.82rem', opacity: 0.8 }}>
          <span>Rôle : <strong style={{ color: '#2dd4bf' }}>Administrateur</strong></span>
          <span>Version : <strong style={{ color: '#2dd4bf' }}>{resume?.version ?? '-'}</strong></span>
          <span>
            Seuil :{' '}
            <strong style={{ color: '#2dd4bf' }}>
              {resume === null ? '-' : pourcentage(resume.seuil)}
            </strong>
          </span>
        </div>
        <SchemaProjet />
      </div>

      <div className="onglets" role="tablist">
        {(
          [
            ['seuil', 'Seuil'],
            ['modele', 'Modèle'],
            ['sante', 'Santé'],
            ['canaux', 'Canaux'],
            ['observabilite', 'Observabilite'],
            ['utilisateurs', 'Comptes'],
            ['audit', 'Journal'],
            ['rgpd', 'Droits des personnes'],
          ] as const
        ).map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            role="tab"
            aria-selected={onglet === cle}
            className={onglet === cle ? 'onglet actif' : 'onglet'}
            onClick={() => setOnglet(cle)}
          >
            {libelle}
          </button>
        ))}
      </div>

      <Erreur message={erreur} />
      <Succes message={succes} />

      {onglet === 'seuil' && (
        <Carte titre="Seuil de declenchement des alertes">
          <p className="aide">
            Une facture dont le score depasse ce seuil entre dans la file du gestionnaire.
            Un seuil plus bas augmente le rappel et le nombre de fausses alertes.
          </p>
          <form className="formulaire" onSubmit={enregistrerSeuil}>
            <div className="grille deux">
              <Champ label="Seuil (0 a 1)">
                <input
                  type="number"
                  min={0}
                  max={1}
                  step="0.001"
                  value={seuil}
                  onChange={(event) => setSeuil(event.target.value)}
                  required
                />
              </Champ>
              <Champ label="Motif du changement" aide="Trace dans le journal d audit.">
                <input
                  type="text"
                  minLength={3}
                  maxLength={500}
                  value={motif}
                  onChange={(event) => setMotif(event.target.value)}
                  placeholder="Exemple : arbitrage rappel / charge de travail"
                  required
                />
              </Champ>
            </div>
            <button type="submit" className="bouton principal" disabled={enCours}>
              {enCours ? 'Application...' : 'Appliquer le seuil'}
            </button>
          </form>
        </Carte>
      )}

      {onglet === 'modele' && (
        <div className="grille deux">
          <Carte titre="Registre des modèles">
            {modele === null ? (
              <Chargement />
            ) : (
              <div className="pile-serre">
                <div className="resultat-meta">
                  <Badge ton={modele.active_version === null ? 'alerte' : 'ok'}>
                    Active : {modele.active_version ?? 'aucune'}
                  </Badge>
                  <Badge ton="info">
                    Candidate : {modele.candidate_version ?? 'aucune'}
                  </Badge>
                  <span>Seuil : {pourcentage(modele.threshold)}</span>
                  <span>Charge : {dateCourte(modele.loaded_at)}</span>
                </div>

                <h3>Metriques de la version active</h3>
                {Object.keys(modele.metrics).length === 0 ? (
                  <Vide>Aucune metrique exposee.</Vide>
                ) : (
                  <ul className="liste-simple">
                    {Object.entries(modele.metrics).map(([cle, valeur]) => (
                      <li key={cle}>
                        <span className="mono">{cle}</span> : {String(valeur)}
                      </li>
                    ))}
                  </ul>
                )}

                <h3>Versions présentes sur le volume</h3>
                {modele.available_versions.length === 0 ? (
                  <Vide>
                    Aucune version sur /models. Lancez <code>make train VERSION=2</code>.
                  </Vide>
                ) : (
                  <p className="mono">{modele.available_versions.join(', ')}</p>
                )}
              </div>
            )}
          </Carte>

          <Carte titre="Re-contrôler un stock de factures">
            <p className="aide">
              Le contrôle automatisé du CDC : re-noter toutes les factures déjà
              présentes. L’historique compte 84 592 factures, le passage dure
              environ deux minutes — il part dans un sous-processus et le service
              reste disponible. Les notes de l’historique ne nourrissent pas la
              file du gestionnaire.
            </p>
            <div className="boutons-ligne">
              <button
                type="button"
                className="bouton"
                disabled={recontrole?.etat === 'en_cours'}
                onClick={() => lancerRecontrole('historique')}
              >
                {recontrole?.etat === 'en_cours' ? 'Re-contrôle en cours…' : 'Re-contrôler l’historique'}
              </button>
              <button
                type="button"
                className="bouton discret"
                disabled={recontrole?.etat === 'en_cours'}
                onClick={() => lancerRecontrole('nouvelles')}
              >
                Re-contrôler les nouvelles
              </button>
            </div>
            {recontrole && recontrole.etat !== 'en_cours' && recontrole.resume && Object.keys(recontrole.resume).length > 0 ? (
              <ul className="liste-simple">
                {Object.entries(recontrole.resume).map(([cle, valeur]) => (
                  <li key={cle}>
                    <span className="mono">{cle}</span> : {String(valeur)}
                  </li>
                ))}
              </ul>
            ) : null}
          </Carte>

          <Carte titre="Deploiement sans interruption">
            <div className="formulaire">
              <Champ label="Version" aide="Un numero present sur le volume /models.">
                <input
                  type="text"
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                  placeholder="2"
                />
              </Champ>
              <div className="boutons-ligne">
                <button
                  type="button"
                  className="bouton"
                  disabled={enCours || version === ''}
                  onClick={() =>
                    void agirModele(
                      `/api/core/admin/modele/candidat?version=${encodeURIComponent(version)}`,
                    )
                  }
                >
                  Charger la candidate
                </button>
                <button
                  type="button"
                  className="bouton principal"
                  disabled={enCours}
                  onClick={() => void agirModele('/api/core/admin/modele/bascule')}
                >
                  Basculer sur la candidate
                </button>
                <button
                  type="button"
                  className="bouton danger"
                  disabled={enCours || version === ''}
                  onClick={() =>
                    void agirModele(
                      `/api/core/admin/modele/retour-arriere?version=${encodeURIComponent(version)}`,
                    )
                  }
                >
                  Revenir a cette version
                </button>
              </div>
              <p className="aide">
                Charger ne bascule pas : le modele en service continue de repondre pendant
                le chargement. C est la condition d un deploiement sans coupure.
              </p>
            </div>
          </Carte>
        </div>
      )}

      {onglet === 'sante' && (
        <Carte titre="Santé de la plateforme">
          {sante === null ? (
            <Chargement />
          ) : (
            <div className="pile-serre">
              <div className="grille trois">
                <div className="sonde">
                  <span className="champ-label">Base de données</span>
                  <Badge ton={sante.dependances.base ? 'ok' : 'alerte'}>
                    {sante.dependances.base ? 'ok' : 'indisponible'}
                  </Badge>
                </div>
                <div className="sonde">
                  <span className="champ-label">Service d inference</span>
                  <Badge ton={tonSante(sante.dependances.inference.status)}>
                    {sante.dependances.inference.status}
                  </Badge>
                  <span className="mono">{sante.dependances.inference.version ?? '-'}</span>
                </div>
                <div className="sonde">
                  <span className="champ-label">Assistant RAG</span>
                  <Badge ton={tonSante(sante.dependances.rag.status)}>
                    {sante.dependances.rag.status}
                  </Badge>
                  <span className="mono">{sante.dependances.rag.version ?? '-'}</span>
                  <span className="mono">
                    {sante.dependances.rag.documents ?? 0} document(s) indexe(s)
                  </span>
                  <Badge
                    ton={sante.dependances.rag.embedding_configure ? 'ok' : 'alerte'}
                  >
                    {sante.dependances.rag.embedding_configure
                      ? 'embeddings configures'
                      : 'clé d embedding absente'}
                  </Badge>
                </div>
              </div>

              <p className="aide">
                api-core {sante.version} - seuil {pourcentage(sante.seuil)} - sonde du{' '}
                {dateCourte(sante.timestamp)}
              </p>

              <h3>Secrets manquants</h3>
              {sante.secrets_manquants.length === 0 ? (
                <p>Configuration complete.</p>
              ) : (
                <ul className="liste-simple">
                  {sante.secrets_manquants.map((secret) => (
                    <li key={secret} className="mono">
                      {secret}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Carte>
      )}

      {onglet === 'canaux' && (
        <Carte titre="Canaux de notification">
          <p className="aide">
            Ces reglages sont enregistres en base et s appliquent sans redemarrage.
            Un canal sans destinataire reste « non configure » : le badge Actif ne
            garantit pas qu une alerte parte.
          </p>
          {canaux.length === 0 ? (
            <Chargement />
          ) : (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Nom</th>
                    <th>Type</th>
                    <th>Configure</th>
                    <th>Actif</th>
                    <th>Destinataire</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {canaux.map((canal) => {
                    const reglage = canauxEdition[canal.nom] ?? {
                      actif: canal.actif,
                      destinataire: canal.destinataire,
                    }
                    return (
                      <tr key={canal.nom}>
                        <td>{canal.nom}</td>
                        <td>{canal.type}</td>
                        <td>
                          <Badge ton={canal.configure ? 'ok' : 'alerte'}>
                            {canal.configure ? 'configure' : 'non configure'}
                          </Badge>
                        </td>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Activer ${canal.nom}`}
                            checked={reglage.actif}
                            onChange={(event) =>
                              setCanauxEdition((precedent) => ({
                                ...precedent,
                                [canal.nom]: {
                                  ...reglage,
                                  actif: event.target.checked,
                                },
                              }))
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className="mono"
                            aria-label={`Destinataire ${canal.nom}`}
                            value={reglage.destinataire}
                            onChange={(event) =>
                              setCanauxEdition((precedent) => ({
                                ...precedent,
                                [canal.nom]: {
                                  ...reglage,
                                  destinataire: event.target.value,
                                },
                              }))
                            }
                          />
                        </td>
                        <td className="droite">
                          <div className="carte-actions">
                            <button
                              type="button"
                              className="bouton discret"
                              disabled={testEnCours}
                              onClick={() => void testerUnCanal(canal.nom)}
                            >
                              {testEnCours ? 'Envoi…' : 'Tester'}
                            </button>
                            <button
                              type="button"
                              className="bouton principal"
                              disabled={enCours}
                              onClick={() => void enregistrerCanal(canal.nom)}
                            >
                              Enregistrer
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {testCanal !== null && (
            <p className={testCanal.envoye ? 'succes' : 'erreur'} role="status">
              {testCanal.envoye ? '✓ ' : '✕ '}
              {testCanal.message}
            </p>
          )}

          <h3>Secrets</h3>
          <p className="aide">
            Un secret s’écrit ici, ou dans l’environnement du conteneur. La base passe
            avant l’environnement : corriger un canal ne demande donc ni déploiement ni
            édition de fichier. La valeur est chiffrée en base, et l’écriture est
            journalisée. Les services la relisent au démarrage : après un changement,
            redémarrez la plateforme pour qu’ils la prennent en compte.
          </p>
          {secrets.length === 0 ? (
            <Chargement />
          ) : (
            <div className="table-enveloppe">
              <table className="table table-dense">
                <caption className="visuellement-cache">
                  Secrets nécessaires à la plateforme
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Secret</th>
                    <th scope="col">Variable</th>
                    <th scope="col">État</th>
                    <th scope="col">Conséquence si absente</th>
                    <th scope="col">Valeur</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {secrets.map((secret) => (
                    <tr key={secret.variable}>
                      <td>{secret.nom}</td>
                      <td className="mono">{secret.variable}</td>
                      <td>
                        <Badge ton={secret.configure ? 'ok' : 'alerte'}>
                          {secret.configure ? 'configuré' : 'manquant'}
                        </Badge>
                        <span className="aide"> {secret.source}</span>
                        {secret.apercu ? <span className="mono"> {secret.apercu}</span> : null}
                      </td>
                      <td className="aide">{secret.effet}</td>
                      <td>
                        <input
                          type="password"
                          aria-label={`Valeur du secret ${secret.nom}`}
                          placeholder={secret.configure ? secret.apercu : 'à renseigner'}
                          value={secretEnEdition[secret.nom] ?? ''}
                          onChange={(event) =>
                            setSecretEnEdition({ ...secretEnEdition, [secret.nom]: event.target.value })
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="bouton discret"
                          disabled={!secretEnEdition[secret.nom]}
                          onClick={() => enregistrerSecret(secret.nom, secretEnEdition[secret.nom])}
                        >
                          Enregistrer
                        </button>{' '}
                        <button
                          type="button"
                          className="bouton discret"
                          onClick={() => testerSecret(secret.nom)}
                        >
                          Tester
                        </button>
                        {secretTest[secret.nom] ? (
                          <p className={secretTest[secret.nom].ok ? 'aide' : 'erreur'}>
                            {secretTest[secret.nom].ok ? '✓ ' : '✕ '}
                            {secretTest[secret.nom].message}
                          </p>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Carte>
      )}

      {onglet === 'observabilite' && (
        observabilite === null ? (
          <Carte titre="Observabilité">
            <Chargement />
          </Carte>
        ) : (
          <div className="pile">
            <Carte
              titre="Synthèse d’exploitation"
              actions={
                <div className="carte-actions">
                  <label className="champ-label" htmlFor="fenetre-observabilite">
                    Période
                  </label>
                  <select
                    id="fenetre-observabilite"
                    value={fenetreObservabilite}
                    onChange={(event) => {
                      setFenetreObservabilite(event.target.value as typeof fenetreObservabilite)
                      chargerObservabilite(event.target.value as typeof fenetreObservabilite)
                    }}
                  >
                    <option value="24h">24 heures</option>
                    <option value="7j">7 jours</option>
                    <option value="30j">30 jours</option>
                    <option value="90j">90 jours</option>
                  </select>
                </div>
              }
            >
              <div className="resultat-meta">
                <Badge ton={observabilite.base.disponible ? 'ok' : 'alerte'}>
                  Base {observabilite.base.disponible ? 'ok' : 'indisponible'}
                </Badge>
                <Badge ton={observabilite.inference.disponible === false ? 'alerte' : 'ok'}>
                  Inference {observabilite.inference.disponible === false ? 'indisponible' : 'ok'}
                </Badge>
                <Badge ton={observabilite.rag.disponible ? 'ok' : 'alerte'}>
                  RAG {observabilite.rag.disponible ? 'ok' : 'indisponible'}
                </Badge>
                <span className="aide">
                  Sonde du {dateCourte(observabilite.timestamp)} - version{' '}
                  {observabilite.inference.version ?? '-'}
                </span>
              </div>
              {observabilite.secrets_manquants.length > 0 && (
                <p className="aide">
                  Secrets a configurer :{' '}
                  <span className="mono">{observabilite.secrets_manquants.join(', ')}</span>
                </p>
              )}
            </Carte>

            <Carte
              titre={`Volume traité par jour (${fenetreObservabilite})`}
              actions={
                <span className="aide">
                  {nombre(observabilite.serie?.reduce((somme, point) => somme + point.factures, 0) ?? 0)}{' '}
                  facture(s) sur la période
                </span>
              }
            >
              <Barres
                libelle="Factures déposées par jour"
                points={(observabilite.serie ?? []).map((point) => ({
                  etiquette: point.jour.slice(5),
                  valeur: point.factures,
                  valeurSecondaire: point.alertes,
                }))}
                format={(valeur) => nombre(valeur)}
              />
              <p className="aide">
                Barres pleines : factures déposées. Part rouge : factures ayant déclenché une
                alerte.
              </p>
            </Carte>

            <div className="grille trois grille-kpi">
              <Carte titre="Volume">
                <div className="kpi">
                  <span className="kpi-valeur">{nombre(observabilite.base.factures)}</span>
                  <span className="kpi-libelle">Factures en base</span>
                </div>
                <div className="kpi">
                  <span className="kpi-valeur">{nombre(observabilite.base.alertes)}</span>
                  <span className="kpi-libelle">Alertes fraude</span>
                </div>
              </Carte>
              <Carte titre="Activite">
                <div className="kpi">
                  <span className="kpi-valeur">{nombre(observabilite.base.predictions)}</span>
                  <span className="kpi-libelle">Predictions</span>
                </div>
                <div className="kpi">
                  <span className="kpi-valeur">{nombre(observabilite.base.decisions)}</span>
                  <span className="kpi-libelle">Decisions gestionnaire</span>
                </div>
              </Carte>
              <Carte titre="Erreurs">
                <div className="kpi">
                  <span className="kpi-valeur">
                    {nombre(observabilite.inference.erreurs_total)}
                  </span>
                  <span className="kpi-libelle">Erreurs applicatives</span>
                </div>
                <p className="aide">
                  {nombre(observabilite.inference.requetes_total)} requete(s) mesuree(s)
                  {observabilite.inference.requetes_total
                    ? ` - taux ${pourcentage(
                        (observabilite.inference.erreurs_total ?? 0) /
                          observabilite.inference.requetes_total,
                      )}`
                    : ''}
                </p>
              </Carte>
            </div>

            <div className="grille deux-large">
              <Carte titre="Latence de l'inference">
                {observabilite.inference.latence_ms?.disponible ? (
                  <div className="grille trois grille-kpi">
                    <div className="kpi">
                      <span className="kpi-valeur">
                        {observabilite.inference.latence_ms.p50?.toFixed(2)} ms
                      </span>
                      <span className="kpi-libelle">P50</span>
                    </div>
                    <div className="kpi">
                      <span className="kpi-valeur">
                        {observabilite.inference.latence_ms.p95?.toFixed(2)} ms
                      </span>
                      <span className="kpi-libelle">P95</span>
                    </div>
                    <div className="kpi">
                      <span className="kpi-valeur">
                        {observabilite.inference.latence_ms.p99?.toFixed(2)} ms
                      </span>
                      <span className="kpi-libelle">P99</span>
                    </div>
                  </div>
                ) : (
                  <Vide>Aucune inference mesurée depuis le demarrage du service.</Vide>
                )}
                <p className="aide">
                  {observabilite.inference.latence_ms?.echantillons ?? 0} echantillon(s) dans
                  la fenetre glissante.
                </p>
              </Carte>

              <Carte titre="Dérive du modèle">
                {Object.keys(observabilite.derive).length === 0 ? (
                  <Vide>Aucun rapport de dérive disponible.</Vide>
                ) : (
                  <ul className="liste-simple">
                    {Object.entries(observabilite.derive).map(([cle, valeur]) => (
                      <li key={cle}>
                        <span className="mono">{cle}</span> : {valeurLisible(valeur)}
                      </li>
                    ))}
                  </ul>
                )}
              </Carte>
            </div>

            <div className="grille deux-large">
              <Carte titre="Cache semantique">
                {Object.keys(observabilite.rag.cache).length === 0 ? (
                  <Vide>Aucune statistique exposee par l'assistant.</Vide>
                ) : (
                  <ul className="liste-simple">
                    {Object.entries(observabilite.rag.cache).map(([cle, valeur]) => (
                      <li key={cle}>
                        <span className="mono">{cle}</span> : {valeurLisible(valeur)}
                      </li>
                    ))}
                  </ul>
                )}
              </Carte>

              <Carte titre="Posture de sécurité de l'assistant">
                {Object.keys(observabilite.rag.securite).length === 0 ? (
                  <Vide>Aucune posture de sécurité exposee.</Vide>
                ) : (
                  <ul className="liste-simple">
                    {Object.entries(observabilite.rag.securite).map(([cle, valeur]) => (
                      <li key={cle}>
                        <span className="mono">{cle}</span> : {valeurLisible(valeur)}
                      </li>
                    ))}
                  </ul>
                )}
              </Carte>
            </div>
          </div>
        )
      )}

      {onglet === 'rgpd' && (
        <div className="grille deux">
          <Carte titre="Droits des personnes">
            <p className="aide">
              L&apos;export, la rectification, l&apos;opposition et l&apos;effacement
              d&apos;un dossier. L&apos;export rend l&apos;identité en clair : c&apos;est le droit
              d&apos;accès de la personne. L&apos;effacement supprime les données métier et
              anonymise le journal — la trace reste, la personne part.
            </p>
            <div className="formulaire">
              <Champ label="Pseudonyme du dossier" aide="Le pseudonyme affiché dans l'historique de l'assuré.">
                <input
                  type="text"
                  value={pseudonymeRgpd}
                  onChange={(event) => setPseudonymeRgpd(event.target.value)}
                  placeholder="assr_..."
                />
              </Champ>
              <div className="boutons-ligne">
                <button
                  type="button"
                  className="bouton"
                  disabled={!pseudonymeRgpd}
                  onClick={exporterDossier}
                >
                  Exporter
                </button>
                <button
                  type="button"
                  className="bouton discret"
                  disabled={!pseudonymeRgpd}
                  onClick={() =>
                    requeteRgpd(`/assures/${encodeURIComponent(pseudonymeRgpd)}/identite`, {
                      methode: 'PUT',
                      corps: { nom: `Rectifie ${new Date().toISOString().slice(0, 10)}` },
                    })
                  }
                >
                  Rectifier
                </button>
                <button
                  type="button"
                  className="bouton discret"
                  disabled={!pseudonymeRgpd}
                  onClick={() =>
                    requeteRgpd(`/assures/${encodeURIComponent(pseudonymeRgpd)}/opposition`, {
                      methode: 'POST',
                    })
                  }
                >
                  Opposer
                </button>
                <button
                  type="button"
                  className="bouton discret"
                  disabled={!pseudonymeRgpd}
                  onClick={effacerDossier}
                >
                  Effacer
                </button>
              </div>
              {messageRgpd ? <p className="aide">{messageRgpd}</p> : null}
            </div>
          </Carte>
        </div>
      )}

      {onglet === 'utilisateurs' && (
        <div className="grille deux-large">
          <Carte titre={`Comptes (${utilisateurs.length})`}>
            {utilisateurs.length === 0 ? (
              <Vide>Aucun compte. Creez le premier a droite.</Vide>
            ) : (
              <div className="table-enveloppe">
                <table className="table">
                  <thead>
                    <tr>
                      <th>E-mail</th>
                      <th>Rôle</th>
                      <th>Nom</th>
                      <th>Dossier</th>
                      <th>Prestataire</th>
                      <th>État</th>
                      <th>Dernière connexion</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {utilisateurs.map((compte) => {
                      const estMoi =
                        profile !== null && String(compte.id) === profile.subject
                      return (
                        <tr key={compte.id}>
                          <td className="mono">{compte.email}</td>
                          <td>{ROLE_LABELS[compte.role]}</td>
                          <td>{compte.display_name ?? '-'}</td>
                          <td className="mono">{compte.assured_pseudonyme ?? '-'}</td>
                          <td className="mono">{compte.prestataire_code ?? '-'}</td>
                          <td>
                            <Badge ton={compte.is_active ? 'ok' : 'neutre'}>
                              {compte.is_active ? 'actif' : 'désactivé'}
                            </Badge>
                          </td>
                          <td>{dateCourte(compte.last_login)}</td>
                          <td className="droite">
                            <button
                              type="button"
                              className={compte.is_active ? 'bouton danger' : 'bouton'}
                              disabled={enCours || (estMoi && compte.is_active)}
                              title={
                                estMoi && compte.is_active
                                  ? 'Vous ne pouvez pas desactiver votre propre compte.'
                                  : undefined
                              }
                              onClick={() => void changerStatut(compte)}
                            >
                              {compte.is_active ? 'Desactiver' : 'Activer'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="aide">
              La desactivation bloque la prochaine connexion. Un jeton deja emis reste
              valide jusqu a son expiration.
            </p>
          </Carte>

          <Carte titre="Nouveau compte">
            <form className="formulaire" onSubmit={creerCompte}>
              <Champ label="Adresse e-mail">
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={(event) =>
                    setForm((precedent) => ({ ...precedent, email: event.target.value }))
                  }
                  placeholder="prenom@predicare.local"
                />
              </Champ>

              <Champ
                label="Mot de passe"
                aide="Au moins 12 caracteres. Il est hache (Argon2id) avant l enregistrement."
              >
                <input
                  type="password"
                  required
                  minLength={12}
                  maxLength={256}
                  value={form.password}
                  onChange={(event) =>
                    setForm((precedent) => ({ ...precedent, password: event.target.value }))
                  }
                />
              </Champ>

              <Champ label="Rôle">
                <select
                  value={form.role}
                  onChange={(event) =>
                    setForm((precedent) => ({
                      ...precedent,
                      role: event.target.value as Role,
                    }))
                  }
                >
                  {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
                    <option key={role} value={role}>
                      {ROLE_LABELS[role]}
                    </option>
                  ))}
                </select>
              </Champ>

              <Champ label="Nom affiche">
                <input
                  type="text"
                  maxLength={128}
                  value={form.display_name}
                  onChange={(event) =>
                    setForm((precedent) => ({
                      ...precedent,
                      display_name: event.target.value,
                    }))
                  }
                  placeholder="Optionnel"
                />
              </Champ>

              {form.role === 'assure' && (
                <Champ
                  label="Dossier assure"
                  aide="Un compte assure doit pointer vers un dossier existant."
                >
                  {assures.length === 0 ? (
                    <p className="aide">
                      Aucun dossier disponible : lancez d abord le seed des donnees.
                    </p>
                  ) : (
                    <select
                      required
                      value={form.assured_pseudonyme}
                      onChange={(event) =>
                        setForm((precedent) => ({
                          ...precedent,
                          assured_pseudonyme: event.target.value,
                        }))
                      }
                    >
                      {assures.map((pseudonyme) => (
                        <option key={pseudonyme} value={pseudonyme}>
                          {pseudonyme}
                        </option>
                      ))}
                    </select>
                  )}
                </Champ>
              )}

              {form.role === 'professionnel_sante' && (
                <Champ
                  label="Prestataire"
                  aide="Code du prestataire dont ce compte depend (ex. PRE-00001). Il determine les factures visibles."
                >
                  <input
                    type="text"
                    required
                    maxLength={64}
                    value={form.prestataire_code}
                    onChange={(event) =>
                      setForm((precedent) => ({
                        ...precedent,
                        prestataire_code: event.target.value,
                      }))
                    }
                    placeholder="PRE-00001"
                  />
                </Champ>
              )}

              <button type="submit" className="bouton principal" disabled={enCours}>
                {enCours ? 'Creation...' : 'Creer le compte'}
              </button>
            </form>
          </Carte>
        </div>
      )}

      {onglet === 'audit' && (
        <Carte
          titre={`Journal d’audit (${totalJournal} entrées)`}
          actions={
            <div className="carte-actions">
              <button type="button" className="bouton discret" onClick={exporterJournal}>
                Exporter en CSV
              </button>
            </div>
          }
        >
          <div className="grille quatre">
            <Champ label="Action">
              <input
                value={filtreAction}
                placeholder="decision_alerte, connexion…"
                onChange={(event) => setFiltreAction(event.target.value)}
              />
            </Champ>
            <Champ label="Acteur">
              <input
                value={filtreActeur}
                placeholder="identifiant de l’acteur"
                onChange={(event) => setFiltreActeur(event.target.value)}
              />
            </Champ>
            <Champ label="Cible">
              <input
                value={filtreCible}
                placeholder="prediction:12, compte:3…"
                onChange={(event) => setFiltreCible(event.target.value)}
              />
            </Champ>
            <div className="carte-actions" style={{ alignItems: 'flex-end' }}>
              <button type="button" className="bouton principal" onClick={appliquerFiltresJournal}>
                Appliquer
              </button>
              <button type="button" className="bouton discret" onClick={reinitialiserJournal}>
                Réinitialiser
              </button>
            </div>
          </div>

          {journal.length === 0 ? (
            <EtatVide
              titre="Aucune entrée pour le moment"
              texte="Le journal se remplit automatiquement : connexion, décision du gestionnaire, changement de seuil, gestion de compte."
            />
          ) : (
            <>
              <div className="table-enveloppe">
                <table className="table table-dense">
                  <caption className="visuellement-cache">
                    Journal d’audit de la plateforme
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">Acteur</th>
                      <th scope="col">Rôle</th>
                      <th scope="col">Action</th>
                      <th scope="col">Cible</th>
                      <th scope="col">Détails</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journal.map((entree) => (
                      <tr key={entree.id}>
                        <td>{dateCourte(entree.created_at)}</td>
                        <td className="mono">{entree.acteur}</td>
                        <td>{entree.role}</td>
                        <td>
                          <span className="mono">{entree.action}</span>
                        </td>
                        <td className="mono">{entree.cible ?? '—'}</td>
                        <td>
                          {entree.details === null ||
                          Object.keys(entree.details).length === 0 ? (
                            <span className="aide">—</span>
                          ) : (
                            <details className="journal-details">
                              <summary>Voir</summary>
                              <dl className="journal-details-liste">
                                {Object.entries(entree.details).map(([cle, valeur]) => (
                                  <div key={cle}>
                                    <dt className="mono">{cle}</dt>
                                    <dd>
                                      {typeof valeur === 'object' && valeur !== null
                                        ? JSON.stringify(valeur)
                                        : String(valeur)}
                                    </dd>
                                  </div>
                                ))}
                              </dl>
                            </details>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination
                total={totalJournal}
                offset={offsetJournal}
                limite={LIMITE_JOURNAL}
                onChange={chargerJournal}
                libelle="entrées"
              />
            </>
          )}
        </Carte>
      )}
    </div>
  )
}
