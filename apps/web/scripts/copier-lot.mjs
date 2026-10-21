// Artefact de developpement : `apps/web/public/lot-jury.json` n'est PAS
// versionne. Il est produit ici depuis `data/seed/lot_20_factures.json`, le
// meme fichier que celui soumis par le job de ligne de commande.
//
// Pourquoi ce script : l'ecran « Charger le lot du jury » fait
// `fetch('/lot-jury.json')`. En image Docker, `apps/web/Dockerfile` copie le
// lot dans `public/` avant le build. En `npm run dev` (ou pour un `vite
// build` hors Docker), ce fichier n'existait pas : le bouton renvoyait 404.
// `predev` et `prebuild` le generent donc a la demande.
//
// En image Docker, `data/seed/` n'est pas dans le contexte du builder : la
// source est absente, mais le Dockerfile a deja copie le lot dans `public/`.
// Le script le constate et s'arrete sans erreur, pour ne pas casser l'image.

import { copyFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ici = dirname(fileURLToPath(import.meta.url)) // apps/web/scripts
const racineDepot = resolve(ici, '../../..')
const source = resolve(racineDepot, 'data/seed/lot_20_factures.json')
const destination = resolve(ici, '../public/lot-jury.json')

if (!existsSync(source)) {
  if (existsSync(destination)) {
    // Cas de l'image Docker : le Dockerfile a deja pose le fichier.
    console.log(`[lot-jury] Source absente (${source}) ; ${destination} deja present, conserve.`)
    process.exit(0)
  }
  console.warn(`[lot-jury] Source introuvable : ${source}`)
  console.warn(
    '[lot-jury] Le bouton « Charger le lot du jury » sera indisponible (404). ' +
      'Verifiez que vous executez le script depuis un depot complet.',
  )
  process.exit(0)
}

copyFileSync(source, destination)
console.log(`[lot-jury] ${source} -> ${destination}`)
