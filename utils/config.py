"""
HYPERION V9 — Chargeur de configuration YAML
Charge tous les fichiers config/ et expose un objet AppConfig global.
"""
import os
import yaml
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_yaml(filename: str) -> dict:
    """Charge un fichier YAML depuis config/"""
    path = CONFIG_DIR / filename
    if not path.exists():
        logger.warning(f"Config introuvable : {path} — valeurs par défaut utilisées")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    logger.debug(f"Config chargée : {filename}")
    return data


class AppConfig:
    """Configuration globale HYPERION — singleton."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        self.app      = load_yaml("app.yaml")
        self.scoring  = load_yaml("scoring.yaml")
        self.gemini   = load_yaml("gemini.yaml")
        self.hades    = load_yaml("hades.yaml")
        self.finance  = load_yaml("finance.yaml")
        self.sources  = load_yaml("sources.yaml")
        logger.info("Configuration HYPERION V9 chargée")

    def reload(self):
        """Recharge tous les fichiers YAML (utile pour tests)."""
        AppConfig._instance = None
        self._load()

    # Helpers pratiques
    @property
    def timezone(self) -> str:
        return self.app.get("timezone", "Africa/Ouagadougou")

    @property
    def max_courses(self) -> int:
        return self.app.get("max_courses_per_day", 10)

    @property
    def scoring_weights(self) -> dict:
        return self.scoring.get("weights", {
            "historique": 0.35, "forme": 0.25, "terrain": 0.20,
            "handicap": 0.10, "fraicheur": 0.10
        })

    @property
    def mc_simulations(self) -> int:
        return self.scoring.get("monte_carlo", {}).get("simulations", 10000)

    @property
    def mc_variantes(self) -> int:
        return self.scoring.get("monte_carlo", {}).get("variantes", 5)

    @property
    def mc_sigma(self) -> float:
        return self.scoring.get("monte_carlo", {}).get("sigma_noise", 0.15)

    @property
    def borda_threshold(self) -> float:
        return self.scoring.get("consensus", {}).get("borda_threshold", 0.80)

    @property
    def hades_mode_test(self) -> bool:
        return self.hades.get("mode_test", True)

    @property
    def kelly_fraction(self) -> float:
        return self.finance.get("kelly_fraction", 0.25)

    @property
    def kelly_max_pct(self) -> float:
        return self.finance.get("kelly_max_pct", 0.05)

    @property
    def ev_threshold(self) -> float:
        return self.finance.get("ev_threshold", 0.05)

    @property
    def capital_reference(self) -> float:
        return self.finance.get("capital_reference", 100000.0)

    @property
    def gemini_daily_quota(self) -> int:
        return self.gemini.get("daily_quota_per_key", 24)

    @property
    def lonab_url(self) -> str:
        return self.sources.get("lonab", {}).get("url", "https://www.lonab.bf")

    @property
    def pmu_base_url(self) -> str:
        return self.sources.get("pmu", {}).get("url", "https://www.pmu.fr")

    def load_prompt(self, name: str) -> str:
        """Charge un prompt depuis config/prompts/"""
        path = CONFIG_DIR / "prompts" / f"{name}.txt"
        if not path.exists():
            logger.warning(f"Prompt introuvable : {name}.txt")
            return ""
        return path.read_text(encoding="utf-8").strip()


# Instance globale
config = AppConfig()
