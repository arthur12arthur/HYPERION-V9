"""
HYPERION V9 — Logger
Logging structuré avec niveaux, fichiers rotatifs et formatage console.
"""
import logging
import logging.handlers
import os
from datetime import datetime


def setup_logger(name: str = "hyperion", log_level: str = "INFO") -> logging.Logger:
    """
    Configure et retourne le logger principal HYPERION.
    Écrit dans la console ET dans un fichier rotatif (backup/).
    """
    logger = logging.getLogger(name)

    # Éviter la duplication de handlers si déjà configuré
    if logger.handlers:
        return logger

    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # Format des messages
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler fichier rotatif (backup/logs/)
    log_dir = os.path.join(os.path.dirname(__file__), "..", "backup", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"hyperion_{datetime.now().strftime('%Y-%m-%d')}.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=7,
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(module_name: str) -> logging.Logger:
    """
    Retourne un logger enfant pour un module spécifique.
    Usage : logger = get_logger(__name__)
    """
    return logging.getLogger(f"hyperion.{module_name}")


# Logger racine HYPERION — initialisé au démarrage
root_logger = setup_logger()
