"""Configuration centralisee, lue depuis l'environnement ou le fichier .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Toutes les valeurs comes de variables d'environnement.

    Une variable absente ne doit pas bloquer le demarrage du conteneur de
    sante : on fournit donc une valeur par defaut et on signale explicitement
    les secrets non configures au lieu de planter.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Projet
    app_name: str = "predicare"
    environment: str = "development"
    log_level: str = "INFO"
    log_format: str = Field(default="json", alias="API_LOG_FORMAT")

    # Base de donnees.
    # `alias` explicite : sans lui, pydantic-settings chercherait la variable
    # `DB_URL`. Le service demarrerait alors avec une URL sans mot de passe
    # et echouerait a la premiere connexion, sans que la cause soit lisible.
    db_url: str = Field(
        default="postgresql+psycopg://predicare@db:5432/predicare",
        alias="PREDICARE_DB_URL",
    )
    db_ro_url: str = Field(default="", alias="PREDICARE_DB_RO_URL")
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Securite
    app_secret_key: str = "dev-only-change-me"
    jwt_secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    identity_encryption_key: str = ""

    # Metier
    #: Seuil d'alerte. `None` (variable vide) signifie « adopter le seuil
    #: arbitre par le modele » (Phase 2.5) : le service lit `metadata.json` au
    #: chargement. Une valeur explicite reste prioritaire et sert l'ecran
    #: d'administration, qui doit pouvoir imposer un seuil sans reentrainer.
    fraud_alert_threshold: float | None = None
    fraud_min_recall: float = 0.90
    cors_origins: str = "http://localhost:8080"

    # Modele ML
    model_dir: str = "/models"
    model_active_version: int = 1
    model_candidate_version: int | None = None
    drift_window_days: int = 30
    drift_ks_threshold: float = 0.10

    # RAG
    embedding_dimension: int = 1536
    rag_top_k: int = 6
    rag_similarity_threshold: float = 0.55
    rag_max_agent_steps: int = 8
    semantic_cache_threshold: float = 0.95
    semantic_cache_ttl_seconds: int = 86400

    # LLM (jamais en clair dans le code)
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 800
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    # Canaux de notification, affiches par l'ecran d'administration.
    slack_webhook_url: str = ""
    smtp_from: str = ""

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("model_candidate_version", "fraud_alert_threshold", mode="before")
    @classmethod
    def _vide_vers_none(cls, value: object) -> object:
        """Une variable vide dans un `.env` signifie « aucune » / « par defaut ».

        `MODEL_CANDIDATE_VERSION=` : aucune candidate. `FRAUD_ALERT_THRESHOLD=` :
        adopter le seuil du modele. Sans ce convertisseur, pydantic refuse la
        chaine vide et le service ne demarre pas. Or c'est exactement ce
        qu'ecrit un administrateur lorsqu'il vide un champ avant de le remplir.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def missing_secrets(self) -> list[str]:
        """Liste les secrets encore a l'etat du modele. Alimente /health."""
        if self.is_production:
            return []
        placeholders = {
            "app_secret_key": self.app_secret_key,
            "jwt_secret_key": self.jwt_secret_key,
        }
        return [name for name, value in placeholders.items() if "change-me" in value or not value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings mis en cache : une seule instance par processus."""
    return Settings()


def reset_settings_cache() -> None:
    """Utilise par les tests pour recharger une configuration."""
    get_settings.cache_clear()
