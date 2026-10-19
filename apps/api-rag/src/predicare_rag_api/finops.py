"""Estimation du cout LLM (Phase F - FinOps).

Les prix sont des *parametres*, pas des constantes cachees : un tarif
fournisseur change, et un chiffre FinOps doit pouvoir etre recalcule avec
le tarif du moment. Les valeurs par defaut correspondent a un petit modele
GPT-4o-mini (0,15 USD / million de tokens d'entree, 0,60 USD / million de
tokens de sortie) et a un taux de conversion indicatif USD -> EUR.

Le module reste sans dependance : il est utilisable par l'API, par les
scripts d'evaluation et par les tests, sans demarrer quoi que ce soit.
"""

from __future__ import annotations

#: Tarifs par defaut, en USD par million de tokens. A verifier avant toute
#: presentation : les grilles tarifaires evoluent.
PRIX_ENTREE_DEFAUT_USD_PAR_MILLION = 0.15
PRIX_SORTIE_DEFAUT_USD_PAR_MILLION = 0.60
TAUX_USD_EUR_DEFAUT = 0.92


def estimer_cout(
    tokens_entree: int,
    tokens_sortie: int,
    prix_entree_par_million_usd: float = PRIX_ENTREE_DEFAUT_USD_PAR_MILLION,
    prix_sortie_par_million_usd: float = PRIX_SORTIE_DEFAUT_USD_PAR_MILLION,
    taux_usd_eur: float = TAUX_USD_EUR_DEFAUT,
) -> dict[str, float]:
    """Retourne le cout estime d'un appel LLM, en USD et en EUR.

    Formule lineaire, volontairement explicite pour que le jury puisse la
    refaire a la main :

        cout_entree = tokens_entree / 1_000_000 * prix_entree
        cout_sortie = tokens_sortie / 1_000_000 * prix_sortie
        cout_total_eur = cout_total_usd * taux_usd_eur

    Les tokens sont des entiers positifs ou nuls ; une valeur negative est
    traitee comme zero pour ne jamais produire un cout negatif. Le detail en
    EUR par sens est fourni pour que le dossier FinOps puisse ventiler le
    cout d'entree (prompt) et le cout de sortie (completion).
    """
    entree = max(0, int(tokens_entree))
    sortie = max(0, int(tokens_sortie))

    cout_entree_usd = entree / 1_000_000 * prix_entree_par_million_usd
    cout_sortie_usd = sortie / 1_000_000 * prix_sortie_par_million_usd
    cout_total_usd = cout_entree_usd + cout_sortie_usd

    return {
        "cout_entree_usd": round(cout_entree_usd, 6),
        "cout_sortie_usd": round(cout_sortie_usd, 6),
        "cout_total_usd": round(cout_total_usd, 6),
        "cout_entree_eur": round(cout_entree_usd * taux_usd_eur, 6),
        "cout_sortie_eur": round(cout_sortie_usd * taux_usd_eur, 6),
        "cout_total_eur": round(cout_total_usd * taux_usd_eur, 6),
    }
