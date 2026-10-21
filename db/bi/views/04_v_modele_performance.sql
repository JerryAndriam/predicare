-- ============================================================================
-- Performance du modele : les metriques de TEST de la version promue
-- ----------------------------------------------------------------------------
-- Le CDC demande un « taux de detection » (Flux 3) et privilegie le Rappel
-- (Module 2). Le chiffre honnete est celui du TEST TEMPOREL : la derniere
-- fenetre de 3 mois, jamais vue a l'entrainement, lue une seule fois par
-- `train.py`.
--
-- Pourquoi pas un rejeu de tout l'historique : les factures d'entrainement
-- sont dans `ml.prediction` apres le backfill, et un rappel calcule dessus
-- serait IN-SAMPLE (surapprecie). Il ne doit donc pas alimenter la tuile de
-- performance. Ces metriques vivent deja dans `ml.modele_version.metriques`,
-- ecrites par le job d'entrainement et conservees avec le registre.
--
-- Grain = 1 LIGNE, toujours, meme si aucun modele n'est promu : la tuile
-- affiche alors « en attente » au lieu de disparaitre.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_modele_performance AS
WITH modele AS (
    SELECT version, promu_le, metriques
    FROM ml.modele_version
    WHERE statut = 'promu'
    ORDER BY promu_le DESC NULLS LAST
    LIMIT 1
)
SELECT
    m.version                                               AS version,

    -- Rappel = vrais positifs / vraies fraudes, sur le test temporel.
    ROUND(((m.metriques ->> 'rappel')::numeric) * 100.0, 2)
                                                            AS rappel_test_pct,

    -- Faux positifs = 1 - precision, sur le meme test.
    ROUND(
        100.0 - ((m.metriques ->> 'precision')::numeric) * 100.0,
        2
    )                                                       AS faux_positifs_test_pct,

    ROUND(((m.metriques ->> 'precision')::numeric) * 100.0, 2)
                                                            AS precision_test_pct,

    ROUND(((m.metriques ->> 'roc_auc')::numeric), 4)        AS roc_auc_test,
    ROUND(((m.metriques ->> 'pr_auc')::numeric), 4)         AS pr_auc_test,
    ROUND(((m.metriques ->> 'gain_metier')::numeric), 2)    AS gain_metier_test_mga,

    ((m.metriques ->> 'vrais_positifs')::numeric)::bigint   AS vrais_positifs_test,
    ((m.metriques ->> 'faux_positifs')::numeric)::bigint    AS faux_positifs_test,
    ((m.metriques ->> 'nb_factures')::numeric)::bigint      AS nb_factures_test,

    m.promu_le                                              AS promu_le,

    -- Colonne temporelle exigee par `big_number` (voir v_cdc_global).
    date_trunc('month', m.promu_le)::date                   AS periode
FROM (SELECT 1) base
LEFT JOIN modele m ON TRUE;

COMMENT ON VIEW bi.v_modele_performance IS
    'Metriques de TEST de la version promue : rappel, faux positifs (1 - precision), precision, ROC-AUC, PR-AUC, gain metier et taille du jeu de test. Grain 1 ligne, TOUJOURS presente meme si aucun modele n''est promu. Source ml.modele_version.';
