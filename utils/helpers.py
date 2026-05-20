"""
HYPERION V9 — Helpers utilitaires
Fonctions partagées entre tous les modules.
"""
import json
import uuid
import hashlib
from datetime import datetime, date
from typing import Any, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


def generate_run_id() -> str:
    """Génère un ID unique pour un run pipeline."""
    return f"run_{uuid.uuid4().hex[:8]}"


def generate_doc_id(date_str: str, course_id: str) -> str:
    """Génère un ID de document Firebase."""
    return f"{date_str}_{course_id}"


def today_str() -> str:
    """Date du jour au format YYYY-MM-DD (timezone Ouagadougou)."""
    return date.today().isoformat()


def now_iso() -> str:
    """Timestamp ISO 8601 actuel."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_json_loads(text: str, default: Any = None) -> Any:
    """JSON parse sécurisé — retourne default si échec."""
    if not text:
        return default
    # Nettoyer les balises markdown éventuelles
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e} — texte: {clean[:100]}")
        return default


def escape_markdown_v2(text: str) -> str:
    """
    Échappe les caractères spéciaux pour Telegram MarkdownV2.
    Obligatoire avant d'envoyer tout texte dynamique.
    """
    special_chars = r'_*[]()~`>#+-=|{}.!'
    result = ""
    for char in str(text):
        if char in special_chars:
            result += f"\\{char}"
        else:
            result += char
    return result


def stars_from_confidence(confidence: float) -> str:
    """Convertit un score de confiance en étoiles."""
    if confidence >= 0.80:
        return "⭐⭐⭐"
    elif confidence >= 0.60:
        return "⭐⭐"
    else:
        return "⭐"


def format_fcfa(amount: float) -> str:
    """Formate un montant en FCFA lisible."""
    return f"{int(amount):,} FCFA".replace(",", " ")


def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    """Division sécurisée — retourne default si b == 0."""
    return a / b if b != 0 else default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Borne une valeur entre min et max."""
    return max(min_val, min(max_val, value))


def truncate_message(text: str, max_length: int = 4096) -> str:
    """Tronque un message Telegram si trop long."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 20] + "\n_\\[message tronqué\\]_"


def hash_content(content: str) -> str:
    """Hash MD5 d'un contenu — pour détecter les doublons."""
    return hashlib.md5(content.encode()).hexdigest()[:12]
