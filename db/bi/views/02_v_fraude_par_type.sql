-- ============================================================================
-- bi.v_fraude_par_type : grain = 1 ligne / type de fraude x mois
-- ============================================================================
-- Les 14 types de fraude documents par l'encadrement, avec leur volume et
-- le montant expose. Le taux est calcule par rapport au volume TOTAL du mois,
-- pas au volume du type : un camembert par type se lit, une courbe par type
-- non, et surtout le taux par type ne se lit correctement que Face a son
-- denominateur reel.
--
-- Frequence : a chaque rechargement.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_fraude_par_type AS
SELECT
    d.mois                                                 AS mois,
    d.type_fraude,
    d.nb_fraudes,
    d.montant_fraude_mga,
    t.nb_factures_du_mois,
    -- Part de ce type dans le volume total du mois.
    ROUND(100.0 * d.nb_fraudes / NULLIF(t.nb_factures_du_mois, 0), 2)
                                                            AS part_du_type_pct,
    -- Part de ce type parmi les seules factures frauduleuses du mois.
    ROUND(100.0 * d.nb_fraudes / NULLIF(t.nb_fraudes_du_mois, 0), 2)
                                                            AS part_de_la_fraude_pct
FROM (
    SELECT
        date_trunc('month', f.date_facture)::date            AS mois,
        l.type_fraude,
        COUNT(*)                                              AS nb_fraudes,
        SUM(f.montant_total)                                  AS montant_fraude_mga
    FROM core.facture f
    JOIN ml.label_fraude l ON l.facture_id = f.id
    WHERE l.label = 1
      AND l.type_fraude IS NOT NULL
    GROUP BY 1, 2
) d
JOIN (
    SELECT
        date_trunc('month', f.date_facture)::date            AS mois,
        COUNT(*)                                              AS nb_factures_du_mois,
        COUNT(*) FILTER (WHERE l.label = 1)                   AS nb_fraudes_du_mois
    FROM core.facture f
    LEFT JOIN ml.label_fraude l ON l.facture_id = f.id
    GROUP BY 1
) t ON t.mois = d.mois;

COMMENT ON VIEW bi.v_fraude_par_type IS
    'Fraude par mecanisme et par mois, avec montant expose et part dans le volume. Source ml.label_fraude + core.facture. Frequence : a chaque rechargement.';


-- ============================================================================
-- bi.v_prestataires_risque : grain = 1 ligne / prestataire
-- ============================================================================
-- Classement par montant expose plutot que par taux : un taux eleve sur
-- 3 factures ne pese rien, un taux de 8 % sur 2 000 factures coute cher.
-- Le dashboard trie donc sur `montant_expose_mga`.
--
-- `actif` et `conventionne` viennent du referentiel, pas du jeu de labels :
-- un prestataire radie qui continue de facturer est un point de controle.
--
-- Frequence : a chaque rechargement.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_prestataires_risque AS
SELECT
    p.id                                                   AS prestataire_id,
    p.code                                                 AS prestataire_code,
    p.nom                                                  AS prestataire_nom,
    p.type                                                 AS prestataire_type,
    p.ville                                                AS prestataire_ville,
    p.niveau_tarif,
    p.conventionne,
    p.date_fin_convention,
    p.actif                                                AS prestataire_actif,
    COUNT(f.id)                                             AS nb_factures,
    COUNT(f.id) FILTER (WHERE l.label = 1)                  AS nb_fraudes,
    ROUND(100.0 * COUNT(f.id) FILTER (WHERE l.label = 1)
          / NULLIF(COUNT(f.id), 0), 2)                     AS taux_fraude_pct,
    SUM(f.montant_total)                                   AS montant_total_mga,
    SUM(f.montant_total) FILTER (WHERE l.label = 1)        AS montant_expose_mga,
    -- Factures emises apres la fin de convention : anomalie de controle,
    -- distincte d'une fraude.
    COUNT(f.id) FILTER (WHERE p.date_fin_convention IS NOT NULL
                          AND f.date_facture > p.date_fin_convention)
                                                            AS nb_apres_fin_convention
FROM core.prestataire p
LEFT JOIN core.facture f     ON f.prestataire_id = p.id
LEFT JOIN ml.label_fraude l   ON l.facture_id = f.id
GROUP BY p.id, p.code, p.nom, p.type, p.ville, p.niveau_tarif,
         p.conventionne, p.date_fin_convention, p.actif;

COMMENT ON VIEW bi.v_prestataires_risque IS
    'Prestataires classes par montant expose, avec taux de fraude et anomalies de convention. Source core.prestataire + core.facture + ml.label_fraude. Frequence : a chaque rechargement.';


-- ============================================================================
-- bi.v_controle_points : grain = 1 ligne / motif x mois
-- ============================================================================
-- Les points de controle qui expliquent pourquoi une facture n'a pas ete
-- payee en l'integralite. Deux familles volontairement melangees ici :
--
--  - les REJETS, portee par `core.facture.motif_rejet` ;
--  - les HORS COUVERTURE, calcules sur les regles metier du jeu
--    (soin avant l'effet du contrat, soin apres la radiation).
--
-- Melanger les deux dans une meme vue est un choix de lisibilite, pas un
-- oubli : un gestionnaire veut une seule liste « pourquoi n'a-t-on pas paye ».
-- La colonne `famille` permet de les separer dans un graphique.
--
-- Frequence : a chaque rechargement.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_controle_points AS
SELECT
    x.mois                                                 AS mois,
    x.famille,
    x.motif,
    x.nb_factures,
    x.montant_concerne_mga,
    ROUND(100.0 * x.nb_factures / NULLIF(t.nb_factures_du_mois, 0), 2)
                                                            AS taux_du_mois_pct
FROM (
    -- Rejets metadataires
    SELECT
        date_trunc('month', date_facture)::date            AS mois,
        'REJET'                                              AS famille,
        COALESCE(motif_rejet, 'NON_PRECISE')                AS motif,
        COUNT(*)                                             AS nb_factures,
        SUM(montant_total)                                   AS montant_concerne_mga
    FROM core.facture
    WHERE statut = 'REJETEE'
    GROUP BY 1, 3

    UNION ALL

    -- Hors couverture : soin avant l'effet du contrat
    SELECT
        date_trunc('month', f.date_soin)::date              AS mois,
        'COUVERTURE'                                         AS famille,
        'SOIN_AVANT_EFFET_CONTRAT'                           AS motif,
        COUNT(*)                                             AS nb_factures,
        SUM(f.montant_total)                                 AS montant_concerne_mga
    FROM core.facture f
    JOIN core.contrat c ON c.id = f.contrat_id
    WHERE f.date_soin < c.date_debut
    GROUP BY 1, 3

    UNION ALL

    -- Hors couverture : soin apres la fin du contrat
    SELECT
        date_trunc('month', f.date_soin)::date              AS mois,
        'COUVERTURE'                                         AS famille,
        'SOIN_APRES_FIN_CONTRAT'                             AS motif,
        COUNT(*)                                             AS nb_factures,
        SUM(f.montant_total)                                 AS montant_concerne_mga
    FROM core.facture f
    JOIN core.contrat c ON c.id = f.contrat_id
    WHERE c.date_fin IS NOT NULL
      AND f.date_soin > c.date_fin
    GROUP BY 1, 3

    UNION ALL

    -- Hors couverture : adherent radie
    SELECT
        date_trunc('month', f.date_soin)::date              AS mois,
        'COUVERTURE'                                         AS famille,
        'ADHERENT_RADIE'                                     AS motif,
        COUNT(*)                                             AS nb_factures,
        SUM(f.montant_total)                                 AS montant_concerne_mga
    FROM core.facture f
    JOIN core.assure a       ON a.id = f.assure_id
    JOIN core.contrat_beneficiaire cb ON cb.assure_id = a.id
    WHERE cb.date_radiation IS NOT NULL
      AND f.date_soin > cb.date_radiation
    GROUP BY 1, 3
) x
JOIN (
    SELECT date_trunc('month', date_facture)::date AS mois, COUNT(*) AS nb_factures_du_mois
    FROM core.facture
    GROUP BY 1
) t ON t.mois = x.mois;

COMMENT ON VIEW bi.v_controle_points IS
    'Motifs de non-paiement : rejets metadataires et hors couverture, par mois. Source core.facture + core.contrat + core.contrat_beneficiaire. Frequence : a chaque rechargement.';
