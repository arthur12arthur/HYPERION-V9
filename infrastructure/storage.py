"""
HYPERION V9 — Storage local
Gestion des fichiers backup et logs locaux.
"""
import os
import json
from typing import Any
from utils.logger import get_logger

logger = get_logger(__name__)

BACKUP_DIR = "./backup"


def ensure_dirs():
    """Crée les dossiers backup si nécessaire."""
    for subdir in ["predictions", "results", "logs", "pipeline_runs"]:
        os.makedirs(os.path.join(BACKUP_DIR, subdir), exist_ok=True)


def save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_json(path: str) -> Any:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


ensure_dirs()
