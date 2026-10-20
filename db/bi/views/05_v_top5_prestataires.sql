-- bi.v_top5_prestataires : les cinq prestataires les plus exposes.
-- Grain = 1 ligne / prestataire, au maximum 5 lignes. La limite n'est PAS
-- un indice du frontal : elle est porte par la vue, donc un camembert, un
-- tableau ou un graphique a barres renvoient tous les cinq mêmes lignes, meme
-- si le controle « Row limit » est perdu lors d'une manipulation.
--
-- Source : v_prestataires_risque, filtree sur les prestataires qui ont au
-- moins une facture et dont le montant expose est strictement positif.
-- ============================================================================

CREATE OR REPLACE VIEW bi.v_top5_prestataires AS
SELECT
    prestataire_id,
    prestataire_code,
    prestataire_nom,
    prestataire_ville,
    nb_factures,
    nb_fraudes,
    taux_fraude_pct,
    montant_total_mga,
    montant_expose_mga,
    nb_apres_fin_convention
FROM bi.v_prestataires_risque
WHERE nb_factures > 0
  AND montant_expose_mga IS NOT NULL
  AND montant_expose_mga > 0
ORDER BY montant_expose_mga DESC NULLS LAST
LIMIT 5;

COMMENT ON VIEW bi.v_top5_prestataires IS
    'Cinq prestataires classes par montant expose, avec taux de fraude. Vue pour le tableau de bord : la limite est structurelle, pas un indice du frontal. Source bi.v_prestataires_risque. Frequence : a chaque rechargement.';

GRANT SELECT ON bi.v_top5_prestataires TO superset_ro;
