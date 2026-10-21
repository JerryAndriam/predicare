"""Journalisation MLflow par son API REST, sans le paquet `mlflow`.

Pourquoi pas le SDK : il pese environ 200 Mo dans une image qui sert aussi
l'inference, et il evolue plus vite que le serveur qu'il interroge. Le job
d'entrainement n'a besoin que de QUATRE points d'entree stables de l'API 2.0 :
creer l'experience, creer le run, journaliser par lot, cloturer le run. Les
appeler avec `httpx` (deja dans le socle, ADR-004) suffit, et l'image reste
legere.

Pourquoi si peu de couplage : MLflow est un outil de SUIVI, jamais un chemin
d'inference. Le profil `mlops` peut etre arrete pendant la soutenance sans que
la detection cesse de fonctionner. Ce module ne decore donc pas l'echec : il
LEVE, et c'est l'appelant (`train._journaliser_mlflow`) qui decide qu'un
serveur de suivi injoignable ne fait pas echouer un entrainement complet.
"""

from __future__ import annotations

import time

import httpx

#: Nom de l'experience creee si elle n'existe pas encore.
EXPERIENCE_PAR_DEFAUT = "predicare-detection-fraude"

#: Un serveur de suivi lent ne doit pas immobiliser le job : au-dela, on
#: considere qu'il est injoignable. `make train` dure une vingtaine de
#: minutes ; dix secondes de patience par appel sont deja genereuses.
DELAI_PAR_DEFAUT = 10.0


class JournalisationImpossibleError(RuntimeError):
    """Le serveur MLflow n'a pas accepte une des etapes de la journalisation."""


def _lire(reponse: httpx.Response, chemin: str) -> dict:
    try:
        return reponse.json()
    except ValueError as exc:  # reponse non JSON : serveur intermediaire ?
        raise JournalisationImpossibleError(
            f"Reponse illisible de MLflow sur {chemin} : {reponse.text[:200]}"
        ) from exc


def _poster(client: httpx.Client, chemin: str, corps: dict) -> dict:
    reponse = client.post(chemin, json=corps)
    if reponse.status_code >= 400:
        raise JournalisationImpossibleError(
            f"MLflow a repondu {reponse.status_code} sur {chemin} : {reponse.text[:200]}"
        )
    return _lire(reponse, chemin)


def _identifier_experience(client: httpx.Client, nom: str) -> str:
    """Rend l'identifiant de l'experience, en la creant a la premiere execution.

    Le point d'entree « get-or-create » n'existe plus dans l'API 2.0 (il
    repond 404) : la creation se fait en deux temps, et une creation
    concurrente n'est pas une erreur -- on relit simplement l'experience.

    Troisieme cas, rencontre en vrai : l'experience existe mais a ete
    SUPPRIMEE depuis l'interface (etat `deleted`). La retrouver par son nom
    n'est alors pas suffisant : MLflow refuse d'y creer un run (400). Une
    suppression est reversible dans MLflow ; on la restaure donc, plutot que
    de laisser l'entrainement se terminer sans suivi.
    """
    reponse = client.get("/api/2.0/mlflow/experiments/get-by-name", params={"experiment_name": nom})
    if reponse.status_code == 200:
        experience_trouvee = _lire(reponse, "get-by-name")["experiment"]
        identifiant = experience_trouvee["experiment_id"]
        if experience_trouvee.get("lifecycle_stage") == "deleted":
            _poster(
                client,
                "/api/2.0/mlflow/experiments/restore",
                {"experiment_id": identifiant},
            )
        return identifiant

    creation = client.post("/api/2.0/mlflow/experiments/create", json={"name": nom})
    if creation.status_code >= 400:
        # Course perdue contre une autre execution : l'experience existe
        # maintenant, et c'est tout ce qui compte.
        relance = client.get(
            "/api/2.0/mlflow/experiments/get-by-name", params={"experiment_name": nom}
        )
        if relance.status_code == 200:
            return _lire(relance, "get-by-name")["experiment"]["experiment_id"]
        raise JournalisationImpossibleError(
            f"MLflow a refuse de creer l'experience {nom!r} : "
            f"{creation.status_code} {creation.text[:200]}"
        )
    return _lire(creation, "experiments/create")["experiment_id"]


def journaliser(
    uri: str,
    run_name: str,
    params: dict[str, object],
    metrics: dict[str, float],
    *,
    experience: str = EXPERIENCE_PAR_DEFAUT,
    client: httpx.Client | None = None,
) -> str:
    """Ecrit un run complet dans MLflow et rend son identifiant.

    `client` sert aux tests : on peut injecter un transport simule plutot que
    de dependre d'un vrai serveur dans la suite unitaire.

    Leve `JournalisationImpossibleError` (ou une erreur `httpx`) si le serveur
    est injoignable : l'appelant decide si c'est fatal, ici ce ne l'est jamais.
    """
    horodatage_ms = int(time.time() * 1000)
    externe = client is None
    if client is None:
        client = httpx.Client(base_url=uri.rstrip("/"), timeout=DELAI_PAR_DEFAUT)

    try:
        experience_id = _identifier_experience(client, experience)

        run_id = _poster(
            client,
            "/api/2.0/mlflow/runs/create",
            {
                "experiment_id": experience_id,
                "run_name": run_name,
                "start_time": horodatage_ms,
                # Le nom du run porte la version : c'est ce que l'exploitant
                # cherche dans l'interface quand il compare deux entrainements.
                "tags": [{"key": "predicare.version", "value": run_name}],
            },
        )["run"]["info"]["run_id"]

        _poster(
            client,
            "/api/2.0/mlflow/runs/log-batch",
            {
                "run_id": run_id,
                # Les parametres sont des chaines dans l'API MLflow : convertir
                # ici evite un 400 decouvert seulement en production.
                "params": [{"key": cle, "value": str(valeur)} for cle, valeur in params.items()],
                "metrics": [
                    {
                        "key": cle,
                        "value": float(valeur),
                        "timestamp": horodatage_ms,
                        "step": 0,
                    }
                    for cle, valeur in metrics.items()
                ],
            },
        )

        _poster(
            client,
            "/api/2.0/mlflow/runs/update",
            {"run_id": run_id, "status": "FINISHED", "end_time": horodatage_ms},
        )
        return run_id
    finally:
        if externe:
            client.close()
