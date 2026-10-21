/**
 * Captures d'ecran de la presentation.
 *
 * Le script pilote un navigateur reel (Chromium de Playwright) sur la pile
 * locale et enregistre les ecrans utilises pour la soutenance. Chaque role
 * ouvre son propre contexte : l'application garde son jeton en sessionStorage,
 * un changement de role exige donc une session neuve.
 *
 * Usage :
 *     cd apps/web && node scripts/captures.mjs
 *
 * Variables attendues (via `make captures`, qui les lit dans le `.env`) :
 *     DEMO_PASSWORD            mot de passe des comptes de l'application
 *     SUPERSET_DEMO_PASSWORD   mot de passe du compte de demonstration BI
 *     GRAFANA_ADMIN_PASSWORD   mot de passe administrateur Grafana
 *     N8N_EMAIL, N8N_MDP      compte proprietaire n8n (jamais dans le .env)
 */

import { chromium } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ICI = dirname(fileURLToPath(import.meta.url))
const RACINE = resolve(ICI, '..', '..', '..')
const SORTIE = process.env.CAPTURES_SORTIE ?? '/home/jerry/Documents/pic-pitch'

const APP = 'http://localhost:8080'
const SUPERSET = 'http://localhost:8088'
const GRAFANA = 'http://localhost:3001'
const PROMETHEUS = 'http://localhost:9090'
const MLFLOW = 'http://localhost:5000'
const N8N = 'http://localhost:5678'

const DOSSIERS = {
  1: '1-introduction',
  2: '2-architecture',
  3: '3-ia',
  4: '4-demo',
  5: '5-gouvernance',
}

let reussis = 0
let echecs = 0

async function lireEnv() {
  const texte = await readFile(resolve(RACINE, '.env'), 'utf8')
  const valeurs = {}
  for (const ligne of texte.split('\n')) {
    const correspondance = ligne.match(/^([A-Z0-9_]+)=(.*)$/)
    if (correspondance) valeurs[correspondance[1]] = correspondance[2].trim()
  }
  return valeurs
}

async function shot(page, partie, nom) {
  const dossier = resolve(SORTIE, DOSSIERS[partie])
  await mkdir(dossier, { recursive: true })
  await page.waitForTimeout(700)
  await page.screenshot({ path: resolve(dossier, `${nom}.png`), fullPage: false })
  reussis += 1
  console.log(`  ok  ${DOSSIERS[partie]}/${nom}.png`)
}

async function tenter(nom, action) {
  try {
    await action()
  } catch (erreur) {
    echecs += 1
    console.log(`  KO  ${nom} : ${String(erreur).split('\n')[0]}`)
  }
}

async function cliquer(page, libelles) {
  for (const libelle of libelles) {
    const cible = page.locator(`button:has-text("${libelle}"), a:has-text("${libelle}")`).first()
    if (await cible.count()) {
      await cible.click()
      return true
    }
  }
  return false
}

/** Ouvre une session neuve pour un compte de l'application. */
async function sessionRole(navigateur, email, motDePasse) {
  const contexte = await navigateur.newContext({
    viewport: { width: 1600, height: 900 },
    locale: 'fr-FR',
  })
  const page = await contexte.newPage()
  await page.goto(`${APP}/connexion`, { waitUntil: 'domcontentloaded' })
  await page.getByLabel('ADRESSE E-MAIL').fill(email)
  await page.getByLabel('MOT DE PASSE').fill(motDePasse)
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByRole('button', { name: 'Menu du profil' }).waitFor({ timeout: 20000 })
  return { contexte, page }
}

async function principal() {
  const env = await lireEnv()
  const mdpApp = process.env.DEMO_PASSWORD ?? env.DEMO_PASSWORD
  const mdpSuperset = process.env.SUPERSET_DEMO_PASSWORD ?? env.SUPERSET_DEMO_PASSWORD
  const mdpGrafana = process.env.GRAFANA_ADMIN_PASSWORD ?? env.GRAFANA_ADMIN_PASSWORD
  const mdpN8n = process.env.N8N_MDP
  const emailN8n = process.env.N8N_EMAIL
  if (mdpN8n && !emailN8n) {
    throw new Error('N8N_EMAIL est obligatoire avec N8N_MDP (compte proprietaire n8n)')
  }

  const navigateur = await chromium.launch({ args: ['--no-sandbox'] })

  // ---------------------------------------------------------------- partie 1
  await tenter('p1_accueil_professionnel', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'pro@predicare.local', mdpApp)
    await page.goto(`${APP}/professionnel`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)
    await shot(page, 1, 'p1_accueil_professionnel')
    await contexte.close()
  })

  await tenter('p1_pilotage_application', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'admin@predicare.local', mdpApp)
    await page.goto(`${APP}/pilotage`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(6000)
    await shot(page, 1, 'p1_pilotage_application')
    await contexte.close()
  })

  // ---------------------------------------------------------------- partie 2
  await tenter('p2_observabilite', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'admin@predicare.local', mdpApp)
    await page.goto(`${APP}/administration/observabilite`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await shot(page, 2, 'p2_observabilite')
    await contexte.close()
  })

  await tenter('p2_grafana_vue_service', async () => {
    const contexte = await navigateur.newContext({ viewport: { width: 1600, height: 900 } })
    const page = await contexte.newPage()
    await page.goto(`${GRAFANA}/login`, { waitUntil: 'domcontentloaded' })
    await page.locator('input[name="user"], input[name="login"]').first().fill('admin')
    await page.locator('input[name="password"]').first().fill(mdpGrafana)
    await cliquer(page, ['Log in', 'Se connecter', 'Sign in'])
    await page.waitForTimeout(5000)
    await page.goto(`${GRAFANA}/d/predicare-vue-service/predicare-vue-service`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(5000)
    await shot(page, 2, 'p2_grafana_vue_service')
    await contexte.close()
  })

  await tenter('p2_prometheus_regles', async () => {
    const contexte = await navigateur.newContext({ viewport: { width: 1600, height: 900 } })
    const page = await contexte.newPage()
    await page.goto(`${PROMETHEUS}/alerts`, { waitUntil: 'domcontentloaded', timeout: 90000 })
    await page.waitForTimeout(3000)
    await shot(page, 2, 'p2_prometheus_regles')
    await contexte.close()
  })

  // ---------------------------------------------------------------- partie 3
  await tenter('p3_seuil_modele', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'admin@predicare.local', mdpApp)
    await page.goto(`${APP}/administration/modele`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    await shot(page, 3, 'p3_seuil_modele')
    await page.goto(`${APP}/administration/seuil`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)
    await shot(page, 3, 'p3_seuil_valeur')
    await contexte.close()
  })

  await tenter('p3_mlflow_experiences', async () => {
    const contexte = await navigateur.newContext({ viewport: { width: 1600, height: 900 } })
    const page = await contexte.newPage()
    await page.goto(`${MLFLOW}/#/experiments/1`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(7000)
    await shot(page, 3, 'p3_mlflow_experiences')
    const reponse = await fetch(`${MLFLOW}/api/2.0/mlflow/runs/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ experiment_ids: ['1'], max_results: 10 }),
    })
    const donnees = await reponse.json()
    const runs = (donnees.runs ?? []).filter((r) => r.info?.status === 'FINISHED')
    if (runs.length) {
      await page.goto(`${MLFLOW}/#/experiments/1/runs/${runs[0].info.run_id}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(7000)
      await shot(page, 3, 'p3_mlflow_run')
    }
    await contexte.close()
  })

  await tenter('p3_assistant_rag', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'assure@predicare.local', mdpApp)
    await page.goto(`${APP}/assure/assistant`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)
    const champ = page.locator('textarea').first()
    if (await champ.count()) {
      await champ.fill('Quel est mon reste a charge sur mes factures payees ?')
      await page.keyboard.press('Enter')
      await page.waitForTimeout(30000)
    }
    await shot(page, 3, 'p3_assistant_rag')
    await contexte.close()
  })

  await tenter('p3_n8n', async () => {
    if (!mdpN8n) throw new Error('N8N_MDP absent')
    const contexte = await navigateur.newContext({ viewport: { width: 1600, height: 900 } })
    const page = await contexte.newPage()
    await page.goto(`${N8N}/workflows`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    if (await page.locator('input[type="email"]').count()) {
      await page.locator('input[type="email"]').fill(emailN8n)
      await page.locator('input[type="password"]').fill(mdpN8n)
      await page.locator('button:has-text("Sign in")').first().click()
      await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 30000 })
      await page.waitForTimeout(6000)
    }
    await shot(page, 3, 'p3_n8n_workflows')

    await page.goto(`${N8N}/executions`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(5000)
    await shot(page, 3, 'p3_n8n_executions')

    await page.goto(`${N8N}/workflows`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(5000)
    const lien = page.getByText('PK-Alerte-Fraude-Interne', { exact: false }).first()
    if (await lien.count()) {
      await lien.click()
      await page.waitForTimeout(7000)
    }
    await shot(page, 3, 'p3_n8n_canvas')
    await contexte.close()
  })

  // ---------------------------------------------------------------- partie 4
  await tenter('p4_file_alertes', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'gestionnaire@predicare.local', mdpApp)
    await page.goto(`${APP}/gestionnaire`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3500)
    await shot(page, 4, 'p4_file_alertes')
    const ligne = page.locator('.alerte-item').first()
    if (await ligne.count()) {
      await ligne.click()
      await page.waitForTimeout(4000)
      await shot(page, 4, 'p4_detail_alerte')
    }
    await contexte.close()
  })

  await tenter('p4_pilotage_bi', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'admin@predicare.local', mdpApp)
    await page.goto(`${APP}/pilotage`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(7000)
    await shot(page, 4, 'p4_pilotage_bi')
    await contexte.close()
  })

  // Pas de capture Superset plein ecran : le compte de demonstration est en
  // lecture stricte et ne voit ni tableau ni tuile dans sa liste. Le tableau
  // se montre par l'application (jeton d'invite, page /pilotage), c'est
  //.capture plus haut.
  // ---------------------------------------------------------------- partie 5
  await tenter('p5_grafana_vue_modele', async () => {
    const contexte = await navigateur.newContext({ viewport: { width: 1600, height: 900 } })
    const page = await contexte.newPage()
    await page.goto(`${GRAFANA}/login`, { waitUntil: 'domcontentloaded' })
    await page.locator('input[name="user"], input[name="login"]').first().fill('admin')
    await page.locator('input[name="password"]').first().fill(mdpGrafana)
    await cliquer(page, ['Log in', 'Se connecter', 'Sign in'])
    await page.waitForTimeout(5000)
    await page.goto(`${GRAFANA}/d/predicare-vue-modele/predicare-vue-modele`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(6000)
    await shot(page, 5, 'p5_grafana_vue_modele')
    await contexte.close()
  })

  await tenter('p5_journal_actions', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'admin@predicare.local', mdpApp)
    await page.goto(`${APP}/administration/journal`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await shot(page, 5, 'p5_journal_actions')
    await contexte.close()
  })

  await tenter('p5_securite_canaux', async () => {
    const { contexte, page } = await sessionRole(navigateur, 'admin@predicare.local', mdpApp)
    await page.goto(`${APP}/administration/canaux`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    await shot(page, 5, 'p5_securite_canaux')
    await contexte.close()
  })

  await navigateur.close()
  console.log(`\n  ${reussis} capture(s) reussie(s), ${echecs} echec(s).`)
  return echecs === 0 ? 0 : 1
}

principal()
  .then((code) => process.exit(code))
  .catch((erreur) => {
    console.error(erreur)
    process.exit(1)
  })
