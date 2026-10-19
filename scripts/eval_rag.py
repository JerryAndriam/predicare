"""Evaluation de la fidelite du RAG sur le jeu de questions de reference.

Usage :
    python scripts/eval_rag.py --base-url http://localhost:8003 --token <JWT>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

FICHIER = Path(__file__).resolve().parents[1] / "tests" / "rag_reference" / "questions.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8003")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    questions = json.loads(FICHIER.read_text(encoding="utf-8"))
    ok_fidelite = 0
    ok_citation = 0
    for q in questions:
        reponse = httpx.post(
            f"{args.base_url}/api/rag/question",
            headers={"Authorization": f"Bearer {args.token}"},
            json={"question": q["question"]},
            timeout=30.0,
        ).json()
        texte = (reponse.get("reponse") or "").lower()
        sources = reponse.get("sources") or []
        fidelite = all(m.lower() in texte for m in q["mots_cles"])
        citation = any(
            s.get("contrat") in (src for src in q["sources_attendues"])
            or any(src in str(s) for src in q["sources_attendues"])
            for s in sources
        )
        ok_fidelite += int(fidelite)
        ok_citation += int(citation)
        print(f"{q['id']}: fidelite={fidelite} citation={citation}")

    n = len(questions)
    print(f"Fidelite : {ok_fidelite}/{n} = {ok_fidelite/n:.2f}")
    print(f"Citation : {ok_citation}/{n} = {ok_citation/n:.2f}")


if __name__ == "__main__":
    main()