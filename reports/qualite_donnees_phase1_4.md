# Rapport qualite des donnees — Phase 1.4

Source : `data/raw`

## 1. Volume

| domaine | lignes | colonnes |
|---|---:|---:|
| actes | 58 | 12 |
| medicaments | 28 | 6 |
| prestataires | 251 | 20 |
| assures | 4459 | 9 |
| identites | 4459 | 10 |
| contrats | 1500 | 12 |
| garanties | 27 | 11 |
| grille | 3242 | 3 |
| ordonnances | 47804 | 8 |
| ordonnance_lignes | 82175 | 6 |
| factures | 84593 | 24 |
| lignes_facture | 123270 | 9 |
| labels_fraude | 84593 | 6 |
| labels_prestataires | 251 | 2 |

## 2. Valeurs manquantes non normales (a examiner)

| colonne | vides | % |
|---|---:|---:|
| (aucune) | | |

## 3. Doublons

| domaine | cle | doublons exacts | doublons de cle |
|---|---|---:|---:|
| actes | code_acte | 0 | 0 |
| medicaments | code_medicament | 0 | 0 |
| prestataires | prestataire_id | 0 | 0 |
| assures | assure_id | 0 | 0 |
| identites | assure_id | 0 | 0 |
| contrats | numero_police | 0 | 1288 |
| garanties | formule + categorie | 0 | 0 |
| grille | prestataire_id + code | 0 | 0 |
| ordonnances | ordonnance_id | 0 | 0 |
| ordonnance_lignes | ordonnance_id + num_ligne | 0 | 0 |
| factures | numero_facture | 0 | 553 |
| lignes_facture | facture_id + num_ligne | 0 | 0 |
| labels_fraude | facture_id | 0 | 0 |
| labels_prestataires | prestataire_id | 0 | 0 |

**Lecture (ne pas supprimer) :**
- `contrats.numero_police` : ce n'est PAS un doublon. Une police de GROUPE (contrat collectif) couvre plusieurs contrats individuels ; le numero est volontairement partage.
- `factures.numero_facture` : double soumission de la MEME facture. C'est le signal de la fraude DOUBLON : la supprimer effacerait la fraude a detecter.
- Les doublons EXACTS (toutes colonnes identiques) sont nuls partout : le fichier ne contient aucune ligne dupliquee par erreur.

## 4. Signaux de dates (a CONSERVER, pas des erreurs)

| signal | cas |
|---|---:|
| soin avant l'effet du contrat (HORS_COUVERTURE) | 134 |
| soin apres la fin du contrat (HORS_COUVERTURE) | 52 |
| soin apres la fin de convention (PRESTATAIRE_RADIE) | 157 |
| soin avant le conventionnement (PRESTATAIRE_RADIE) | 17 |
| facture d'un prestataire RADIE | 3063 |

## 5. Factures invalides (rejet deterministe)

- factures valides : 84593
- factures rejetees : 0

Interpretation : le jeu de l'encadrement est sain — aucun cas des 10 regles d'invalidite. Le controleur est neanmoins operationnel : il ecartera automatiquement toute facture invalide soumise plus tard (les 20 factures fraiches du jury).
