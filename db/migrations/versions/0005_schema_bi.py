"""Schema `bi` : couche semantique du pilotage decisionnel.

Pourquoi un schema dedie
-------------------------
Les vues de pilotage ne sont pas des donnees metier : ce sont des lectures
agregees destinees a une seule audience, la direction. Les melanger dans
`core` rendrait leurs colonnes indiscernables de celles alimentees par les
API, et surtout rendrait impossible de les retirer quand Superset n'est plus
utilise.

Un schema dedie rend la frontiere explicite, et permet un droit d'acces
propre : `superset_ro` recoit `USAGE` sur `bi` sans que cela modifie ses
droits sur les tables metier.

Ce que ce schema ne doit PAS contenir
-------------------------------------
Aucune vue de `bi` ne lit le schema `audit`. La migration 0002 retire
deliberement a `superset_ro` tout acces a `audit` : le tableau de bord doit
pouvoir mesurer la performance, pas consulter qui a fait quoi.

Deux datasets registraient pourtant une jointure sur
`audit.decision_gestionnaire`, et echouaient donc en production avec
« permission denied for schema audit ». Les vues de remplacement calculent le
delai de traitement depuis `core.facture.date_reception` et
`core.facture.date_traitement`, qui portent la meme information sans franchir
la frontiere.

Vues ou pas dans la migration
----------------------------
Les VUES ne sont pas creees ici, volontairement. Elles sont dans
`db/bi/views/*.sql` et appliquees par `CREATE OR REPLACE VIEW`.

Un indicateur change dix fois plus souvent qu'un schema. Loger chaque retouche
de libelle ou de formule dans Alembic obligerait a ecrire une migration a
chaque fois, ce qui decourage de corriger et laisse les indicateurs vieillir.
Les vues restent versionnees dans Git et rejouables sur une machine vierge,
mais modifiables sans migration.

Seuls le schema et les droits, qui sont du DDL de structure, sont versionnes
ici.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_schema_bi"
down_revision = "0004_referentiels"
branch_labels = None
depends_on = None


#: Role auquel la couche semantique est lisible. Cree par la migration 0002,
#: en lecture seule stricte : le tableau de bord ne peut pas modifier une
#: donnee metier, meme par une requete erronee.
ROLE_BI = "superset_ro"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS bi")

    # `USAGE` seul : lire les vues suppose avoir le droit de les lire, pas
    # d'ecrire dans le schema. Superset n'a besoin de `USAGE` que parce que
    # la connexion est configuree avec un role applicatif qui n'est pas le
    # proprietaire.
    op.execute(f"GRANT USAGE ON SCHEMA bi TO {ROLE_BI}")

    # Les privileges sur les tables elles-memes sont accordes par le script
    # de chargement des vues (`db/bi/views/`), avec `CREATE OR REPLACE VIEW`,
    # pour qu'un ajout de vue soit pris en compte sans migration.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA bi GRANT SELECT ON TABLES TO {ROLE_BI}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON SCHEMA bi FROM {ROLE_BI}")
    op.execute("DROP SCHEMA IF EXISTS bi CASCADE")
