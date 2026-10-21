import { useEffect, useRef, useState } from 'react'

import { api, apiFormData, messageErreur } from '../../api/client'
import type { InvoiceInput, Prediction, References, ShapContribution } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { EnTetePage } from '../../components/blocs'
import { ShapList } from '../../components/ShapList'
import {
  Badge,
  Carte,
  Champ,
  Chargement,
  Erreur,
  EtatVide,
  Succes,
  pourcentage,
} from '../../components/ui'

/** Taille maximale d'un lot. Le CDC en demande 20 ; la marge laisse de quoi
 *  rejouer un lot plus large sans bloquer l'utilisateur. */
const LIMITE_LOT = 200

/** Le CDC fait passer 20 factures PDF au jury : l'ecran refuse au-dela, ce
 *  qui evite un envoi massif par erreur (le serveur tolere davantage). */
const LIMITE_PDF = 20

interface ResultatLot {
  ligne: number
  /** Fichier d'origine : nom du PDF, ou nom du fichier JSON/CSV. */
  source: string
  reference: string
  statut: 'ok' | 'erreur'
  message: string
  /** Détails riches (uniquement pour l'import PDF). */
  score_fraude?: number | null
  is_fraud?: boolean | null
  seuil_applique?: number | null
  prediction_id?: number | null
  shap?: ShapContribution[] | null
  champ?: string | null
}

/** Un fichier du lot PDF, tel que renvoye par `POST /factures/import`. */
interface ItemImport {
  fichier: string
  statut: 'notee' | 'rejetee' | 'echec'
  reference: string | null
  score_fraude: number | null
  is_fraud: boolean | null
  seuil_applique: number | null
  prediction_id: number | null
  shap: ShapContribution[] | null
  message: string
  champ?: string | null
}

/**
 * Reponse de l'import multipart : le serveur a DEJA traite les 20 fichiers.
 * L'ecran n'a donc aucune boucle de soumission a faire.
 */
interface ResultatImport {
  total: number
  noted: number
  rejected: number
  failed: number
  items: ItemImport[]
}

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
      throw new Error('Le CSV doit contenir un en-tête et au moins une facture.')
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

/**
 * L'import d'un lot de factures.
 *
 * La page reproduit le traitement d'origine : le fichier est analyse ligne
 * par ligne, chaque facture est ensuite deposee separement, et une facture
 * fautive est rejetee sans interrompre les autres. L'import peut etre
 * interrompu entre deux factures.
 */
export function ImportLotPage() {
  // Le meme ecran sert le professionnel (`/professionnel/import-lot`) et
  // l'administrateur (`/administration/import-lot`) : seul le fil d'Ariane
  // et l'aide changent, le traitement est identique.
  const { profile } = useAuth()
  const estAdmin = profile?.role === 'administrateur'

  const [references, setReferences] = useState<References | null>(null)
  const [prestataire, setPrestataire] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)

  const [lotNom, setLotNom] = useState('')
  const [lotTexte, setLotTexte] = useState('')
  const [lotEnCours, setLotEnCours] = useState(false)
  const [lotAnnule, setLotAnnule] = useState(false)
  const [lotTraitees, setLotTraitees] = useState(0)
  const [lotResultats, setLotResultats] = useState<ResultatLot[]>([])

  const [pdfFichiers, setPdfFichiers] = useState<File[]>([])
  const [pdfEnCours, setPdfEnCours] = useState(false)
  const [pdfGlisse, setPdfGlisse] = useState(false)
  const inputPdfRef = useRef<HTMLInputElement | null>(null)

  const [onglet, setOnglet] = useState<'pdf' | 'json'>('pdf')
  const [detail, setDetail] = useState<ResultatLot | null>(null)

  const importEnCours = lotEnCours || pdfEnCours

  useEffect(() => {
    api<References>('/api/core/factures/references')
      .then((valeurs) => {
        setReferences(valeurs)
        // Le prestataire du compte prime (perimetre serveur). Un
        // administrateur, lui, n'en a pas : le champ reste vide, ce qui
        // laisse chaque PDF porter son propre prestataire.
        const propre = valeurs.prestataire_du_compte ?? null
        if (propre !== null) setPrestataire(propre)
      })
      .catch((probleme: unknown) => setErreur(messageErreur(probleme)))
  }, [])

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
    // celui selectionne dans le formulaire : un administrateur, qui n'a pas
    // de perimetre impose, peut ainsi importer un lot sans avoir a recopier
    // le code dans chaque ligne du fichier.
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
    // La colonne « Source » garde le nom du fichier JSON/CSV : dans un bilan
    // qui peut melanger plusieurs origines, une ligne sans source serait
    // impossible a rattacher a un depot.
    const source = lotNom.trim() === '' ? '-' : lotNom
    // Les lignes rejetees a la LECTURE du fichier sont reportees telles
    // quelles : une facture fautive ne doit pas disparaitre du bilan.
    const resultats: ResultatLot[] = analyse.rejetees.map((rejetee) => ({
      ligne: rejetee.ligne,
      source,
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
          source,
          reference: prediction.facture_id,
          statut: 'ok',
          message: `${pourcentage(prediction.score_fraude)} - ${
            prediction.is_fraud ? 'alerte' : 'sous le seuil'
          }`,
        })
      } catch (probleme) {
        resultats.push({
          ligne: entree.ligne,
          source,
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
  }

  /**
   * Selectionne les PDF a envoyer. Le controle est fait ici, avant l'envoi :
   * un refus immediat evite de faire monter 20 fichiers pour rien.
   */
  const validerPdf = (fichiers: File[]) => {
    if (fichiers.length === 0) return
    setErreur(null)
    setSucces(null)
    setLotResultats([])

    const nonPdf = fichiers.filter((fichier) => !fichier.name.toLowerCase().endsWith('.pdf'))
    if (nonPdf.length > 0) {
      setPdfFichiers([])
      setErreur(
        `Fichier(s) non PDF : ${nonPdf.map((fichier) => fichier.name).join(', ')}. ` +
          'Le lot PDF n’accepte que des fichiers .pdf.',
      )
      return
    }
    if (fichiers.length > LIMITE_PDF) {
      setPdfFichiers([])
      setErreur(`Un lot est limité à ${LIMITE_PDF} PDF (${fichiers.length} sélectionnés).`)
      return
    }
    // On dedoublonne par nom + taille : un glisser-deposer par erreur ne
    // doit pas envoyer deux fois le meme fichier.
    const vus = new Set<string>()
    const uniques = fichiers.filter((fichier) => {
      const cle = `${fichier.name}|${fichier.size}|${fichier.lastModified}`
      if (vus.has(cle)) return false
      vus.add(cle)
      return true
    })
    setPdfFichiers(uniques)
  }

  const choisirFichiersPdf = (liste: FileList | null) => {
    if (liste === null) return
    validerPdf(Array.from(liste))
  }

  const ajouterPdf = (liste: FileList | null) => {
    if (liste === null) return
    // Ajout incremental : on garde la selection precedente et on complete,
    // sans depasser la limite.
    const nouveaux = Array.from(liste)
    const restants = LIMITE_PDF - pdfFichiers.length
    if (restants <= 0) {
      setErreur(`Un lot est limité à ${LIMITE_PDF} PDF.`)
      return
    }
    const aAjouter = nouveaux.slice(0, restants)
    validerPdf([...pdfFichiers, ...aAjouter])
  }

  const retirerPdf = (fichier: File) => {
    setPdfFichiers((precedents) =>
      precedents.filter(
        (item) => !(item.name === fichier.name && item.size === fichier.size && item.lastModified === fichier.lastModified),
      ),
    )
  }

  const gererDepotPdf = (evenement: React.DragEvent<HTMLDivElement>) => {
    evenement.preventDefault()
    evenement.stopPropagation()
    setPdfGlisse(false)
    if (importEnCours) return
    const fichiers = evenement.dataTransfer.files
    if (fichiers && fichiers.length > 0) {
      ajouterPdf(fichiers)
    }
  }

  const ouvrirSelecteurPdf = () => {
    if (importEnCours) return
    inputPdfRef.current?.click()
  }

  /**
   * Envoie les PDF en UN SEUL appel multipart.
   *
   * Le serveur traite chaque fichier isolement et renvoie le bilan complet :
   * un PDF illisible produit un `echec` sans interrompre les autres. Le
   * message du serveur (par exemple « PDF sans couche texte : OCR requis »
   * pour un scan) est affiche TEL QUEL dans la colonne « Détail ».
   */
  const importerPdf = async () => {
    setErreur(null)
    setSucces(null)
    setLotResultats([])

    if (pdfFichiers.length === 0) {
      setErreur('Sélectionnez au moins un PDF.')
      return
    }
    if (pdfFichiers.length > LIMITE_PDF) {
      setErreur(`Un lot est limité à ${LIMITE_PDF} PDF (${pdfFichiers.length} sélectionnés).`)
      return
    }

    const form = new FormData()
    for (const fichier of pdfFichiers) form.append('fichiers', fichier)
    // Facultatif : un administrateur peut imposer un prestataire aux
    // factures qui n'en portent pas. Vide = chaque PDF fait foi.
    if (prestataire !== '') form.append('prestataire_id', prestataire)

    setPdfEnCours(true)
    try {
      const resultat = await apiFormData<ResultatImport>('/api/core/factures/import', form)
      const bilan: ResultatLot[] = resultat.items.map((item, index) => ({
        ligne: index + 1,
        source: item.fichier,
        reference: item.reference ?? '-',
        statut: item.statut === 'notee' ? 'ok' : 'erreur',
        message: item.message.trim() === '' ? item.statut : item.message,
        score_fraude: item.score_fraude,
        is_fraud: item.is_fraud,
        seuil_applique: item.seuil_applique,
        prediction_id: item.prediction_id,
        shap: item.shap,
        champ: item.champ,
      }))
      setLotResultats(bilan)
      const refusees = resultat.rejected + resultat.failed
      setSucces(
        `${resultat.noted} importée(s), ${refusees} rejetée(s) sur ${resultat.total}.`,
      )
    } catch (probleme) {
      setErreur(messageErreur(probleme))
    } finally {
      setPdfEnCours(false)
    }
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
      <EnTetePage
        fil={
          estAdmin
            ? [
                { libelle: 'Administration', chemin: '/administration' },
                { libelle: 'Import de lot' },
              ]
            : [
                { libelle: 'Espace professionnel de santé', chemin: '/professionnel' },
                { libelle: 'Import de lot' },
              ]
        }
        titre="Import de lot"
        chapo={
          <>
            Déposez les PDF du jury — une facture par fichier — ou un fichier JSON/CSV :
            chaque facture est vérifiée, notée et enregistrée séparément. Une facture
            invalide est rejetée et listée comme telle, sans interrompre le reste du lot.
          </>
        }
      />

      <Erreur message={erreur} />
      <Succes message={succes} />

      <Carte
        titre="Import de lot"
        actions={
          <button
            type="button"
            className="bouton discret"
            onClick={() => void chargerLotJury()}
            disabled={importEnCours}
          >
            Charger le lot du jury
          </button>
        }
      >
        <p className="aide">
          Trois formats acceptés : PDF (une facture par fichier), JSON ou CSV. Les
          PDF sont envoyés en un seul appel et traités séparément par le serveur ;
          pour le JSON/CSV, chaque ligne est vérifiée et déposée individuellement.
          Une facture invalide est rejetée sans arrêter le reste du lot.
        </p>

        <div className="formulaire">
          {references === null ? (
            <Chargement texte="Chargement des référentiels..." />
          ) : (
            <Champ
              label="Prestataire"
              aide={
                estAdmin
                  ? 'Facultatif : laissé vide, chaque PDF porte son propre prestataire. Sinon, il est imposé aux factures qui n’en portent pas.'
                  : undefined
              }
            >
              <select
                value={prestataire}
                onChange={(event) => setPrestataire(event.target.value)}
                disabled={references.prestataire_du_compte != null}
              >
                {references.prestataire_du_compte == null && (
                  <option value="">— Aucun (lu dans le fichier ou le PDF) —</option>
                )}
                {references.prestataires.map((valeur) => (
                  <option key={valeur.code} value={valeur.code}>
                    {valeur.code} - {valeur.nom}
                  </option>
                ))}
              </select>
            </Champ>
          )}
        </div>

        <div className="onglets-import" role="tablist" aria-label="Mode d'import">
          <button
            type="button"
            role="tab"
            aria-selected={onglet === 'pdf'}
            className={`onglet-import${onglet === 'pdf' ? ' onglet-import--actif' : ''}`}
            onClick={() => setOnglet('pdf')}
          >
            Factures PDF
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={onglet === 'json'}
            className={`onglet-import${onglet === 'json' ? ' onglet-import--actif' : ''}`}
            onClick={() => setOnglet('json')}
          >
            Fichier JSON / CSV
          </button>
        </div>

        {onglet === 'pdf' && (
          <>
            <h3>Factures PDF</h3>
            <div className="formulaire">
              <Champ
                label="Fichiers PDF (une facture par fichier)"
            aide={`1 à ${LIMITE_PDF} fichiers .pdf, sélection multiple, dépôt par glisser-déposer.`}
          >
            <div
              className={`zone-depot${pdfGlisse ? ' zone-depot--actif' : ''}${pdfFichiers.length > 0 ? ' zone-depot--plein' : ''}${importEnCours ? ' zone-depot--disabled' : ''}`}
              role="button"
              tabIndex={importEnCours ? -1 : 0}
              aria-label="Zone de dépôt des factures PDF"
              onDragOver={(evenement) => {
                evenement.preventDefault()
                evenement.stopPropagation()
                if (!importEnCours) setPdfGlisse(true)
              }}
              onDragLeave={(evenement) => {
                evenement.preventDefault()
                evenement.stopPropagation()
                setPdfGlisse(false)
              }}
              onDrop={gererDepotPdf}
              onClick={ouvrirSelecteurPdf}
              onKeyDown={(evenement) => {
                if (evenement.key === 'Enter' || evenement.key === ' ') {
                  evenement.preventDefault()
                  ouvrirSelecteurPdf()
                }
              }}
            >
              <input
                ref={inputPdfRef}
                type="file"
                accept=".pdf,application/pdf"
                multiple
                disabled={importEnCours}
                className="zone-depot__input"
                onChange={(event) => {
                  choisirFichiersPdf(event.target.files)
                  event.target.value = ''
                }}
              />
              <span className="zone-depot__icone" aria-hidden="true">
                {pdfFichiers.length > 0 ? '✓' : '⤓'}
              </span>
              <span className="zone-depot__titre">
                {pdfFichiers.length > 0
                  ? `${pdfFichiers.length} PDF sélectionné(s) sur ${LIMITE_PDF}`
                  : 'Glissez vos factures PDF ici'}
              </span>
              <span className="zone-depot__sous-titre">
                {pdfFichiers.length > 0
                  ? 'Cliquez pour en ajouter d’autres, ou déposez-les par-dessus.'
                  : 'ou cliquez pour parcourir — une facture par fichier, .pdf uniquement.'}
              </span>
            </div>
          </Champ>

          {pdfFichiers.length > 0 && (
            <div className="zone-depot__liste" role="status" aria-live="polite">
              <ul className="zone-depot__puces">
                {pdfFichiers.map((fichier) => (
                  <li
                    key={`${fichier.name}-${fichier.size}-${fichier.lastModified}`}
                    className="zone-depot__puce"
                  >
                    <span className="zone-depot__puce-nom" title={fichier.name}>
                      {fichier.name}
                    </span>
                    <span className="zone-depot__puce-taille">
                      {(fichier.size / 1024).toFixed(0)} Ko
                    </span>
                    <button
                      type="button"
                      className="zone-depot__puce-retirer"
                      onClick={(evenement) => {
                        evenement.stopPropagation()
                        retirerPdf(fichier)
                      }}
                      disabled={importEnCours}
                      aria-label={`Retirer ${fichier.name}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="boutons-ligne">
            <button
              type="button"
              className="bouton principal"
              onClick={() => void importerPdf()}
              disabled={importEnCours || pdfFichiers.length === 0}
            >
              {pdfEnCours ? 'Import des PDF en cours...' : 'Importer les PDF'}
            </button>
            {!pdfEnCours && pdfFichiers.length > 0 && (
              <button
                type="button"
                className="bouton discret"
                onClick={() => setPdfFichiers([])}
              >
                Vider la sélection
              </button>
            )}
          </div>
          {pdfEnCours && (
            <p className="aide" role="status" aria-live="polite">
              Envoi de {pdfFichiers.length} PDF et notation en cours…
            </p>
          )}
        </div>
          </>
        )}

        {onglet === 'json' && (
          <>
            <h3>Fichier JSON ou CSV</h3>
        <div className="formulaire">
          <Champ label="Fichier (.json ou .csv)">
            <input
              type="file"
              accept=".json,.csv,application/json,text/csv"
              disabled={importEnCours}
              onChange={(event) => chargerFichierLot(event.target.files?.[0])}
            />
          </Champ>

          <Champ
            label="Contenu (modifiable)"
            aide="Collez un tableau JSON ou un CSV. Le prestataire sélectionné ci-dessus sert aux lignes qui n’en portent pas."
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
              disabled={importEnCours || lotTexte.trim() === '' || references === null}
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
                disabled={pdfEnCours}
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
          </>
        )}

        {lotEnCours && (
          <p className="aide" role="status" aria-live="polite">
            {lotTraitees} facture(s) traitée(s)…
            {lotAnnule ? ' Annulation demandée.' : ''}
          </p>
        )}

        {lotResultats.length === 0 && !importEnCours && (
          <EtatVide
            titre="Aucun import pour le moment"
            texte="Le bilan de l’import, ligne par ligne, apparaîtra ici après le traitement du lot."
          />
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
                  <th scope="col">Source</th>
                  <th scope="col">Référence</th>
                  <th scope="col">Statut</th>
                  <th scope="col">Détail</th>
                </tr>
              </thead>
              <tbody>
                {lotResultats.map((resultat) => (
                  <tr
                    key={`${resultat.ligne}-${resultat.source}`}
                    className="ligne-cliquable"
                    onClick={() => setDetail(resultat)}
                    tabIndex={0}
                    onKeyDown={(evenement) => {
                      if (evenement.key === 'Enter' || evenement.key === ' ') {
                        evenement.preventDefault()
                        setDetail(resultat)
                      }
                    }}
                  >
                    <td>{resultat.ligne}</td>
                    <td>{resultat.source}</td>
                    <td className="mono">{resultat.reference}</td>
                    <td>
                      <Badge ton={resultat.statut === 'ok' ? 'ok' : 'alerte'}>
                        {resultat.statut === 'ok' ? 'Importée' : 'Rejetée'}
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

      {detail !== null && (
        <div
          className="modale-fond"
          role="dialog"
          aria-modal="true"
          aria-labelledby="detail-titre"
          onClick={() => setDetail(null)}
        >
          <div className="modale" onClick={(evenement) => evenement.stopPropagation()}>
            <div className="modale__entete">
              <h3 id="detail-titre">
                Détail — {detail.source} (ligne {detail.ligne})
              </h3>
              <button
                type="button"
                className="bouton discret"
                onClick={() => setDetail(null)}
                aria-label="Fermer"
              >
                ×
              </button>
            </div>

            <div className="modale__corps">
              <dl className="liste-definitions">
                <div>
                  <dt>Référence</dt>
                  <dd className="mono">{detail.reference ?? '-'}</dd>
                </div>
                <div>
                  <dt>Statut</dt>
                  <dd>
                    <Badge ton={detail.statut === 'ok' ? 'ok' : 'alerte'}>
                      {detail.statut === 'ok' ? 'Importée' : 'Rejetée'}
                    </Badge>
                  </dd>
                </div>
                {detail.score_fraude != null && (
                  <div>
                    <dt>Score de fraude</dt>
                    <dd>
                      {pourcentage(detail.score_fraude)} —{' '}
                      {detail.is_fraud ? 'au-dessus du seuil (alerte)' : 'sous le seuil'}
                    </dd>
                  </div>
                )}
                {detail.seuil_applique != null && (
                  <div>
                    <dt>Seuil appliqué</dt>
                    <dd>{pourcentage(detail.seuil_applique)}</dd>
                  </div>
                )}
                {detail.prediction_id != null && (
                  <div>
                    <dt>Prédiction</dt>
                    <dd className="mono">#{detail.prediction_id}</dd>
                  </div>
                )}
                {detail.champ && (
                  <div>
                    <dt>Champ fautif</dt>
                    <dd className="mono">{detail.champ}</dd>
                  </div>
                )}
                <div>
                  <dt>Détail</dt>
                  <dd>{detail.message}</dd>
                </div>
              </dl>

              {detail.shap && detail.shap.length > 0 && (
                <div className="modale__shap">
                  <h4>Explication (SHAP) — top contributions</h4>
                  <ShapList contributions={detail.shap} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
