"""Evaluation de la fidelite du RAG sur le jeu de questions de reference.

Le script mesure quatre choses, separement :

- la fidelite : tous les mots-cles attendus figurent dans la reponse ;
- la citation : au moins une source retournee porte le contrat ou l'article
  attendu (les questions purement SQL ne declarent pas de source) ;
- l'exactitude des valeurs : les montants/dates attendus sont presents ;
- le cout et la latence : p50, p95, tokens (entree + sortie) et estimation
  FinOps.

Le cache semantique est desactive par defaut (`--no-cache`) : sans cela, une
question proche deja posee serait servie depuis le cache, avec zero token, et
l'evaluation mesurerait le cache au lieu du RAG. Le resume rapporte les
succes de cache pour que le chiffre reste lisible.

Usage :
    python scripts/eval_rag.py --base-url http://localhost:8003 --token <JWT>
    python scripts/eval_rag.py --token <JWT> --ci --no-cache --output /tmp/eval.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx

FICHIER = Path(__file__).resolve().parents[1] / "tests" / "rag_reference" / "questions.json"

SEUIL_FIDELITE = 0.80
SEUIL_CITATION = 0.90
SEUIL_VALEUR = 0.90
COUT_PAR_MILLION_DEFAUT = 0.60

#: Champs de la source qui peuvent porter la reference attendue.
CHAMPS_SOURCE = ("contrat", "article", "garantie", "source_fichier")


# --------------------------------------------------------------- normalisation


def normaliser_texte(texte: str | None) -> str:
    """Minuscules, sans accents, espaces et separateurs de milliers normalises."""
    if not texte:
        return ""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    normalise = sans_accents.lower()
    normalise = (
        normalise.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("\u2019", "'")
    )
    normalise = re.sub(r"\s+", " ", normalise)
    # 616 060 et 20 000 000 doivent devenir 616060 et 20000000, sans
    # toucher aux espaces entre un nombre et son unite ("90 jours").
    normalise = re.sub(r"(?<=\d) (?=\d)", "", normalise)
    return normalise.strip()


def _correspond(texte_normalise: str, attendu: str) -> bool:
    """Sous-chaine, ou expression reguliere prefixee par `re:`."""
    attendu_normalise = normaliser_texte(attendu)
    if attendu_normalise.startswith("re:"):
        try:
            return re.search(attendu_normalise[3:], texte_normalise) is not None
        except re.error:
            return attendu_normalise[3:] in texte_normalise
    return attendu_normalise in texte_normalise


def mots_cles_presents(texte: str, mots_cles: list[str]) -> bool:
    """Vrai si tous les mots-cles sont presents, accents et casse ignores."""
    texte_normalise = normaliser_texte(texte)
    return all(normaliser_texte(mot) in texte_normalise for mot in mots_cles)


def citation_ok(sources: list[dict], sources_attendues: list[str]) -> bool | None:
    """Vrai si une source porte une reference attendue.

    `None` signifie « non applicable » : une question purement SQL n'a pas
    de citation contractuelle a produire, elle ne doit donc ni reussir ni
    echouer le taux de citation.
    """
    if not sources_attendues:
        return None
    references = [
        normaliser_texte(" ".join(str(source.get(champ) or "") for champ in CHAMPS_SOURCE))
        for source in sources
    ]
    return any(
        _correspond(reference, attendu) for reference in references for attendu in sources_attendues
    )


def valeur_ok(reponse: str, attendu_contient: list[str]) -> bool | None:
    """Vrai si toutes les valeurs attendues figurent dans la reponse."""
    if not attendu_contient:
        return None
    reponse_normalisee = normaliser_texte(reponse)
    return all(_correspond(reponse_normalisee, attendu) for attendu in attendu_contient)


# ------------------------------------------------------------------ statistiques


def percentile(valeurs: list[float], p: float) -> float:
    """Percentile par interpolation lineaire, sans dependance externe."""
    if not valeurs:
        return 0.0
    triees = sorted(valeurs)
    if p <= 0:
        return float(triees[0])
    if p >= 100:
        return float(triees[-1])
    rang = (len(triees) - 1) * p / 100
    bas = int(rang)
    haut = min(bas + 1, len(triees) - 1)
    return float(triees[bas] + (triees[haut] - triees[bas]) * (rang - bas))


def estimer_cout(tokens: int, cout_par_million: float = COUT_PAR_MILLION_DEFAUT) -> float:
    """Estimation lineaire du cout LLM, en dollars.

    `tokens` est le total entree + sortie : ne compter que la completion
    sous-estime le cout, la part « prompt » dominant un agent a outils. Le
    prix applique reste un prix moyen par million de tokens, sans distinguer
    les deux sens.
    """
    return round(tokens / 1_000_000 * cout_par_million, 6)


def cout_par_million_depuis_env() -> float:
    """Prix configurable, pour suivre le tarif reel du fournisseur."""
    valeur = os.getenv("LLM_COUT_PAR_MILLION_USD", str(COUT_PAR_MILLION_DEFAUT))
    try:
        return float(valeur)
    except ValueError:
        return COUT_PAR_MILLION_DEFAUT


def respecte_seuils_ci(
    fidelite: float,
    citation: float,
    valeur: float,
    *,
    citation_questions: int | None = None,
    valeur_questions: int | None = None,
) -> bool:
    """Decision de la CI : les trois seuils doivent etre atteints.

    Un taux vaut 1.0 quand son denominateur est nul (`_taux`). Une CI qui
    admettrait une mesure vide passerait donc sans avoir rien verifie : un
    denominateur nul est un echec explicite, pas un sans-faute.
    """
    if citation_questions == 0:
        return False
    if valeur_questions == 0:
        return False
    return fidelite >= SEUIL_FIDELITE and citation >= SEUIL_CITATION and valeur >= SEUIL_VALEUR


def _taux(ok: int, total: int) -> float:
    return ok / total if total else 1.0


# ------------------------------------------------------------------- evaluation


def _tokens_entree_sortie(reponse: dict[str, Any]) -> tuple[int, int]:
    """Tokens d'entree et de sortie d'une reponse API, avec repli.

    Une API ancienne n'expose pas le detail : on retombe alors sur le total
    `tokens` (historiquement la completion), pour ne pas afficher zero.
    """
    entree = int(reponse.get("tokens_entree") or 0)
    sortie = int(reponse.get("tokens_sortie") or 0)
    if entree == 0 and sortie == 0:
        sortie = int(reponse.get("tokens") or 0)
    return entree, sortie


def evaluer_reponse(question: dict[str, Any], reponse: dict[str, Any], latence_ms: float) -> dict:
    """Construit le resultat d'une question, sans modifier la reponse."""
    texte = reponse.get("reponse") or ""
    sources = reponse.get("sources") or []
    tokens_entree, tokens_sortie = _tokens_entree_sortie(reponse)
    return {
        "id": question["id"],
        "type": question.get("type", "rag"),
        "question": question["question"],
        "reponse": texte,
        "sources": [
            {
                "contrat": source.get("contrat"),
                "article": source.get("article"),
                "garantie": source.get("garantie"),
                "score": source.get("score"),
            }
            for source in sources
        ],
        "fidelite": mots_cles_presents(texte, question.get("mots_cles", [])),
        "citation": citation_ok(sources, question.get("sources_attendues", [])),
        "valeur": valeur_ok(texte, question.get("attendu_contient", [])),
        "latence_ms": round(latence_ms, 2),
        "tokens_entree": tokens_entree,
        "tokens_sortie": tokens_sortie,
        "tokens": tokens_entree + tokens_sortie,
        "cache_semantique": bool(reponse.get("cache_semantique")),
    }


def _appeler(
    client: httpx.Client, base_url: str, token: str, question: str, *, sans_cache: bool = True
) -> tuple[dict[str, Any], float]:
    """Appelle l'API RAG, cache desactive par defaut.

    Sans ce contournement, deux questions proches partageraient la meme
    reponse et l'evaluation mesurerait le cache, pas le RAG. Un appel
    servi par le cache coute zero token : il fausserait l'estimation.
    """
    headers = {"Authorization": f"Bearer {token}"}
    if sans_cache:
        headers["X-Rag-No-Cache"] = "true"
    debut = time.perf_counter()
    response = client.post(
        f"{base_url.rstrip('/')}/api/rag/question",
        headers=headers,
        json={"question": question},
    )
    latence_ms = (time.perf_counter() - debut) * 1000
    response.raise_for_status()
    return response.json(), latence_ms


def _imprimer_tableau(resultats: list[dict]) -> None:
    entete = f"{'ID':<5} {'Type':<6} {'Fid.':<5} {'Cit.':<5} {'Val.':<5} {'ms':>9} {'tokens':>8}"
    print(entete)
    print("-" * len(entete))
    for resultat in resultats:
        citation = (
            "-" if resultat["citation"] is None else ("oui" if resultat["citation"] else "non")
        )
        valeur = "-" if resultat["valeur"] is None else ("oui" if resultat["valeur"] else "non")
        print(
            f"{resultat['id']:<5} {resultat['type']:<6} "
            f"{'oui' if resultat['fidelite'] else 'non':<5} {citation:<5} {valeur:<5} "
            f"{resultat['latence_ms']:>9.1f} {resultat['tokens']:>8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluation du RAG PrediCare")
    parser.add_argument("--base-url", default="http://localhost:8003")
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--ci", action="store_true", help="Sort en erreur si les seuils ne sont pas atteints"
    )
    parser.add_argument("--output", type=Path, help="Ecrit les resultats detailles en JSON")
    parser.add_argument("--limit", type=int, default=0, help="Limite le nombre de questions")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--no-cache",
        dest="sans_cache",
        action="store_true",
        default=True,
        help="Desactive le cache semantique : evaluation a froid (defaut)",
    )
    parser.add_argument(
        "--cache",
        dest="sans_cache",
        action="store_false",
        help="Autorise le cache semantique (mesure alors le gain du cache)",
    )
    args = parser.parse_args()

    questions = json.loads(FICHIER.read_text(encoding="utf-8"))
    if args.limit:
        questions = questions[: args.limit]

    resultats: list[dict] = []
    with httpx.Client(timeout=args.timeout) as client:
        for question in questions:
            try:
                reponse, latence_ms = _appeler(
                    client,
                    args.base_url,
                    args.token,
                    question["question"],
                    sans_cache=args.sans_cache,
                )
                resultat = evaluer_reponse(question, reponse, latence_ms)
            except Exception as exc:
                print(f"{question['id']}: erreur {exc}", file=sys.stderr)
                resultat = {
                    "id": question["id"],
                    "type": question.get("type", "rag"),
                    "question": question["question"],
                    "reponse": "",
                    "sources": [],
                    "fidelite": False,
                    "citation": None if not question.get("sources_attendues") else False,
                    "valeur": None if not question.get("attendu_contient") else False,
                    "latence_ms": 0.0,
                    "tokens_entree": 0,
                    "tokens_sortie": 0,
                    "tokens": 0,
                    "cache_semantique": False,
                    "erreur": str(exc),
                }
            resultats.append(resultat)

    _imprimer_tableau(resultats)

    total = len(resultats)
    ok_fidelite = sum(1 for r in resultats if r["fidelite"])
    applicables_citation = [r for r in resultats if r["citation"] is not None]
    ok_citation = sum(1 for r in applicables_citation if r["citation"])
    applicables_valeur = [r for r in resultats if r["valeur"] is not None]
    ok_valeur = sum(1 for r in applicables_valeur if r["valeur"])

    latences = [r["latence_ms"] for r in resultats if r["latence_ms"] > 0]
    total_entree = sum(r["tokens_entree"] for r in resultats)
    total_sortie = sum(r["tokens_sortie"] for r in resultats)
    total_tokens = total_entree + total_sortie
    cache_hits = sum(1 for r in resultats if r["cache_semantique"])
    prix = cout_par_million_depuis_env()
    cout = estimer_cout(total_tokens, prix)

    taux_fidelite = _taux(ok_fidelite, total)
    taux_citation = _taux(ok_citation, len(applicables_citation))
    taux_valeur = _taux(ok_valeur, len(applicables_valeur))

    print("\nResume")
    print(f"  Fidelite          : {ok_fidelite}/{total} = {taux_fidelite:.2f}")
    print(
        f"  Citation          : {ok_citation}/{len(applicables_citation)} = {taux_citation:.2f}"
        " (questions sans source attendue exclues)"
    )
    print(f"  Exactitude valeurs: {ok_valeur}/{len(applicables_valeur)} = {taux_valeur:.2f}")
    print(
        f"  Latence p50/p95   : {percentile(latences, 50):.1f} / {percentile(latences, 95):.1f} ms"
    )
    print(f"  Tokens entree     : {total_entree}")
    print(f"  Tokens sortie     : {total_sortie}")
    print(f"  Tokens total      : {total_tokens} (entree + sortie)")
    print(
        f"  Cout estime       : {cout:.4f} USD "
        f"({prix:.2f} USD / million, entree + sortie, estimation)"
    )
    print(f"  Cache succes      : {cache_hits} (reponses servies du cache : aucun token, cout nul)")

    resume = {
        "total_questions": total,
        "fidelite": taux_fidelite,
        "fidelite_ok": ok_fidelite,
        "citation": taux_citation,
        "citation_ok": ok_citation,
        "citation_questions": len(applicables_citation),
        "valeur": taux_valeur,
        "valeur_ok": ok_valeur,
        "valeur_questions": len(applicables_valeur),
        "latence_p50_ms": round(percentile(latences, 50), 2),
        "latence_p95_ms": round(percentile(latences, 95), 2),
        "tokens_entree": total_entree,
        "tokens_sortie": total_sortie,
        "tokens_total": total_tokens,
        "cache_hits": cache_hits,
        "cout_estime_usd": cout,
        "cout_par_million_usd": prix,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"resume": resume, "questions": resultats}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nResultats ecrits dans {args.output}")

    if args.ci and not respecte_seuils_ci(
        taux_fidelite,
        taux_citation,
        taux_valeur,
        citation_questions=len(applicables_citation),
        valeur_questions=len(applicables_valeur),
    ):
        print("\nSeuils CI non atteints.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
