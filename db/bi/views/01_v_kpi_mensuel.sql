-- ============================================================================
-- bi.v_kpi_mensuel : le tableau de bord de pilotage, grain = 1 ligne / mois
-- ============================================================================
-- Indicateurs : volume de factures, montants en ariary, taux de fraude
-- observe, delai moyen de traitement.
--
-- Source de verite
-- ----------------
-- core.facture porte le fait metier. ml.label_fraude porte la VERITE
-- TERRAIN (les labels fournis par l'encadrement), pas la sortie du modele.
--
-- Le jour ou `ml.prediction` sera peuple par un modele entraine, la taux de
-- detection et de faux positifs se lira la : seule la ligne de jointure
-- change, pas la vue.
--
-- Le taux de fraude calcule ici est donc la PREVALENCE observee dans le jeu
-- (part des factures reellement frauduleuses), et non le rappel d'un modele.
-- Ce sont deux grandeurs differentes et le libelle du dashboard doit le dire.
--
-- Unite : tous les montants sont en MGA (ariary), devise unique du jeu.
-- Le nom de colonne le porte. Un libelle « EUR » ici serait faux d'un
-- facteur d'environ 57 000.
--
-- Frequence : le jeu est fige sur 24 mois ; la vue se recalcule a chaque
-- chargement. Aucune notion de « aujourd'hui » n'intervient.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_kpi_mensuel AS
SELECT
    -- Grain
    date_trunc('month', f.date_facture)::date            AS mois,

    -- Volume
    COUNT(*)                                              AS nb_factures,
    COUNT(DISTINCT f.assure_id)                           AS nb_assures,
    COUNT(DISTINCT f.prestataire_id)                       AS nb_prestataires,

    -- Montants, en ariary
    SUM(f.montant_total)                                   AS montant_total_mga,
    SUM(f.montant_pris_en_charge)                          AS montant_pris_en_charge_mga,
    SUM(f.reste_a_charge)                                  AS reste_a_charge_mga,
    -- 100 = la totalite du montant presente a tort-remboursement a la
    -- company. Indicateur de fuite de tresorerie, pas de performance.
    ROUND(100.0 * SUM(f.reste_a_charge)
          / NULLIF(SUM(f.montant_total), 0), 2)           AS taux_reste_a_charge_pct,

    -- Fraude observee
    COUNT(*) FILTER (WHERE l.label = 1)                    AS nb_fraudes,
    ROUND(100.0 * COUNT(*) FILTER (WHERE l.label = 1)
          / NULLIF(COUNT(*), 0), 2)                       AS taux_fraude_pct,
    -- Montant qu'une detection de la fraude aurait evite de payer. C'est la
    -- base du raisonnement FinOps du projet.
    SUM(f.montant_total) FILTER (WHERE l.label = 1)        AS montant_fraude_mga,

    -- Delai de traitement, mesure sur les seules factures traitees.
    -- `date_traitement` est NULL tant que la facture n'est pas traitee :
    -- l'inclure au denominateur mesurerait le temps d'attente, pas le delai.
    ROUND(AVG(EXTRACT(EPOCH FROM (f.date_traitement - f.date_reception)))
          FILTER (WHERE f.date_traitement IS NOT NULL) / 86400.0, 2)
                                                            AS delai_traitement_jours,
    COUNT(*) FILTER (WHERE f.date_traitement IS NOT NULL) AS nb_factures_traitees
FROM core.facture f
LEFT JOIN ml.label_fraude l ON l.facture_id = f.id
GROUP BY 1;

COMMENT ON VIEW bi.v_kpi_mensuel IS
    'Pilotage mensuel : volume, montants MGA, prevalence de la fraude et delai de traitement. Source core.facture + ml.label_fraude. Frequence : a chaque rechargement.';


-- ============================================================================
-- bi.v_factures_detail : grain = 1 ligne / facture
-- ============================================================================
-- Socle d'exploration. Superset peut agreger librement a partir d'ici :
-- un graphique au grain facture ne doit jamais recalculer une moyenne
-- d'efficience deja calculee ailleurs.
--
-- Frequence : a chaque rechargement.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_factures_detail AS
SELECT
    f.id                                                   AS facture_id,
    f.reference                                            AS facture_reference,
    f.date_facture::date                                   AS date_facture,
    f.date_soin::date                                      AS date_soin,
    f.type_facture,
    f.canal_reception,
    f.mode_reglement,
    f.statut,
    f.motif_rejet,
    f.devise,
    f.montant_total                                        AS montant_total_mga,
    f.montant_eligible                                     AS montant_eligible_mga,
    f.montant_pris_en_charge                               AS montant_pris_en_charge_mga,
    f.reste_a_charge                                       AS reste_a_charge_mga,
    -- Dimensions denormalisees : le grain est la facture, donc agreger par
    -- prestataire ou par mois ne doit pas exiger une jointure supplementaire
    -- dans chaque graphique.
    f.prestataire_id,
    p.nom                                                  AS prestataire_nom,
    p.type                                                 AS prestataire_type,
    p.ville                                                AS prestataire_ville,
    p.conventionne,
    p.date_fin_convention,
    f.assure_id,
    a.commune_code                                         AS assure_commune,
    a.annee_naissance,
    a.sexe                                                 AS assure_sexe,
    f.contrat_id,
    f.ordonnance_id,
    -- Verite terrain
    COALESCE(l.label, 0)                                   AS est_fraude,
    l.type_fraude,
    l.detail_fraude,
    -- Signaux de delai
    f.date_reception::date                                 AS date_reception,
    f.date_traitement::date                                AS date_traitement,
    ROUND(EXTRACT(EPOCH FROM (f.date_traitement - f.date_reception))
          / 86400.0, 2)                                    AS delai_traitement_jours
FROM core.facture f
LEFT JOIN core.prestataire p ON p.id = f.prestataire_id
LEFT JOIN core.assure a       ON a.id = f.assure_id
LEFT JOIN ml.label_fraude l   ON l.facture_id = f.id;

COMMENT ON VIEW bi.v_factures_detail IS
    'Detail au grain facture, dimensions denormalisees, verite terrain jointe. Source core.facture + core.prestataire + core.assure + ml.label_fraude. Frequence : a chaque rechargement.';
