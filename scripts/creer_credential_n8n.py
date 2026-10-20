#!/usr/bin/env python3
"""Cree une credential n8n par la CLI, chiffree comme n8n l'attend.

Pourquoi ce script
-----------------
`n8n import:credentials` n'attend pas du JSON en clair : la colonne `data` est
CHIFFREE dans la base, avec la cle de l'instance (`N8N_ENCRYPTION_KEY`). Un
import en clair echoue au premier dechiffrement (« wrong final block length »),
et l'erreur ne parle que de cryptographie.

La CLI n'a pas de mode « JSON en clair ». On reproduit donc son chiffrement :
le format OpenSSL `Salted__`, MD5, AES-256-CBC -- exactement ce que fait
`n8n-core/dist/encryption/aes-256-cbc.js`.

Usage :
    python3 scripts/creer-credential-n8n.py --nom "Mailpit (dev)" --type smtp \\
        --donnees '{"host": "mailpit", "port": 1025, ...}'

La credential creee n'est PAS versionnee : `apps/n8n/credentials/` est
ignore par Git. Le JSON importe est ecrit dans ce dossier, puis la CLI
l'importe.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "apps" / "n8n" / "credentials"
PREFIXE = b"Salted__"


def _chiffrer(donnees: str, cle: str) -> str:
    """Chiffre comme n8n : OpenSSL EVP_BytesToKey (MD5) + AES-256-CBC."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    sel = os.urandom(8)
    mot_de_passe = cle.encode("latin-1") + sel
    empreinte1 = hashlib.md5(mot_de_passe).digest()
    empreinte2 = hashlib.md5(empreinte1 + mot_de_passe).digest()
    iv = hashlib.md5(empreinte2 + mot_de_passe).digest()
    cle_derivee = empreinte1 + empreinte2
    # Node remplit avec PKCS#7 : Python ne le fait pas.
    brut = donnees.encode("utf-8")
    remplissage = 16 - (len(brut) % 16)
    brut += bytes([remplissage]) * remplissage
    chiffreur = Cipher(algorithms.AES(cle_derivee), modes.CBC(iv)).encryptor()
    chiffre = chiffreur.update(brut) + chiffreur.finalize()
    return base64.b64encode(PREFIXE + sel + chiffre).decode("ascii")


def _cle_instance() -> str:
    for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
        if ligne.startswith("N8N_ENCRYPTION_KEY="):
            return ligne.split("=", 1)[1].strip()
    raise SystemExit("N8N_ENCRYPTION_KEY introuvable dans .env.")


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "--nom", required=True, help="Nom de la credential (celui reference par le workflow)."
    )
    parseur.add_argument("--type", required=True, help="Type n8n : smtp, slack, openAiApi...")
    parseur.add_argument("--donnees", required=True, help="Donnees de la credential, en JSON.")
    parseur.add_argument(
        "--id", default=None, help="Identifiant impose (celui reference par le workflow)."
    )
    arguments = parseur.parse_args()

    donnees = json.loads(arguments.donnees)
    payload = {
        "name": arguments.nom,
        "type": arguments.type,
        "data": _chiffrer(json.dumps(donnees), _cle_instance()),
    }
    if arguments.id:
        payload["id"] = arguments.id

    DOSSIER.mkdir(parents=True, exist_ok=True)
    fichier = DOSSIER / "a- importer.json"
    fichier.write_text(json.dumps([payload], ensure_ascii=False, indent=2), encoding="utf-8")
    fichier.chmod(0o600)
    print(f"Fichier d'import ecrit : {fichier}")

    conteneur = os.environ.get("N8N_CONTENEUR", "predicare-n8n")
    destination = "/tmp/cred-import"
    subprocess.run(["docker", "exec", conteneur, "rm", "-rf", destination], check=False)
    subprocess.run(["docker", "exec", conteneur, "mkdir", "-p", destination], check=True)
    subprocess.run(
        ["docker", "cp", str(fichier), f"{conteneur}:{destination}/cred.json"], check=True
    )
    resultat = subprocess.run(
        [
            "docker",
            "exec",
            conteneur,
            "n8n",
            "import:credentials",
            "--separate",
            f"--input={destination}",
        ],
        capture_output=True,
        text=True,
    )
    sortie = (resultat.stdout + resultat.stderr).strip().splitlines()
    for ligne in sortie[-3:]:
        print(f"  {ligne}")
    fichier.unlink(missing_ok=True)
    return resultat.returncode


if __name__ == "__main__":
    raise SystemExit(main())
