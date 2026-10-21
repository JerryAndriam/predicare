"""Contrat JSON des workflows n8n, sans pile ni base.

Ces tests ne remplacent pas la preuve de bout en bout (`make e2e-n8n`) : ils
verrouillent ce qui peut casser silencieusement dans un fichier versionne —
un noeud renomme, une branche d'erreur debranchee, un secret colle dans le
JSON. Ils tournent dans `make test` et dans la CI, sans Docker.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "apps" / "n8n" / "workflows"

#: Un secret colle dans un workflow exporte serait visible dans Git.
SECRETS = re.compile(
    r"hooks\.slack\.com"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
)


def charger(nom: str) -> dict:
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


def noms(workflow: dict) -> set[str]:
    return {noeud["name"] for noeud in workflow["nodes"]}


def liens(workflow: dict) -> list[tuple[str, int, str]]:
    """Tous les liens (source, index de sortie, cible), tous types confondus."""
    resultat = []
    for source, sorties in workflow["connections"].items():
        for branches in sorties.values():
            for index, branche in enumerate(branches):
                for lien in branche or []:
                    resultat.append((source, index, lien["node"]))
    return resultat


def noeud(workflow: dict, nom: str) -> dict:
    for candidat in workflow["nodes"]:
        if candidat["name"] == nom:
            return candidat
    raise AssertionError(f"noeud absent : {nom}")


@pytest.fixture(scope="module")
def alerte() -> dict:
    return charger("PK-Alerte-Fraude.json")


@pytest.fixture(scope="module")
def bascule() -> dict:
    return charger("PK-Bascule-Modele.json")


# ---------------------------------------------------------------------------
# Structure commune
# ---------------------------------------------------------------------------
def test_tous_les_workflows_sont_structurellement_valides() -> None:
    fichiers = sorted(DOSSIER.glob("*.json"))
    assert fichiers, "aucun workflow versionne"

    for fichier in fichiers:
        workflow = json.loads(fichier.read_text(encoding="utf-8"))
        assert workflow.get("name"), fichier
        assert workflow.get("nodes"), fichier
        assert workflow.get("connections") is not None, fichier

        ids = [noeud["id"] for noeud in workflow["nodes"]]
        assert len(ids) == len(set(ids)), f"identifiants de noeud dupliques : {fichier}"

        for source, _, cible in liens(workflow):
            assert source in noms(workflow), f"{fichier}: source inconnue {source}"
            assert cible in noms(workflow), f"{fichier}: cible inconnue {cible}"


def test_aucun_secret_dans_les_workflows() -> None:
    for fichier in sorted(DOSSIER.glob("*.json")):
        contenu = fichier.read_text(encoding="utf-8")
        assert not SECRETS.search(contenu), f"secret en clair dans {fichier}"


def test_les_noeuds_http_declarent_une_politique_d_erreur() -> None:
    for fichier in sorted(DOSSIER.glob("*.json")):
        workflow = json.loads(fichier.read_text(encoding="utf-8"))
        for noeud_http in (n for n in workflow["nodes"] if n["type"].endswith("httpRequest")):
            assert noeud_http.get("onError") in {
                "continueRegularOutput",
                "continueErrorOutput",
            }, f"{fichier}: {noeud_http['name']} sans politique d'erreur"


# ---------------------------------------------------------------------------
# Chaine d'alerte
# ---------------------------------------------------------------------------
def test_alerte_webhook_repond_par_un_noeud_dedie(alerte: dict) -> None:
    webhook = noeud(alerte, "Webhook entree")
    assert webhook["parameters"]["responseMode"] == "responseNode"
    assert ("Webhook entree", 0, "Invoquer l'API d'inference") in liens(alerte)


def test_alerte_une_panne_d_inference_est_une_erreur_explicite(alerte: dict) -> None:
    inference = noeud(alerte, "Invoquer l'API d'inference")
    assert inference["onError"] == "continueErrorOutput"
    assert "neverError" not in json.dumps(inference["parameters"]), (
        "neverError transformerait un 422/500 en succes silencieux"
    )
    assert ("Invoquer l'API d'inference", 1, "Repondre echec inference") in liens(alerte)
    assert ("Repondre echec inference", 0, "Inference indisponible") in liens(alerte)
    assert noeud(alerte, "Inference indisponible")["type"].endswith("stopAndError")


def test_alerte_repond_le_score_avant_les_notifications(alerte: dict) -> None:
    assert ("Invoquer l'API d'inference", 0, "Repondre au client") in liens(alerte)
    assert ("Repondre au client", 0, "Score au-dessus du seuil de notification") in liens(alerte)


def test_alerte_le_message_slack_contient_le_rapport_shap(alerte: dict) -> None:
    slack = noeud(alerte, "Notifier Slack")
    assert "$env.SLACK_WEBHOOK_URL" in slack["parameters"]["url"]
    assert "rapport_shap" in slack["parameters"]["body"]
    assert slack["parameters"]["body"].lstrip().startswith("={{")
    assert any("$env.SEUIL_NOTIFICATION_SLACK" in str(v) for v in slack["parameters"].values())


def test_alerte_l_email_contient_le_rapport_shap(alerte: dict) -> None:
    email = noeud(alerte, "Notifier par e-mail")
    assert "rapport_shap" in email["parameters"]["text"]
    assert "$env.SMTP_FROM" in email["parameters"]["fromEmail"]
    assert "$env.SMTP_GESTIONNAIRE" in email["parameters"]["toEmail"]
    assert email["credentials"]["smtp"]["name"] == "Mailpit (dev)"


def test_alerte_un_echec_de_notification_est_journalise(alerte: dict) -> None:
    assert ("Notifier par e-mail", 0, "Notification en echec ?") in liens(alerte)
    assert ("Notification en echec ?", 0, "Notification en echec") in liens(alerte)
    assert ("Notification en echec ?", 1, "Notifications envoyees") in liens(alerte)
    assert noeud(alerte, "Notification en echec")["type"].endswith("stopAndError")


def test_alerte_une_facture_sous_le_seuil_n_est_pas_notifiee(alerte: dict) -> None:
    assert (
        "Score au-dessus du seuil de notification",
        1,
        "Sous le seuil de notification",
    ) in liens(alerte)
    sous_seuil = noeud(alerte, "Sous le seuil de notification")
    assert sous_seuil["type"].endswith("noOp")
    assert ("Sous le seuil de notification", 0) not in {
        (source, index) for source, index, _ in liens(alerte)
    }


# ---------------------------------------------------------------------------
# Bascule de modele
# ---------------------------------------------------------------------------
def test_bascule_webhook_et_validation(bascule: dict) -> None:
    webhook = noeud(bascule, "Webhook bascule")
    assert webhook["parameters"]["path"] == "bascule-modele"
    assert webhook["parameters"]["responseMode"] == "responseNode"

    validation = noeud(bascule, "Valider la bascule")
    assert "version_apres" in json.dumps(validation["parameters"])
    assert ("Valider la bascule", 0, "Repondre OK") in liens(bascule)
    assert ("Valider la bascule", 1, "Repondre 422") in liens(bascule)


def test_bascule_repond_avant_de_notifier(bascule: dict) -> None:
    assert ("Repondre OK", 0, "Notifier Slack bascule") in liens(bascule)
    assert ("Notifier Slack bascule", 0, "Notifier par e-mail bascule") in liens(bascule)


def test_bascule_les_deux_canaux_nomment_les_versions(bascule: dict) -> None:
    slack = noeud(bascule, "Notifier Slack bascule")
    email = noeud(bascule, "Notifier par e-mail bascule")
    for noeud_notification in (slack, email):
        charge = json.dumps(noeud_notification["parameters"])
        assert "version_avant" in charge
        assert "version_apres" in charge
        assert "acteur" in charge

    assert "$env.SLACK_WEBHOOK_URL" in slack["parameters"]["url"]
    assert "$env.SMTP_FROM" in email["parameters"]["fromEmail"]
    assert email["credentials"]["smtp"]["name"] == "Mailpit (dev)"


def test_bascule_un_echec_de_notification_est_journalise(bascule: dict) -> None:
    assert (
        "Notifier par e-mail bascule",
        0,
        "Notification en echec ?",
    ) in liens(bascule)
    assert ("Notification en echec ?", 0, "Notification en echec") in liens(bascule)
    assert ("Notification en echec ?", 1, "Notifications envoyees") in liens(bascule)
    assert noeud(bascule, "Notification en echec")["type"].endswith("stopAndError")
