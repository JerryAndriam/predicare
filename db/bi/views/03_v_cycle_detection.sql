-- ============================================================================
-- Couche de pilotage decisionnel (CDC, Flux 3)
-- ----------------------------------------------------------------------------
-- Le CDC exige cinq indicateurs : volumes, montants economises, taux de
-- detection, delai de traitement, taux de faux positifs.
--
-- Les trois premieres vues (01 et 02) les calculent sur ce que le jeu
-- contient reellement : le volume, le delai et la prevalence de la fraude
-- sortent de `core.facture` et `ml.label_fraude`.
--
-- Ce fichier mesure la BOUCLE DE DECISION en direct : alertes en attente,
-- montants exposes, decisions, montants confirmes et delai. Il lit
-- `ml.prediction` et `audit.decision_gestionnaire`.
--
-- Les deux ratios de performance du modele (rappel et faux positifs) sont
-- dans `04_v_modele_performance.sql`. Ils viennent des metriques de TEST du
-- modele promu, pas d'un rejeu in-sample de tout l'historique.
--
-- Les tuiles restent presentes meme vides : une brique vide avec son etat
-- (« en attente ») se discute ; une brique absente se confond avec un oubli.
--
-- ---------------------------------------------------------------------------
-- Le probleme de securite, et sa solution
-- ---------------------------------------------------------------------------
-- La migration 0002 retire a `superset_ro` tout acces au schema `audit` :
-- « le tableau de bord doit pouvoir mesurer la performance, pas consulter qui
-- a fait quoi ». Les anciens datasets violaient cette regle et echouaient
-- avec « permission denied for schema audit ».
--
-- Ces vues sont donc creees `security_invoker = false`, c'est-a-dire avec
-- droits s'executent avec les privileges du proprietaire, et non avec ceux du
-- lecteur. `superset_ro` peut ainsi lire l'AGREGAT sans jamais pouvoir lire
-- `audit`.
--
-- Ce que cela expose, et ce que cela n'expose pas :
--
--   expose    : un nombre de dossiers et un montant, par mois et par verdict
--   n'expose  : quel gestionnaire, quel assure, quelle facture individuelle
--
-- Aucune colonne nominative n'est projetee. `decided_by` n'apparait dans
-- aucune vue, volontairement. C'est la condition qui rend cette construction
-- acceptable : elle mesure une performance collective, elle ne permet pas de
-- surveiller une personne.
--
-- Si un jour le besoin devient « qui a tranche quoi », la regle doit etre
-- revisee explicitement, pas contournee en supprimant le SECURITY DEFINER.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Taux de detection : volume de predictions et taux d'alerte, par mois
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW bi.v_detection_mensuel AS
SELECT
    date_trunc('month', p.created_at)::date                    AS mois,
    COUNT(*)                                                   AS nb_predictions,
    COUNT(*) FILTER (WHERE p.is_fraud)                         AS nb_alertes,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.is_fraud)
          / NULLIF(COUNT(*), 0), 2)                            AS taux_alerte_pct,
    -- AVG() sur un `double precision` rend un `float8`, et PostgreSQL
    -- n'a pas de ROUND(float8, integer) : le cast en numeric est
    -- necessaire et explicite.
    ROUND(AVG(p.score_fraude)::numeric, 4)                    AS score_moyen
FROM ml.prediction p
GROUP BY 1;

COMMENT ON VIEW bi.v_detection_mensuel IS
    'Volume de predictions du modele et taux d alerte, par mois. Source ml.prediction. Frequence : continue. VIDE tant qu aucun modele n a ete execute.';


-- ----------------------------------------------------------------------------
-- Delai de traitement mesure sur la boucle reelle : prediction -> decision
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW bi.v_delai_decision AS
SELECT
    date_trunc('month', p.created_at)::date                    AS mois,
    COUNT(*)                                                   AS nb_dossiers_decides,
    ROUND(AVG(EXTRACT(EPOCH FROM (p.decided_at - p.created_at))) / 3600.0, 2)
                                                             AS delai_moyen_heures,
    -- PERCENTILE_CONT rend un `double precision`, comme AVG sur du float8 :
    -- le cast en numeric est requis avant ROUND(x, 2).
    ROUND((
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (p.decided_at - p.created_at))
        ) / 3600.0)::numeric, 2)                                AS delai_median_heures,
    ROUND((
        PERCENTILE_CONT(0.90) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (p.decided_at - p.created_at))
        ) / 3600.0)::numeric, 2)                                AS delai_p90_heures
FROM ml.prediction p
WHERE p.decided_at IS NOT NULL
GROUP BY 1;

COMMENT ON VIEW bi.v_delai_decision IS
    'Delai entre alerte et decision gestionnaire, moyenne / mediane / p90. Source ml.prediction. Frequence : a chaque decision. VIDE tant qu aucune decision n est enregistree.';


-- ----------------------------------------------------------------------------
-- Montants economises : fraude confirmee par un gestionnaire
-- ----------------------------------------------------------------------------
-- SECURITY DEFINER : lecture agregee de `audit`, sans en exposer le detail.
-- `security_invoker = false` est le DEFAUT de PostgreSQL : une vue
-- verifie les droits de son proprietaire, pas ceux du lecteur. On
-- l'ecrit explicitement parce que c'est tout le mecanisme de securite
-- de cette vue, et qu'un defaut qu'on ne nomme pas disparait un jour.
--
-- `WITH SECURITY DEFINER` n'existe pas en SQL PostgreSQL : c'est la
-- forme `WITH (security_invoker = ...)` qui convient.
CREATE OR REPLACE VIEW bi.v_montants_economises
WITH (security_invoker = false) AS
SELECT
    date_trunc('month', p.created_at)::date                    AS mois,
    COUNT(*)                                                   AS nb_fraudes_confirmees,
    SUM(f.montant_total)                                       AS montant_fraude_mga,
    -- Part du montant presente a tort-remboursement qui a ete retenue.
    ROUND(100.0 * SUM(f.montant_total)
          / NULLIF(SUM(t.montant_total_du_mois), 0), 2)        AS poids_pct
FROM audit.decision_gestionnaire d
JOIN ml.prediction p ON p.id = d.prediction_id
JOIN core.facture   f ON f.id = p.facture_id
JOIN (
    SELECT date_trunc('month', date_facture)::date AS mois,
           SUM(montant_total) AS montant_total_du_mois
    FROM core.facture
    GROUP BY 1
) t ON t.mois = date_trunc('month', p.created_at)::date
-- Valeurs reelles imposees par `ManagerDecision` dans
-- `packages/predicare-core/src/predicare/schemas.py` :
--   Literal['valider_fraude', 'rejeter', 'demander_piece']
-- La colonne est un String(32) sans contrainte en base ; filtrer sur
-- une valeur inventee ('FRAUDE_CONFIRMEE') ne leveraged aucun ecart,
-- mais rendrait le filtre faux si la donnee arrivait un jour.
WHERE d.decision = 'valider_fraude'
GROUP BY 1;

COMMENT ON VIEW bi.v_montants_economises IS
    'Montant de fraude confirmee par un gestionnaire, par mois. SECURITY DEFINER : agregat seul, aucune donnee nominative. Source audit.decision_gestionnaire + ml.prediction. VIDE tant qu aucune decision n est enregistree.';


-- ----------------------------------------------------------------------------
-- Taux de faux positifs : ecart entre prediction et decision humaine
-- ----------------------------------------------------------------------------
-- Le seul indicateur du CDC qui ne soit pas definissable sur `core` seul :
-- il compare une PREDICTION a une VERITE HUMAINE.
--
-- SECURITY DEFINER : lecture agregee de `audit`, sans en exposer le detail.
CREATE OR REPLACE VIEW bi.v_faux_positifs
WITH (security_invoker = false) AS
SELECT
    p.is_fraud                                                 AS prediction_fraude,
    d.decision                                                 AS decision_gestionnaire,
    COUNT(*)                                                   AS nb_dossiers,
    SUM(f.montant_total)                                       AS montant_mga
FROM ml.prediction p
LEFT JOIN audit.decision_gestionnaire d ON d.prediction_id = p.id
LEFT JOIN core.facture f ON f.id = p.facture_id
GROUP BY 1, 2;

COMMENT ON VIEW bi.v_faux_positifs IS
    'Matrice de confusion metier : prediction du modele contre decision humaine. SECURITY DEFINER : agregat seul. Source ml.prediction + audit.decision_gestionnaire. VIDE tant qu aucune decision n est enregistree.';


-- ============================================================================
-- bi.v_cdc_global : grain = 1 ligne, la boucle de decision en direct
-- ============================================================================
-- La file d'alertes est vivante : alertes en attente, montant expose, puis
-- decisions humaines (montants confirmes, delai). C'est ce que le gestionnaire
-- voit dans l'interface, agrege pour le pilotage.
--
-- Le seuil d'alerte est relu dans `audit.parametre` a chaque requete : un
-- changement depuis l'ecran d'administration s'applique immediatement, comme
-- la file de `api-core` (condition « Configurable » du CDC).
--
-- Grain = 1 LIGNE, toujours, meme vide. Une tuile qui affiche « en attente »
-- est informative ; une tuile sans aucune ligne ne se distingue pas d'une
-- tuile cassee. D'ou le LEFT JOIN et l'absence de filtre `WHERE` : la vue
-- renvoie une ligne, avec des NULL explicites.
--
-- SECURITY DEFINER : lecture agregee de `audit`, sans en exposer le detail.
-- Un DROP est necessaire : la vue change de colonnes, et CREATE OR REPLACE
-- ne sait pas retirer une colonne existante.
DROP VIEW IF EXISTS bi.v_cdc_global CASCADE;

CREATE VIEW bi.v_cdc_global
WITH (security_invoker = false) AS
WITH seuil AS (
    SELECT COALESCE(
        (SELECT valeur::numeric FROM audit.parametre WHERE cle = 'seuil_alerte'),
        0.8::numeric
    ) AS valeur
)
SELECT
    COUNT(p.id)                                               AS nb_predictions,

    -- File d'alerte : meme filtre que `GET /api/core/alertes/file`.
    COUNT(*) FILTER (
        WHERE p.statut = 'nouvelle'
          AND p.score_fraude >= (SELECT valeur FROM seuil)
    )                                                         AS nb_alertes_en_attente,

    ROUND(COALESCE(SUM(f.montant_total) FILTER (
        WHERE p.statut = 'nouvelle'
          AND p.score_fraude >= (SELECT valeur FROM seuil)
    ), 0), 2)                                                 AS montant_en_attente_mga,

    -- Boucle humaine : ce qu'un gestionnaire a reellement tranche.
    COUNT(d.prediction_id)                                    AS nb_decisions,

    ROUND(SUM(f.montant_total) FILTER (WHERE d.decision = 'valider_fraude'), 2)
                                                            AS montant_economise_mga,

    ROUND(AVG(EXTRACT(EPOCH FROM (d.decided_at - p.created_at))) / 3600.0, 2)
                                                            AS delai_decision_heures,

    -- Temps
    -- -----
    -- `periode` = mois de la derniere prediction. Meme role que dans
    -- v_kpi_global : c'est la colonne temporelle que le frontal Superset
    -- reclame pour toute requete de serie temporelle, et `big_number` en
    -- construit toujours une. Sans elle : 400 « Datetime column not
    -- provided ». NULL tant que `ml.prediction` est vide -- la vue rend
    -- quand meme une ligne, et la tuile affiche « en attente ».
    MAX(date_trunc('month', p.created_at))::date            AS periode
FROM (SELECT 1) base
LEFT JOIN ml.prediction p ON TRUE
LEFT JOIN audit.decision_gestionnaire d ON d.prediction_id = p.id
LEFT JOIN core.facture                 f ON f.id            = p.facture_id;

COMMENT ON VIEW bi.v_cdc_global IS
    'Boucle de decision en direct : predictions, alertes en attente (seuil courant), montant expose, decisions, montants confirmes et delai. Grain 1 ligne, TOUJOURS presente meme vide. SECURITY DEFINER : agregat seul, aucune donnee nominative. `periode` (mois de la derniere prediction, NULL si aucune) sert de colonne temporelle au frontal. Source ml.prediction + audit.decision_gestionnaire.';
