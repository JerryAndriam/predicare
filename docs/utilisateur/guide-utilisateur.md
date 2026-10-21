# Guide utilisateur

**PrediCare — plateforme de tiers payant santé**
Nom affiché dans l’interface : **KolikolyCare**

| | |
| --- | --- |
| Version | 1.0 |
| Date | Octobre 2026 |
| Public | Assurés, professionnels de santé, gestionnaires, administrateurs |
| Objet | Utiliser la plateforme au quotidien, écran par écran |
| Périmètre | Interface web uniquement (l’installation et l’exploitation serveur sont traitées dans le guide de démarrage) |

Ce guide est organisé **en une section par rôle**. Lisez d’abord la prise en main commune, puis la section qui correspond à votre compte.

## Sommaire

1. Prise en main commune
2. Assuré
3. Professionnel de santé
4. Gestionnaire
5. Administrateur
6. Parcours complet d’une facture
7. Glossaire
8. Aide et contacts

---

## 1. Prise en main commune

### 1.1 Se connecter

1. Ouvrez l’adresse communiquée par votre administrateur (en local : `http://localhost:8080`).
2. Saisissez votre **adresse e-mail** et votre **mot de passe**.
3. Cliquez sur **Se connecter**.

Vous arrivez directement sur l’accueil de votre espace. La plateforme vous oriente selon votre rôle : il n’y a pas de menu « choisir mon rôle ».

> **Votre compte est nominatif.** Il est créé par l’administrateur, rattaché à un dossier assuré ou à un prestataire, et ne doit jamais être partagé.

**Si la connexion échoue :**

| Message | Ce qu’il faut faire |
| --- | --- |
| « Identifiants invalides. » | Vérifiez l’adresse e-mail et le mot de passe. Si le problème persiste, le compte est peut-être désactivé : contactez l’administrateur (le message reste le même pour ne pas révéler l’existence d’un compte). |
| Session expirée (retour à la connexion) | Reconnectez-vous : la session se termine après une période d’inactivité. |

### 1.2 Se repérer dans l’interface

- **La barre latérale** liste les pages de votre espace. Elle est propre à votre rôle.
- **Le bandeau supérieur** rappelle votre espace et la page courante.
- **Le bouton de repli** (à gauche du bandeau) réduit la barre latérale aux icônes. Sur petit écran, un bouton ouvre un tiroir de navigation.
- **Le menu du profil** (vos initiales, en haut à droite) donne accès à :
  - **Mon compte** → **Profil** ou **Mot de passe** ;
  - **Aide** → **Questions fréquentes**, **Procédures**, **Centre d’aide** ;
  - **Se déconnecter**.

Le centre d’aide est **adapté à votre rôle** : les procédures affichées sont celles que vous pouvez réellement exécuter.

### 1.3 Changer son mot de passe

1. Menu du profil → **Mon compte** → **Mot de passe**.
2. Saisissez votre **mot de passe actuel**, puis le **nouveau** et sa **confirmation**.
3. Cliquez sur **Changer le mot de passe**.

Le nouveau mot de passe doit contenir **au moins 12 caractères**. Un message confirme le changement ; il sera demandé à la prochaine connexion.

| Message | Ce qu’il signifie |
| --- | --- |
| « Le nouveau mot de passe doit contenir au moins 12 caractères. » | Allongez le mot de passe. Une phrase longue et unique fait très bien l’affaire. |
| « La confirmation ne correspond pas au nouveau mot de passe. » | Les deux saisies diffèrent. Recommencez. |
| « Ancien mot de passe incorrect. » | Le mot de passe actuel saisi n’est pas le bon. Recommencez. |

### 1.4 Se déconnecter

Menu du profil → **Se déconnecter**. Faites-le systématiquement sur un poste partagé : les données affichées sont confidentielles.

### 1.5 Règles communes à tous les rôles

- **Les montants sont exprimés en ariary (MGA)** et affichés au format français.
- **Chaque action sensible est tracée** : décision, changement de seuil, changement de modèle, gestion de compte, demande de droits.
- **Les données de santé sont confidentielles.** Ne prenez pas de capture d’écran contenant un dossier, ne transférez pas un identifiant de dossier par un canal non maîtrisé.
- **L’interface ne permet jamais d’écrire dans les référentiels** (assurés, prestataires, actes, contrats) : ils viennent de la base et sont contrôlés par le serveur.

---

## 2. Assuré

Votre espace sert à **consulter vos remboursements** et à **poser une question sur vos garanties**. Vous n’avez aucune facture à déposer : ce sont vos professionnels de santé qui le font.

### 2.1 Votre espace en un coup d’œil

| Page | Ce que vous y faites |
| --- | --- |
| **Accueil** | Voir l’essentiel de votre dossier et les deux actions possibles |
| **Mes remboursements** | Consulter chaque facture, le montant pris en charge et l’état du contrôle |
| **Assistant garanties** | Poser une question sur votre contrat, en langage courant |

### 2.2 Accueil

Trois indicateurs résument votre dossier :

| Indicateur | Ce qu’il compte |
| --- | --- |
| **Factures dans votre dossier** | Le nombre de factures déposées par vos professionnels de santé |
| **Montant repris en charge** | La somme des montants remboursés |
| **Dossiers en vérification** | Les factures pour lesquelles un contrôle est en cours |

La page rappelle ensuite les trois étapes d’un remboursement : le dépôt par le professionnel, l’examen de la facture, puis la décision. **Vous n’avez rien à faire** : le suivi est automatique.

### 2.3 Mes remboursements

Le tableau présente, pour chaque facture :

| Colonne | Lecture |
| --- | --- |
| **Date** | La date de la facture |
| **Prestataire** | Le code du professionnel qui a déposé la facture |
| **Facture** | Le montant total facturé |
| **Pris en charge** | La part remboursée (un tiret tant que le montant n’est pas connu) |
| **Reste à charge** | La part qui reste à votre charge |
| **Statut** | L’état du dossier (voir ci-dessous) |
| **Contrôle** | Le résultat du contrôle anti-fraude |

**Les statuts :**

| Statut affiché | Signification |
| --- | --- |
| **Reçue** | La facture est enregistrée, en attente de traitement |
| **En cours** | L’instruction est en cours |
| **Payée** | Le remboursement a été effectué |
| **Rejetée** | La facture a été refusée |
| **Fraude confirmée** | Le contrôle a établi une fraude |
| **Pièce demandée** | Une pièce justificative est attendue |

**Les badges de contrôle :**

| Badge | Signification |
| --- | --- |
| **Clair** | La facture n’a pas été signalée |
| **En vérification** | Un contrôle est en cours ; aucune conclusion n’est tirée |
| **Non contrôlé** | Aucune notation n’est disponible pour cette facture |
| **Pièce demandée** | Un justificatif est nécessaire |
| **Rejetée** / **Fraude confirmée** | Le dossier a été refusé ou la fraude établie |

La liste est paginée par 50 factures. Utilisez les boutons de pagination en bas du tableau pour parcourir l’ensemble de votre dossier.

> **Un tiret dans « Pris en charge » n’est pas une erreur** : le montant n’est renseigné qu’une fois le dossier traité.

### 2.4 Assistant garanties

L’assistant répond à vos questions sur **votre** contrat et **votre** dossier, en français, de façon concise.

**Poser une question :**

1. Ouvrez **Assistant garanties**.
2. Saisissez votre question dans le champ **« Posez votre question… »** (1 000 caractères maximum).
3. Appuyez sur **Entrée** ou cliquez sur **Envoyer**.

Vous pouvez enchaîner les questions : l’assistant garde le fil de la conversation **pendant une heure**. Pour repartir de zéro, cliquez sur **Nouvelle conversation**.

**Exemples de questions :**

- « Quel est le taux de remboursement d’une consultation en formule PREMIUM ? »
- « Le plafond annuel de l’optique est-il atteint si j’achète deux montures ? »
- « Combien ai-je été remboursé au total sur mes factures payées ? »
- « Quelle est ma dernière facture, et est-elle payée ? »
- « Et pour l’optique ? » (question de suivi, dans la même conversation)

**Comment lire une réponse :**

- La réponse cite **le contrat, l’article, la garantie et l’extrait** sur lesquels elle s’appuie. Vérifiez la citation : c’est elle qui fonde la réponse.
- Le score de pertinence indique la qualité de la correspondance avec vos documents.
- Les **détails techniques** (latence, tokens, coût, cache) sont repliés sous la réponse.
- Le badge **Réponse dégradée** signale que l’assistant fonctionne en mode réduit : la réponse est donnée sans rédaction complète. Le badge **Extraits de contrat, sans rédaction** signale une réponse composée uniquement d’extraits.

**Ce que l’assistant refuse :**

| Demande | Pourquoi |
| --- | --- |
| Modifier ses instructions, afficher son prompt | Protection contre les manipulations |
| Consulter le dossier d’un autre assuré | Le filtre est posé par le serveur |
| Modifier ou supprimer une donnée | L’assistant est en lecture seule |
| Une question hors de vos documents | Il répond qu’il n’a pas l’information et vous invite à contacter votre gestionnaire |

L’assistant **n’invente jamais** un montant, une date ou un taux. S’il n’a pas la source, il le dit.

### 2.5 Ce que vous ne pouvez pas faire

- Déposer une facture : c’est le rôle du professionnel de santé.
- Modifier un montant, un statut ou une pièce.
- Accéder au dossier d’un autre assuré.

### 2.6 En cas de problème

| Situation | Que faire |
| --- | --- |
| Une facture n’apparaît pas | Elle n’a peut-être pas encore été déposée. Demandez au professionnel, puis rechargez la page. |
| Le montant pris en charge est vide | Le dossier n’est pas encore traité. Le statut indique où il en est. |
| Une facture est « Rejetée » | Contactez votre gestionnaire : le motif du rejet est dans le dossier. |
| L’assistant ne répond pas | Réessayez plus tard ; si le badge « Réponse dégradée » apparaît, le service fonctionne en mode réduit. |

---

## 3. Professionnel de santé

Votre espace sert à **déposer des factures et des ordonnances**, et à **suivre vos dossiers**.

### 3.1 Votre espace en un coup d’œil

| Page | Ce que vous y faites |
| --- | --- |
| **Accueil** | Voir vos volumes et les quatre gestes du quotidien |
| **Déposer une facture** | Saisir une facture ligne par ligne ; elle est vérifiée, notée et expliquée |
| **Importer un lot** | Déposer un fichier de plusieurs factures en une fois |
| **Suivi des dossiers** | Suivre l’état de chaque dossier déposé |
| **Déposer une ordonnance** | Rapprocher une prescription des lignes facturées |

> Votre compte est rattaché à **un** prestataire. Le prestataire est repris automatiquement dans les formulaires : vous ne pouvez pas déposer pour un autre établissement.

### 3.2 Déposer une facture

1. Ouvrez **Déposer une facture**.
2. Choisissez le **dossier de l’assuré** dans la liste.
3. Vérifiez le **prestataire** (imposé par votre compte).
4. Renseignez la **date de la facture**.
5. Ajoutez les **lignes** :
   - **code d’acte** (choisi dans le référentiel ; le prix unitaire se remplit automatiquement),
   - **quantité** (1 à 999),
   - **prix unitaire**,
   - **date de l’acte**.
6. Vérifiez le **montant total calculé**, puis cliquez sur **Envoyer et noter la facture**.

**Les règles contrôlées avant l’envoi :**

| Règle | Message si elle n’est pas respectée |
| --- | --- |
| Un assuré doit être choisi | « Choisissez un assuré. » |
| Un prestataire doit être choisi | « Choisissez un prestataire. » |
| Au moins une ligne | « Ajoutez au moins une ligne de facture. » |
| Chaque ligne porte un acte | « Chaque ligne doit référencer un acte. » |
| Total ≤ 10 000 000 Ar | « Le montant total dépasse le plafond accepté (10 000 000). » |

Le serveur rejoue ces contrôles **avant d’écrire quoi que ce soit** : une facture refusée ne crée aucun dossier.

**Après l’envoi**, la carte « Résultat de la notation » affiche :

| Élément | Signification |
| --- | --- |
| **Note de vigilance** | La probabilité que la facture soit anormale, de 0 à 100 % |
| **Badge « Au-dessus du seuil - alerte »** | La facture entre dans la file du gestionnaire |
| **Badge « Sous le seuil »** | La facture suit le circuit normal |
| **Seuil** | La valeur appliquée au moment de la notation |
| **Notification** | Indique si l’alerte a été transmise, ou pourquoi elle ne l’a pas été |
| **Ce qui a pesé dans la note** | Les facteurs qui ont fait monter ou baisser la note |

**Motifs de refus fréquents :**

| Message | Ce qu’il faut corriger |
| --- | --- |
| `lignes.0.code_acte : valeur inconnue` | Choisissez un acte dans la liste |
| `lignes.0.quantite` | La quantité doit être au moins 1 |
| `lignes.0.date_acte` | La date de l’acte est absente ou illisible |
| `assure_pseudonyme : valeur inconnue` | Le dossier sélectionné n’existe pas |
| `montant_total` hors bornes | Le total dépasse 10 000 000 Ar |

### 3.3 Importer un lot

1. Ouvrez **Importer un lot**.
2. Choisissez le **fichier** (`.json` ou `.csv`) ou collez son contenu dans la zone **« Contenu (modifiable) »**.
3. Vérifiez le prestataire, puis cliquez sur **Importer le lot**.

Le fichier attendu :

- **JSON** : un tableau de factures, avec `assure_pseudonyme`, `date_facture`, `lignes` (chaque ligne contient `code_acte`, `quantite`, `montant_unitaire`, `date_acte`) ;
- **CSV** : les colonnes `assure_pseudonyme, date_facture, code_acte, quantite, montant_unitaire, date_acte`.

Pendant l’import :

- la progression s’affiche (« X facture(s) traitée(s)… ») ;
- le bouton **Annuler l’import** arrête le traitement après la facture en cours ;
- **chaque facture est traitée séparément** : une ligne invalide est rejetée et listée, sans interrompre le reste du lot ;
- le bilan final donne, ligne par ligne, la référence obtenue ou le motif du rejet.

Le bouton **Charger le lot du jury** prépare un jeu de démonstration. Le bouton **Vider** efface le contenu et le bilan affiché.

### 3.4 Déposer une ordonnance

1. Ouvrez **Déposer une ordonnance**.
2. Choisissez le **dossier**, le **prestataire** et l’**acte prescrit**.
3. Renseignez la **date**, la **quantité** et la **validité en jours**.
4. Facultatif : une **référence** (générée automatiquement si vide) et un **diagnostic**.
5. Cliquez sur **Enregistrer l’ordonnance**.

L’ordonnance est rapprochée des lignes de la facture : le gestionnaire voit si chaque acte était **prescrit** ou **non prescrit**. Un **doublon** (même assure, même acte, même jour) est refusé : le message cite l’ordonnance existante. Une ordonnance ne se modifie pas depuis l’interface ; en cas d’erreur, signalez-la au gestionnaire.

### 3.5 Suivi des dossiers

Le tableau affiche **Date**, **Assuré**, **Prestataire**, **Montant**, **Score** et **Statut**. Il est paginé par 100 dossiers.

Le filtre **Statut** s’applique côté serveur : **Tous les statuts**, Reçue, En cours, Payée, Rejetée, Fraude confirmée, Pièce demandée.

### 3.6 Bonnes pratiques

- Déposez la facture **dès le soin réalisé** : le délai de traitement se compte à partir du dépôt.
- Vérifiez la **date de l’acte** : une date incohérente avec la facture fait monter la note de vigilance.
- Déposez l’**ordonnance avant** la facture : un acte facturé sans prescription est un signal fort pour le contrôle.
- En cas de rejet, corrigez **le champ nommé** et renvoyez : rien n’a été enregistré.

---

## 4. Gestionnaire

Votre espace sert à **traiter les alertes** : les factures dont la note de vigilance dépasse le seuil.

### 4.1 La file d’alertes

L’écran **File d’alertes** présente quatre indicateurs :

| Indicateur | Ce qu’il mesure |
| --- | --- |
| **À traiter** | Le nombre d’alertes en attente |
| **Score maximum** | La note la plus élevée de la file |
| **Montant en jeu** | La somme des montants concernés |
| **Âge moyen** | L’ancienneté moyenne des alertes, en minutes |

La file est **triée de la plus suspecte à la moins suspecte**. Chaque ligne montre la note, le montant, le dossier assuré et la date ; au-delà d’une heure d’attente, une mention « X h en file » apparaît.

**Filtrer :** renseignez un **identifiant d’assuré**, un **montant minimum** ou **maximum**, un **score minimum**, puis cliquez sur **Appliquer**. **Réinitialiser** vide les filtres.

La liste est paginée par 20 alertes. Le bouton **Rafraîchir** recharge la page courante.

### 4.2 Ouvrir et lire une alerte

Cliquez sur une alerte : le panneau **Détail et décision** affiche :

- la **note de vigilance**, le seuil appliqué et l’identité du dossier ;
- les **lignes de la facture** : acte, quantité, prix unitaire, total, et la colonne **Ordonnance** (« Prescrite » ou « Non prescrite ») ;
- **Ce qui a pesé dans la note** : les facteurs positifs et négatifs, avec leur poids.

> Une contribution **positive** pousse vers la fraude ; une contribution **négative** joue en faveur de la légitimité. Les deux comptent : une facture peut avoir une note élevée pour une seule anomalie.

### 4.3 Décider

1. Choisissez la **Décision** :

| Décision | Effet sur le dossier |
| --- | --- |
| **Confirmer la fraude** | Le dossier passe en **Fraude confirmée** |
| **Rejeter l’alerte (faux positif)** | Le dossier passe en **Rejetée** |
| **Demander une pièce justificative** | Le dossier passe en **Pièce demandée** |

2. Rédigez le **Motif de la décision** (obligatoire, 3 caractères minimum, 2 000 maximum). Écrivez ce que vous avez constaté, pas ce que vous supposez : le motif est lu lors d’un contrôle et conservé dans le journal.
3. Cliquez sur **Enregistrer la décision**.

Confirmer une fraude demande une **confirmation explicite** : la décision engage le dossier et reste tracée avec votre identité et l’heure.

> Le changement de statut est **immédiatement visible par l’assuré** dans « Mes remboursements ».

**Messages à connaître :**

| Message | Ce qu’il faut faire |
| --- | --- |
| « Le commentaire est obligatoire (au moins 3 caractères). » | Renseignez le motif avant d’enregistrer |
| « Confirmer la fraude ? … » | Validez la confirmation, ou annulez et changez de décision |

### 4.4 Historique

La page **Historique** liste les décisions déjà prises : **Date**, **Alerte**, **Décision**, **Score**, **Motif**, **Décideur**. Le bouton **Exporter en CSV** exporte la page affichée, pour que le fichier corresponde exactement à ce que vous voyez.

### 4.5 Pilotage BI

Le lien **Pilotage BI** (sous la barre latérale) ouvre le tableau de bord décisionnel en lecture seule : volume de factures, fraude détectée, cycle de décision, meilleurs prestataires. Il ne permet aucune modification des dossiers.

Si le tableau ne s’affiche pas, l’écran indique que le service de pilotage n’est pas démarré et propose **Ouvrir le tableau de bord** dans un onglet. En local, le démarrage se fait avec `make up-bi` ; prévenez l’administrateur si le problème persiste.

### 4.6 Bonnes pratiques

- **Lisez les lignes avant la note.** Une note élevée peut venir d’un seul acte non prescrit.
- **Ne confirmez jamais une fraude sans motif factuel.** En cas de doute, demandez une pièce : c’est réversible, une fraude confirmée ne l’est pas.
- **Traitez les alertes les plus anciennes** : l’âge moyen de la file est un indicateur de qualité de service.
- Si la file est vide alors que vous attendez des alertes, vérifiez le **seuil** avec l’administrateur.

---

## 5. Administrateur

Votre espace regroupe les réglages de la plateforme. Chaque réglage est conservé avec son auteur, sa date et son motif.

### 5.1 Vue d’ensemble

La page d’accueil affiche votre rôle, la **version du modèle en service** et le **seuil de déclenchement**, puis donne accès aux neuf sections de l’espace et au **Pilotage BI**.

### 5.2 Seuil d’alerte

1. Ouvrez **Seuil d’alerte**.
2. Saisissez le **seuil** (entre 0 et 1).
3. Renseignez le **motif du changement** (obligatoire).
4. Cliquez sur **Appliquer le seuil**.

Le seuil s’applique **immédiatement**, sans redémarrage. Un seuil bas augmente le rappel et le nombre d’alertes à traiter ; un seuil haut réduit la charge mais laisse passer davantage de dossiers.

> Ne confondez pas le **seuil de détection** (ce qui entre dans la file du gestionnaire) avec le **seuil de notification** (ce qui déclenche un message sur un canal). Le premier se règle ici ; le second est réglé côté serveur, dans l’environnement du service de notification (`SEUIL_NOTIFICATION_SLACK`).

### 5.3 Modèle

La page présente le **registre** : version **active**, version **candidate**, seuil et date de chargement.

| Action | Effet |
| --- | --- |
| **Charger la candidate** | Prépare une version à côté de la version active, qui continue de répondre |
| **Basculer sur la candidate** | La candidate devient la version active |
| **Revenir à cette version** | Réactive une version disponible |

Aucune version n’est perdue ; chaque bascule est journalisée. La carte **Re-contrôler un stock de factures** relance la notation de l’historique ou des nouvelles factures ; les notes historiques ne nourrissent pas la file du gestionnaire.

### 5.4 Santé

L’écran **Santé** vérifie, au moment de l’ouverture :

- le **traitement des factures** (dépôt, contrôle, notation) ;
- l’**assistant garanties** et le nombre de documents disponibles ;
- le **seuil** en vigueur.

Un service indisponible est signalé par un badge. La date de vérification est affichée sous les sondes.

### 5.5 Canaux

Le tableau liste les canaux de notification avec deux états distincts :

| Colonne | Signification |
| --- | --- |
| **Configuré** | Le canal possède une destination |
| **Actif** | Le canal est autorisé à envoyer |

Un canal **actif mais non configuré n’envoie rien**. Pour chaque canal :

1. renseignez le **destinataire** ;
2. cochez ou décochez **Actif** ;
3. cliquez sur **Enregistrer** ;
4. cliquez sur **Tester** pour envoyer un message d’essai : le résultat indique précisément ce qui s’est passé.

> Les secrets (clés, jetons) ne s’écrivent pas depuis cet écran : ils vivent dans l’environnement du serveur. Un canal sans secret reste non configuré.

### 5.6 Observabilité

Choisissez la **période** (24 heures, 7, 30 ou 90 jours). L’écran affiche :

- le **volume traité par jour** (barres pleines) et la part des factures ayant déclenché une alerte ;
- le **volume** (factures enregistrées, alertes) ;
- l’**activité** (factures notées, décisions gestionnaire) ;
- les **erreurs** ;
- les **temps de réponse** P50, P95 et P99.

Les badges indiquent si les données de la base, la notation et l’assistant sont disponibles.

### 5.7 Comptes

La liste présente **E-mail**, **Rôle**, **Nom**, **Dossier**, **Prestataire**, **État**, **Dernière connexion**.

**Créer un compte :**

1. Saisissez l’**adresse e-mail** et un **mot de passe** d’au moins 12 caractères.
2. Choisissez le **rôle**.
3. Renseignez le **nom affiché** (facultatif).
4. Selon le rôle :
   - **assuré** : choisissez le **dossier assuré** (obligatoire) ;
   - **professionnel de santé** : saisissez le **code prestataire** (obligatoire).
5. Cliquez sur **Créer le compte**.

**Désactiver un compte :** bouton **Désactiver** sur la ligne. La désactivation bloque la prochaine connexion ; une session déjà ouverte se termine à son échéance. Vous ne pouvez pas désactiver votre propre compte.

### 5.8 Journal des actions

Le journal enregistre les actions sensibles : connexion, décision du gestionnaire, changement de seuil, gestion de compte, demande de droits.

- Filtrez par **Action**, **Acteur** ou **Cible**, puis **Appliquer**.
- **Réinitialiser** vide les filtres.
- **Exporter en CSV** exporte l’affichage courant.

Les colonnes sont **Date**, **Acteur**, **Rôle**, **Action**, **Cible**, **Détails**.

### 5.9 Droits des personnes (RGPD)

Saisissez la **référence du dossier** (le pseudonyme affiché dans l’historique de l’assuré), puis choisissez l’opération :

| Bouton | Effet |
| --- | --- |
| **Exporter** | Télécharge le dossier en JSON, identité en clair : c’est le droit d’accès |
| **Rectifier** | Enregistre une rectification d’identité sur le dossier |
| **Opposer** | Marque l’opposition : le traitement du dossier s’arrête, rien n’est effacé |
| **Effacer** | Supprime les données métier après confirmation ; une trace anonyme de l’opération est conservée |

> **L’effacement est irréversible.** Vérifiez la référence du dossier et lisez la confirmation avant de valider.

### 5.10 Pilotage BI

Le menu **Pilotage BI** ouvre le tableau de bord décisionnel dans la page, en lecture seule : volume de factures, fraude détectée, cycle de décision, meilleurs prestataires.

- Si le service n’est pas démarré, l’écran l’explique et propose **Ouvrir le tableau de bord** dans un onglet.
- En local, le démarrage se fait avec `make up-bi`.
- Le tableau Superset possède **son propre compte**, distinct de votre compte plateforme : au premier accès, un formulaire de connexion peut s’afficher dans le cadre. Utilisez le compte Superset remis par l’exploitant.
- Le bouton **Ouvrir dans un onglet** affiche le tableau en plein écran.

### 5.11 Bonnes pratiques

- **Changez le seuil avec un motif** : c’est ce motif qui explique la décision six mois plus tard.
- **Testez un canal avant de l’activer** : le bouton Tester dit ce qui s’est réellement passé.
- **Ne créez pas de compte générique** : chaque action est tracée à un compte nominatif.
- **Traitez les demandes de droits depuis cet écran uniquement** : l’opération est journalisée.

---

## 6. Parcours complet d’une facture

```
Professionnel de santé                 Plateforme                     Gestionnaire
─────────────────────                  ──────────                     ────────────
Dépose la facture  ───────────────▶  Contrôle des références
(+ ordonnance)                        Notation (note de vigilance)
                                      └─ sous le seuil ─▶ circuit normal
                                      └─ au-dessus ────▶ file d’alertes ─▶ lit le dossier
                                                                           ├─ Confirme la fraude
                                                                           ├─ Rejette (faux positif)
                                                                           └─ Demande une pièce
                                                                                  │
Assuré ◀────────────── « Mes remboursements » : statut, montant pris en charge, reste à charge
```

À chaque étape, l’action est tracée. Le statut visible par l’assuré change dès la décision du gestionnaire.

---

## 7. Glossaire

| Terme | Définition |
| --- | --- |
| **Acte** | Une prestation de soins codée (consultation, examen, acte technique) |
| **Assuré** | La personne couverte ; son dossier est identifié par un pseudonyme (`assr_…`) |
| **Prestataire** | Le professionnel ou l’établissement qui dépose la facture |
| **Note de vigilance** | La probabilité qu’une facture soit anormale, entre 0 et 100 % |
| **Seuil** | La note au-delà de laquelle une facture entre dans la file du gestionnaire |
| **SHAP** | La décomposition de la note en facteurs, qui explique la décision |
| **Prescription** | L’ordonnance ; un acte absent de l’ordonnance est « non prescrit » |
| **Prise en charge** | La part du soin remboursée par l’assurance |
| **Reste à charge** | La part du soin qui reste à la charge de l’assuré |
| **Pseudonyme** | L’identifiant de dossier affiché à la place du nom (`assr_…`) |

---

## 8. Aide et contacts

- **Centre d’aide intégré** : menu du profil → **Aide** → **Questions fréquentes** ou **Procédures**. Le contenu s’adapte à votre rôle.
- **Assistance** : contactez votre administrateur pour un problème de compte, de droit d’accès ou de données.
- **Incident de sécurité** : signalez immédiatement tout accès ou affichage qui ne correspond pas à votre périmètre.

| Version | Date | Évolution |
| --- | --- | --- |
| 1.0 | Octobre 2026 | Première version complète, une section par rôle |
