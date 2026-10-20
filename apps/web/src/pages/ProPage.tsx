import { useEffect, useState, type FormEvent } from 'react'

import { api, messageErreur } from '../api/client'
import type {
  InvoiceInput,
  InvoiceSummary,
  Page,
  Prediction,
  References,
} from '../api/types'
import { ShapList } from '../components/ShapList'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  Succes,
  Vide,
  dateCourte,
  montant,
  pourcentage,
} from '../components/ui'

type Onglet = 'depot' | 'suivi' | 'ordonnance' | 'lot'

/** Taille maximale d'un lot. Le CDC en demande 20 ; la marge laisse de quoi
 *  rejouer un lot plus large sans bloquer l'utilisateur. */
const LIMITE_LOT = 200

interface LigneForm {
  code_acte: string
  quantite: number
  montant_unitaire: number
  date_acte: string
}

interface ResultatLot {
  ligne: number
  reference: string
  statut: 'ok' | 'erreur'
  message: string
}

/** Statuts de facture proposes dans le filtre du suivi. */
const STATUTS_AFFICHES: { valeur: string; libelle: string }[] = [
  { valeur: 'reçue', libelle: 'Reçue' },
  { valeur: 'en_cours', libelle: 'En cours' },
  { valeur: 'payee', libelle: 'Payee' },
  { valeur: 'rejetée', libelle: 'Rejetée' },
  { valeur: 'fraude_confirmee', libelle: 'Fraude confirmee' },
  { valeur: 'piece_demandee', libelle: 'Pièce demandée' },
]

function convertirDate(valeur: string): string {
  if (valeur.trim() === '') return ''
  const date = new Date(valeur)
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

function normaliserFacture(
  brut: unknown,
  index: number,
  impose: string | null,
): InvoiceInput {
  if (typeof brut !== 'object' || brut === null) {
    throw new Error(`Facture ${index + 1} : objet attendu.`)
  }
  const objet = brut as Record<string, unknown>
  const assure = String(objet.assure_pseudonyme ?? '').trim()
  const prestataire = impose ?? String(objet.prestataire_id ?? '').trim()
  const dateFacture = convertirDate(String(objet.date_facture ?? ''))
  const lignesBrutes = Array.isArray(objet.lignes) ? objet.lignes : []

  if (assure === '' || prestataire === '' || dateFacture === '' || lignesBrutes.length === 0) {
    // Le message nomme le champ fautif : sans cela, l'utilisateur ne sait
    // pas QUOI corriger. Le prestataire est particulierement piegeux : il
    // est impose par le serveur pour le professionnel, et le laisser vide
    // dans le fichier ne peut pas fonctionner.
    const manquants: string[] = []
    if (assure === '') manquants.push('assure_pseudonyme')
    if (prestataire === '') manquants.push('prestataire_id')
    if (dateFacture === '') manquants.push('date_facture')
    if (lignesBrutes.length === 0) manquants.push('lignes')
    throw new Error(
      `Facture ${index + 1} : champ(s) manquant(s) ou invalide(s) : ${manquants.join(', ')}.`,
    )
  }

  const lignes = lignesBrutes.map((ligne, position) => {
    const valeur = (typeof ligne === 'object' && ligne !== null ? ligne : {}) as Record<
      string,
      unknown
    >
    const code = String(valeur.code_acte ?? '').trim()
    const quantite = Number(valeur.quantite)
    const montantUnitaire = Number(valeur.montant_unitaire)
    const dateActe = convertirDate(String(valeur.date_acte ?? ''))
    const fautifs: string[] = []
    if (code === '') fautifs.push('code_acte')
    if (!Number.isFinite(quantite) || quantite < 1) fautifs.push('quantite')
    if (!Number.isFinite(montantUnitaire) || montantUnitaire < 0) fautifs.push('montant_unitaire')
    if (dateActe === '') fautifs.push('date_acte')
    if (fautifs.length > 0) {
      throw new Error(
        `Facture ${index + 1}, ligne ${position + 1} : ${fautifs.join(', ')} invalide(s).`,
      )
    }
    return {
      code_acte: code,
      quantite,
      montant_unitaire: montantUnitaire,
      date_acte: dateActe,
    }
  })

  return {
    assure_pseudonyme: assure,
    prestataire_id: prestataire,
    date_facture: dateFacture,
    montant_total:
      Math.round(lignes.reduce((total, l) => total + l.quantite * l.montant_unitaire, 0) * 100) /
      100,
    lignes,
  }
}

/** Une facture du lot, avec le numero de ligne qu'elle occupe dans le fichier. */
interface FactureDuLot {
  ligne: number
  facture: InvoiceInput
}

/** Une ligne du lot rejetee a la lecture du fichier. */
interface LigneRejetee {
  ligne: number
  message: string
}

interface LotAnalyse {
  factures: FactureDuLot[]
  rejetees: LigneRejetee[]
}

/**
 * Analyse un lot ligne par ligne, SANS qu'une ligne invalide annule le lot.
 *
 * Le CDC demande au jury de soumettre 20 factures inedites dont des
 * invalides : une facture fautive doit etre REJETEE, pas faire echouer
 * les 19 autres. Une erreur de lecture est donc capturee ligne par ligne
 * et remontee telle quelle, avec son numero.
 */
function analyserLot(texte: string, nom: string, impose: string | null): LotAnalyse {
  const contenu = texte.trim()
  if (contenu === '') throw new Error('Le fichier est vide.')

  const brut: { ligne: number; valeur: unknown }[] = []

  const estJson =
    nom.toLowerCase().endsWith('.json') || contenu.startsWith('[') || contenu.startsWith('{')
  if (estJson) {
    const charge: unknown = JSON.parse(contenu)
    // Deux enveloppes sont acceptees :
    //  - un tableau de factures, ou une facture seule ;
    //  - l'enveloppe du lot canonique du jury, `{ "version": 1,
    //    "factures": [...] }`. C'est le MEME fichier que le job de ligne de
    //    commande soumet : le jury n'a ainsi pas deux jeux de donnees a
    //    maintenir, un pour la ligne de commande et un pour l'interface.
    let elements: unknown[]
    if (Array.isArray(charge)) {
      elements = charge
    } else if (
      typeof charge === 'object' &&
      charge !== null &&
      Array.isArray((charge as Record<string, unknown>).factures)
    ) {
      elements = (charge as Record<string, unknown>).factures as unknown[]
    } else {
      elements = [charge]
    }
    elements.forEach((element, index) => brut.push({ ligne: index + 1, valeur: element }))
  } else {
    const lignes = contenu.split(/\r?\n/).filter((ligne) => ligne.trim() !== '')
    if (lignes.length < 2) {
      throw new Error('Le CSV doit contenir un en-tete et au moins une facture.')
    }
    const entete = lignes[0]
    const separateur =
      (entete.match(/;/g)?.length ?? 0) >= (entete.match(/,/g)?.length ?? 0) ? ';' : ','
    const colonnes = entete.split(separateur).map((valeur) => valeur.trim())
    lignes.slice(1).forEach((ligne, index) => {
      const valeurs = ligne.split(separateur)
      const champs = Object.fromEntries(
        colonnes.map((colonne, position) => [colonne, (valeurs[position] ?? '').trim()]),
      )
      brut.push({
        ligne: index + 1,
        valeur: {
          assure_pseudonyme: champs.assure_pseudonyme,
          prestataire_id: champs.prestataire_id,
          date_facture: champs.date_facture,
          lignes: [
            {
              code_acte: champs.code_acte,
              quantite: champs.quantite,
              montant_unitaire: champs.montant_unitaire,
              date_acte: champs.date_acte || champs.date_facture,
            },
          ],
        },
      })
    })
  }

  const factures: FactureDuLot[] = []
  const rejetees: LigneRejetee[] = []
  for (const entree of brut) {
    try {
      factures.push({
        ligne: entree.ligne,
        facture: normaliserFacture(entree.valeur, entree.ligne - 1, impose),
      })
    } catch (probleme) {
      rejetees.push({
        ligne: entree.ligne,
        message: probleme instanceof Error ? probleme.message : 'Ligne illisible.',
      })
    }
  }
  return { factures, rejetees }
}

function maintenantLocal(): string {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

export function ProPage() {
  const [onglet, setOnglet] = useState<Onglet>('depot')
  const [references, setReferences] = useState<References | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  const [assure, setAssure] = useState('')
  const [prestataire, setPrestataire] = useState('')
  const [dateFacture, setDateFacture] = useState(maintenantLocal())
  const [lignes, setLignes] = useState<LigneForm[]>([])
  const [resultat, setResultat] = useState<Prediction | null>(null)

  const [factures, setFactures] = useState<InvoiceSummary[]>([])
  const [totalSuivi, setTotalSuivi] = useState(0)
  const [chargementSuivi, setChargementSuivi] = useState(true)
  const [filtreStatut, setFiltreStatut] = useState('')

  const [lotNom, setLotNom] = useState('')
  const [lotTexte, setLotTexte] = useState('')
  const [lotEnCours, setLotEnCours] = useState(false)
  const [lotAnnule, setLotAnnule] = useState(false)
  const [lotTraitees, setLotTraitees] = useState(0)
  const [lotResultats, setLotResultats] = useState<ResultatLot[]>([])

  const [ordonnance, setOrdonnance] = useState({
    code_acte: '',
    date_ordonnance: maintenantLocal(),
    quantite: 1,
    reference: '',
    diagnostic: '',
    validite_jours: 30,
  })

  const chargerSuivi = (offset = 0) => {
    setChargementSuivi(true)
    const filtre = filtreStatut === '' ? '' : `&statut=${encodeURIComponent(filtreStatut)}`
    api<Page<InvoiceSummary>>(`/api/core/factures?limit=100&offset=${offset}${filtre}`)
      .then((page) => {
        setFactures((precedent) =>
          offset === 0 ? page.items : [...precedent, ...page.items],
        )
        setTotalSuivi(page.total)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
      .finally(() => setChargementSuivi(false))
  }

  useEffect(() => {
    api<References>('/api/core/factures/references')
      .then((valeurs) => {
        setReferences(valeurs)
        if (valeurs.assures.length > 0) setAssure(valeurs.assures[0].pseudonyme)
        const propre = valeurs.prestataire_du_compte ?? null
        if (propre !== null) setPrestataire(propre)
        else if (valeurs.prestataires.length > 0) setPrestataire(valeurs.prestataires[0].code)
        const premier = valeurs.actes[0]
        if (premier !== undefined) {
          setLignes([
            {
              code_acte: premier.code,
              quantite: 1,
              montant_unitaire: premier.prix_unitaire,
              date_acte: maintenantLocal(),
            },
          ])
          setOrdonnance((precedent) => ({ ...precedent, code_acte: premier.code }))
        }
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
    chargerSuivi()
  }, [])

  const total = lignes.reduce(
    (somme, ligne) => somme + ligne.quantite * ligne.montant_unitaire,
    0,
  )

  const changerActe = (index: number, code: string) => {
    const acte = references?.actes.find((valeur) => valeur.code === code)
    setLignes((precedent) =>
      precedent.map((ligne, position) =>
        position === index
          ? {
              ...ligne,
              code_acte: code,
              montant_unitaire: acte !== undefined ? acte.prix_unitaire : ligne.montant_unitaire,
            }
          : ligne,
      ),
    )
  }

  const ajouterLigne = () => {
    const premier = references?.actes[0]
    setLignes((precedent) => [
      ...precedent,
      {
        code_acte: premier?.code ?? '',
        quantite: 1,
        montant_unitaire: premier?.prix_unitaire ?? 0,
        date_acte: dateFacture,
      },
    ])
  }

  const retirerLigne = (index: number) => {
    setLignes((precedent) => precedent.filter((_, position) => position !== index))
  }

  const soumettre = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)

    const probleme =
      assure === ''
        ? 'Choisissez un assure.'
        : prestataire === ''
          ? 'Choisissez un prestataire.'
          : lignes.length === 0
            ? 'Ajoutez au moins une ligne de facture.'
            : lignes.some((ligne) => ligne.code_acte === '')
              ? 'Chaque ligne doit référence un acte.'
              : total > 10_000_000
                ? 'Le montant total depasse le plafond accepte (10 000 000).'
                : null

    if (probleme !== null) {
      setErreur(probleme)
      return
    }

    const charge: InvoiceInput = {
      assure_pseudonyme: assure,
      prestataire_id: prestataire,
      date_facture: new Date(dateFacture).toISOString(),
      montant_total: total,
      lignes: lignes.map((ligne) => ({
        code_acte: ligne.code_acte,
        quantite: ligne.quantite,
        montant_unitaire: ligne.montant_unitaire,
        date_acte: new Date(ligne.date_acte).toISOString(),
      })),
    }

    setEnvoi(true)
    try {
      const prediction = await api<Prediction>('/api/core/factures/soumettre', {
        method: 'POST',
        body: JSON.stringify(charge),
      })
      setResultat(prediction)
      setSucces(`Facture ${prediction.facture_id} enregistree et notee par le modele.`)
      chargerSuivi()
    } catch (problemeTechnique) {
      setErreur(messageErreur(problemeTechnique))
      setResultat(null)
    } finally {
      setEnvoi(false)
    }
  }

  const soumettreOrdonnance = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErreur(null)
    setSucces(null)
    setEnvoi(true)
    try {
      const reponse = await api<{ status: string; reference: string }>(
        '/api/core/factures/ordonnances',
        {
          method: 'POST',
          body: JSON.stringify({
            assure_pseudonyme: assure,
            prestataire_id: prestataire,
            code_acte: ordonnance.code_acte,
            date_ordonnance: new Date(ordonnance.date_ordonnance).toISOString(),
            quantite: ordonnance.quantite,
            reference: ordonnance.reference.trim() || undefined,
            diagnostic: ordonnance.diagnostic.trim() || undefined,
            validite_jours: ordonnance.validite_jours,
          }),
        },
      )
      setSucces(`Ordonnance enregistree (${reponse.reference}).`)
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setEnvoi(false)
    }
  }

  const chargerFichierLot = (fichier: File | undefined) => {
    if (fichier === undefined) return
    setLotNom(fichier.name)
    setLotResultats([])
    fichier
      .text()
      .then(setLotTexte)
      .catch(() => setErreur('Fichier illisible.'))
  }

  const importerLot = async () => {
    setErreur(null)
    setSucces(null)
    setLotResultats([])
    // Le prestataire du compte prime (perimetre serveur). A defaut, on prend
    // celui selectionne dans le formulaire de depot : un administrateur, qui
    // n'a pas de perimetre impose, peut ainsi importer un lot sans avoir a
    // recopier le code dans chaque ligne du fichier.
    const impose = references?.prestataire_du_compte ?? (prestataire || null)

    let analyse: LotAnalyse
    try {
      analyse = analyserLot(lotTexte, lotNom, impose)
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : 'Lot illisible.')
      return
    }

    const total = analyse.factures.length + analyse.rejetees.length
    if (total === 0) {
      setErreur('Aucune facture dans le lot.')
      return
    }
    if (total > LIMITE_LOT) {
      setErreur(`Un lot est limité à ${LIMITE_LOT} factures.`)
      return
    }

    setLotEnCours(true)
    setLotAnnule(false)
    setLotTraitees(0)
    // Les lignes rejetees a la LECTURE du fichier sont reportees telles
    // quelles : une facture fautive ne doit pas disparaitre du bilan.
    const resultats: ResultatLot[] = analyse.rejetees.map((rejetee) => ({
      ligne: rejetee.ligne,
      reference: '-',
      statut: 'erreur',
      message: rejetee.message,
    }))
    setLotResultats([...resultats])

    for (const entree of analyse.factures) {
      // L'annulation est comprise ENTRE deux factures : une importation
      // de 20 factures ne doit pas pouvoir etre interrompue au milieu
      // d'une requete, mais doit pouvoir s'arreter ensuite.
      if (lotAnnule) break
      try {
        const prediction = await api<Prediction>('/api/core/factures/soumettre', {
          method: 'POST',
          body: JSON.stringify(entree.facture),
        })
        resultats.push({
          ligne: entree.ligne,
          reference: prediction.facture_id,
          statut: 'ok',
          message: `${pourcentage(prediction.score_fraude)} - ${
            prediction.is_fraud ? 'alerte' : 'sous le seuil'
          }`,
        })
      } catch (probleme) {
        resultats.push({
          ligne: entree.ligne,
          reference: entree.facture.facture_id ?? '-',
          statut: 'erreur',
          message: messageErreur(probleme),
        })
      }
      setLotTraitees((precedent) => precedent + 1)
      setLotResultats([...resultats].sort((a, b) => a.ligne - b.ligne))
    }
    setLotEnCours(false)
    const reussies = resultats.filter((resultat) => resultat.statut === 'ok').length
    const refusees = resultats.length - reussies
    setSucces(
      lotAnnule
        ? `Import interrompu : ${reussies} facture(s) importée(s), ${refusees} rejetée(s).`
        : `${reussies} facture(s) importée(s), ${refusees} rejetée(s) sur ${resultats.length}.`,
    )
    chargerSuivi()
  }

  /**
   * Charge le lot de 20 factures du jury, embarque dans le bundle.
   *
   * Le fichier est le MEME que le job de ligne de commande soumet : le
   * jury n'a donc pas a chercher un fichier sur le disque, et l'ecran
   * montre exactement ce que la demonstration soumettra.
   */
  const chargerLotJury = async () => {
    setErreur(null)
    setSucces(null)
    try {
      const reponse = await fetch('/lot-jury.json')
      if (!reponse.ok) throw new Error(`Fichier introuvable (${reponse.status}).`)
      const texte = await reponse.text()
      setLotTexte(texte)
      setLotNom('lot_20_factures.json')
      setLotResultats([])
      setSucces('Lot du jury chargé : 20 factures, dont des factures invalides.')
    } catch (probleme) {
      setErreur(
        probleme instanceof Error
          ? `Lot du jury indisponible : ${probleme.message}`
          : 'Lot du jury indisponible.',
      )
    }
  }

  return (
    <div className="pile">
      <div className="titre-page">
        <h1>Espace professionnel de santé</h1>
        <p>Dépôt des factures et des ordonnances, puis suivi des dossiers.</p>
      </div>

      <div className="onglets" role="tablist">
        {(
          [
            ['depot', 'Deposer une facture'],
            ['lot', 'Import de lot'],
            ['suivi', 'Suivi des dossiers'],
            ['ordonnance', 'Ordonnance'],
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

      {onglet === 'depot' && (
        <div className="grille deux-large">
          <Carte titre="Nouvelle facture">
            {references === null ? (
              <Chargement texte="Chargement des référentiels..." />
            ) : (
              <form className="formulaire" onSubmit={soumettre} style={{ background: 'rgba(255,255,255,0.5)', padding: '1.2rem', borderRadius: 'var(--rayon)', border: '1px solid var(--bord)' }}>
                <div className="grille deux">
                  <Champ label="Assure (pseudonyme)">
                    <select value={assure} onChange={(event) => setAssure(event.target.value)}>
                      {references.assures.map((valeur) => (
                        <option key={valeur.pseudonyme} value={valeur.pseudonyme}>
                          {valeur.pseudonyme}
                        </option>
                      ))}
                    </select>
                  </Champ>
                  <Champ label="Prestataire">
                    <select
                      value={prestataire}
                      onChange={(event) => setPrestataire(event.target.value)}
                      disabled={references.prestataire_du_compte != null}
                    >
                      {references.prestataires.map((valeur) => (
                        <option key={valeur.code} value={valeur.code}>
                          {valeur.code} - {valeur.nom}
                        </option>
                      ))}
                    </select>
                  </Champ>
                </div>
                {references.prestataire_du_compte != null && (
                  <p className="aide">
                    Votre compte est rattache a {references.prestataire_du_compte} : le
                    prestataire est impose par le serveur.
                  </p>
                )}

                <Champ label="Date de la facture">
                  <input
                    type="datetime-local"
                    value={dateFacture}
                    onChange={(event) => setDateFacture(event.target.value)}
                    required
                  />
                </Champ>

                <div className="lignes-entete">
                  <h3>Lignes</h3>
                  <button type="button" className="bouton discret" onClick={ajouterLigne}>
                    Ajouter une ligne
                  </button>
                </div>

                {lignes.map((ligne, index) => (
                  <div className="ligne-facture" key={index}>
                    <select
                      value={ligne.code_acte}
                      onChange={(event) => changerActe(index, event.target.value)}
                      aria-label="Acte"
                    >
                      {references.actes.map((acte) => (
                        <option key={acte.code} value={acte.code}>
                          {acte.code} - {acte.libelle}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={1}
                      max={999}
                      value={ligne.quantite}
                      aria-label="Quantite"
                      onChange={(event) =>
                        setLignes((precedent) =>
                          precedent.map((valeur, position) =>
                            position === index
                              ? { ...valeur, quantite: Number(event.target.value) }
                              : valeur,
                          ),
                        )
                      }
                    />
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={ligne.montant_unitaire}
                      aria-label="Montant unitaire"
                      onChange={(event) =>
                        setLignes((precedent) =>
                          precedent.map((valeur, position) =>
                            position === index
                              ? { ...valeur, montant_unitaire: Number(event.target.value) }
                              : valeur,
                          ),
                        )
                      }
                    />
                    <input
                      type="datetime-local"
                      value={ligne.date_acte}
                      aria-label="Date de l acte"
                      onChange={(event) =>
                        setLignes((precedent) =>
                          precedent.map((valeur, position) =>
                            position === index
                              ? { ...valeur, date_acte: event.target.value }
                              : valeur,
                          ),
                        )
                      }
                    />
                    <button
                      type="button"
                      className="bouton danger"
                      onClick={() => retirerLigne(index)}
                      disabled={lignes.length === 1}
                    >
                      Retirer
                    </button>
                  </div>
                ))}

                <p className="total">
                  Montant total calcule : <strong>{montant(total)}</strong>
                </p>

                <button type="submit" className="bouton principal large" disabled={envoi}>
                  {envoi ? 'Envoi et notation...' : 'Envoyer et noter la facture'}
                </button>
              </form>
            )}
          </Carte>

          <Carte titre="Résultat de la notation">
            {resultat === null ? (
              <Vide>
                Le score, le seuil applique et le rapport SHAP s afficheront ici apres l envoi.
              </Vide>
            ) : (
              <div className="resultat">
                <div className="score-bloc">
                  <span className="score-valeur">{pourcentage(resultat.score_fraude)}</span>
                  <span className="score-legende">score de fraude</span>
                </div>
                <div className="resultat-meta">
                  <Badge ton={resultat.is_fraud ? 'alerte' : 'ok'}>
                    {resultat.is_fraud ? 'Au-dessus du seuil - alerte' : 'Sous le seuil'}
                  </Badge>
                  <span>Seuil : {pourcentage(resultat.seuil_applique)}</span>
                  <span>Modele : {resultat.model_version}</span>
                  <span>{resultat.inference_ms.toFixed(1)} ms</span>
                </div>
                {resultat.notification !== undefined && (
                  <p
                    className={resultat.notification.envoye ? 'succes' : 'aide'}
                    role="status"
                  >
                    {resultat.notification.envoye ? '✓ ' : 'ℹ '}
                    {resultat.notification.message}
                  </p>
                )}
                <h3>Explication SHAP</h3>
                <ShapList contributions={resultat.shap} />
              </div>
            )}
          </Carte>
        </div>
      )}

      {onglet === 'suivi' && (
        <Carte
          titre={`${factures.length} sur ${totalSuivi} dossier(s)`}
          actions={
            <>
              <label className="champ-label" htmlFor="filtre-statut">
                Statut
              </label>
              <select
                id="filtre-statut"
                value={filtreStatut}
                onChange={(event) => {
                  setFiltreStatut(event.target.value)
                  setFactures([])
                  chargerSuivi(0)
                }}
              >
                <option value="">Tous les statuts</option>
                {STATUTS_AFFICHES.map((statut) => (
                  <option key={statut.valeur} value={statut.valeur}>
                    {statut.libelle}
                  </option>
                ))}
              </select>
            </>
          }
        >
          {chargementSuivi && <Chargement />}
          {!chargementSuivi && factures.length === 0 && <Vide>Aucun dossier déposé.</Vide>}
          {factures.length > 0 && (
            <div className="table-enveloppe">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Assure</th>
                    <th>Prestataire</th>
                    <th className="droite">Montant</th>
                    <th className="droite">Score</th>
                    <th>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {factures.map((facture) => (
                    <tr key={facture.facture_id}>
                      <td>{dateCourte(facture.date_facture)}</td>
                      <td className="mono">{facture.assure_pseudonyme}</td>
                      <td className="mono">{facture.prestataire_id}</td>
                      <td className="droite">{montant(facture.montant_total)}</td>
                      <td className="droite">
                        {facture.score_fraude === null
                          ? '-'
                          : pourcentage(facture.score_fraude)}
                      </td>
                      <td>{facture.statut}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!chargementSuivi && factures.length < totalSuivi && (
            <button
              type="button"
              className="bouton discret"
              onClick={() => chargerSuivi(factures.length)}
            >
              Charger la suite ({totalSuivi - factures.length} restantes)
            </button>
          )}
        </Carte>
      )}

      {onglet === 'lot' && (
        <Carte
          titre="Import de lot"
          actions={
            <div className="carte-actions">
              <button
                type="button"
                className="bouton discret"
                onClick={() => void chargerLotJury()}
                disabled={lotEnCours}
              >
                Charger le lot du jury
              </button>
            </div>
          }
        >
          <p className="aide">
            Fichier JSON (tableau de factures) ou CSV avec les colonnes
            assure_pseudonyme, date_facture, code_acte, quantite, montant_unitaire,
            date_acte. Chaque facture est notee individuellement : une ligne en erreur
            n arrete pas le lot.
          </p>

          <div className="formulaire">
            <Champ label="Fichier (.json ou .csv)">
              <input
                type="file"
                accept=".json,.csv,application/json,text/csv"
                onChange={(event) => chargerFichierLot(event.target.files?.[0])}
              />
            </Champ>

            <Champ
              label="Contenu (modifiable)"
              aide="Collez un tableau JSON ou un CSV. Le prestataire impose par le serveur prime."
            >
              <textarea
                rows={6}
                value={lotTexte}
                onChange={(event) => setLotTexte(event.target.value)}
                placeholder='[{"assure_pseudonyme":"ASS-00001","date_facture":"2026-10-20T10:00:00Z","lignes":[{"code_acte":"ACT-001","quantite":1,"montant_unitaire":50,"date_acte":"2026-10-20T10:00:00Z"}]}]'
              />
            </Champ>

            <div className="boutons-ligne">
              <button
                type="button"
                className="bouton principal"
                onClick={() => void importerLot()}
                disabled={lotEnCours || lotTexte.trim() === ''}
              >
                {lotEnCours ? 'Import en cours...' : 'Importer le lot'}
              </button>
              {lotEnCours ? (
                <button
                  type="button"
                  className="bouton danger"
                  onClick={() => setLotAnnule(true)}
                >
                  Annuler l’import
                </button>
              ) : (
                <button
                  type="button"
                  className="bouton discret"
                  onClick={() => {
                    setLotTexte('')
                    setLotNom('')
                    setLotResultats([])
                  }}
                >
                  Vider
                </button>
              )}
            </div>
            {lotNom !== '' && <p className="aide">Fichier : {lotNom}</p>}
          </div>

          {lotEnCours && (
            <p className="aide" role="status" aria-live="polite">
              {lotTraitees} facture(s) traitée(s)…
              {lotAnnule ? ' Annulation demandée.' : ''}
            </p>
          )}

          {lotResultats.length > 0 && (
            <div className="table-enveloppe">
              <table className="table table-dense">
                <caption className="visuellement-cache">
                  Résultat de l’import du lot, ligne par ligne
                </caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Référence</th>
                    <th scope="col">Statut</th>
                    <th scope="col">Détail</th>
                  </tr>
                </thead>
                <tbody>
                  {lotResultats.map((resultat) => (
                    <tr key={resultat.ligne}>
                      <td>{resultat.ligne}</td>
                      <td className="mono">{resultat.reference}</td>
                      <td>
                        <Badge ton={resultat.statut === 'ok' ? 'ok' : 'alerte'}>
                          {resultat.statut}
                        </Badge>
                      </td>
                      <td>{resultat.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Carte>
      )}

      {onglet === 'ordonnance' && (
        <Carte titre="Deposer une ordonnance">
          {references === null ? (
            <Chargement />
          ) : (
            <form className="formulaire" onSubmit={soumettreOrdonnance}>
              <div className="grille deux">
                <Champ label="Assure (pseudonyme)">
                  <select value={assure} onChange={(event) => setAssure(event.target.value)}>
                    {references.assures.map((valeur) => (
                      <option key={valeur.pseudonyme} value={valeur.pseudonyme}>
                        {valeur.pseudonyme}
                      </option>
                    ))}
                  </select>
                </Champ>
                <Champ label="Prestataire">
                  <select
                    value={prestataire}
                    onChange={(event) => setPrestataire(event.target.value)}
                    disabled={references.prestataire_du_compte != null}
                  >
                    {references.prestataires.map((valeur) => (
                      <option key={valeur.code} value={valeur.code}>
                        {valeur.code} - {valeur.nom}
                      </option>
                    ))}
                  </select>
                </Champ>
                <Champ label="Acte prescrit">
                  <select
                    value={ordonnance.code_acte}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        code_acte: event.target.value,
                      }))
                    }
                  >
                    {references.actes.map((acte) => (
                      <option key={acte.code} value={acte.code}>
                        {acte.code} - {acte.libelle}
                      </option>
                    ))}
                  </select>
                </Champ>
                <Champ label="Date de l ordonnance">
                  <input
                    type="datetime-local"
                    value={ordonnance.date_ordonnance}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        date_ordonnance: event.target.value,
                      }))
                    }
                  />
                </Champ>
                <Champ label="Quantite">
                  <input
                    type="number"
                    min={1}
                    max={999}
                    value={ordonnance.quantite}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        quantite: Number(event.target.value),
                      }))
                    }
                  />
                </Champ>
                <Champ label="Validite (jours)">
                  <input
                    type="number"
                    min={1}
                    max={730}
                    value={ordonnance.validite_jours}
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        validite_jours: Number(event.target.value),
                      }))
                    }
                  />
                </Champ>
                <Champ label="Reference (facultatif)">
                  <input
                    value={ordonnance.reference}
                    maxLength={64}
                    placeholder="Générée automatiquement si vide"
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        reference: event.target.value,
                      }))
                    }
                  />
                </Champ>
                <Champ label="Diagnostic (facultatif)">
                  <input
                    value={ordonnance.diagnostic}
                    maxLength={256}
                    placeholder="Ex. lombalgie aigue"
                    onChange={(event) =>
                      setOrdonnance((precedent) => ({
                        ...precedent,
                        diagnostic: event.target.value,
                      }))
                    }
                  />
                </Champ>
              </div>
              <p className="aide">
                La validite et le diagnostic alimentent les variables de prescription du
                modele. Un doublon (meme assure, meme acte, meme jour) est refuse.
              </p>
              <button type="submit" className="bouton principal" disabled={envoi}>
                {envoi ? 'Enregistrement...' : 'Enregistrer l ordonnance'}
              </button>
            </form>
          )}
        </Carte>
      )}
    </div>
  )
}
