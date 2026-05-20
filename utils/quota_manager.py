"""
HYPERION V9 — GeminiKeyRotator
Rotation automatique de 2 clés Gemini avec suivi quota Firebase.
"""
import os
import logging
from datetime import date
from utils.logger import get_logger

logger = get_logger(__name__)


class QuotaExceededError(Exception):
    pass

class APIError(Exception):
    pass

class AllKeysExhaustedError(Exception):
    pass


class GeminiKeyRotator:
    """
    Rotation automatique des clés Gemini.
    Transparent pour tous les agents — ils appellent call_gemini()
    sans savoir quelle clé est active.
    """

    DAILY_QUOTA = int(os.getenv("GEMINI_DAILY_QUOTA", "24"))

    def __init__(self):
        self.keys = [
            {"id": "KEY1", "value": os.getenv("GEMINI_API_KEY_1"), "calls": 0, "active": True},
            {"id": "KEY2", "value": os.getenv("GEMINI_API_KEY_2"), "calls": 0, "active": True},
        ]
        self.current = 0
        self._last_reset_date = date.today().isoformat()
        self._telegram_alerter = None  # injecté par le pipeline

    def set_telegram_alerter(self, alerter):
        """Injecte le module d'alerte Telegram (évite import circulaire)."""
        self._telegram_alerter = alerter

    def _alert(self, message: str):
        logger.warning(message)
        if self._telegram_alerter:
            try:
                self._telegram_alerter.send_alert(message)
            except Exception:
                pass

    def can_use(self, n: int = 1) -> bool:
        """Vérifie si on peut encore faire n appels sans dépasser le quota."""
        self._auto_reset_if_new_day()
        total_used = sum(k["calls"] for k in self.keys)
        total_budget = self.DAILY_QUOTA * len(self.keys)
        return (total_used + n) <= total_budget

    def call_gemini(self, prompt: str, system: str = "", **kwargs) -> str:
        """
        Appel Gemini avec rotation automatique.
        Essaie la clé active, bascule si nécessaire.
        """
        self._auto_reset_if_new_day()

        if not self.can_use(1):
            self._alert("🔴 Budget Gemini total épuisé — mode template activé")
            raise AllKeysExhaustedError("Budget total épuisé")

        for attempt in range(len(self.keys)):
            key = self.keys[self.current]

            if not key["active"]:
                self.current = (self.current + 1) % len(self.keys)
                continue

            if key["calls"] >= self.DAILY_QUOTA:
                key["active"] = False
                self._switch_key("Quota individuel épuisé")
                continue

            try:
                response = self._do_call(key["value"], prompt, system, **kwargs)
                key["calls"] += 1
                logger.info(f"Gemini call OK — {key['id']} ({key['calls']}/{self.DAILY_QUOTA})")
                self._save_usage_to_firebase()
                return response

            except Exception as e:
                err_str = str(e).lower()
                if "quota" in err_str or "429" in err_str:
                    key["active"] = False
                    self._switch_key(f"Quota épuisé (429)")
                else:
                    self._switch_key(f"Erreur API: {str(e)[:50]}")

        self._alert("🔴 Les deux clés Gemini sont KO — mode template statique activé")
        raise AllKeysExhaustedError("Les deux clés KO")

    def _do_call(self, api_key: str, prompt: str, system: str = "", **kwargs) -> str:
        """Appel réel à l'API Gemini."""
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        generation_config = genai.types.GenerationConfig(
            temperature=kwargs.get("temperature", 0.1),
            max_output_tokens=kwargs.get("max_tokens", 8192),
        )

        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
            system_instruction=system if system else None
        )

        full_prompt = prompt
        response = model.generate_content(full_prompt)
        return response.text

    def _switch_key(self, reason: str):
        previous = self.keys[self.current]["id"]
        self.current = (self.current + 1) % len(self.keys)
        next_key = self.keys[self.current]["id"]
        logger.warning(f"KEY_ROTATION: {previous} → {next_key} ({reason})")
        self._alert(
            f"🔄 Rotation clé Gemini\n"
            f"Clé précédente : {previous} \\({reason}\\)\n"
            f"Clé active : {next_key}"
        )

    def _auto_reset_if_new_day(self):
        """Reset automatique si on est un nouveau jour."""
        today = date.today().isoformat()
        if today != self._last_reset_date:
            self.reset_daily()
            self._last_reset_date = today

    def reset_daily(self):
        """Reset quotidien des compteurs."""
        for key in self.keys:
            key["calls"] = 0
            key["active"] = True
        logger.info("QUOTA_RESET: Les deux clés Gemini réinitialisées")

    def get_status(self) -> dict:
        """Retourne le statut actuel du quota pour Firebase/Telegram."""
        return {
            "date": date.today().isoformat(),
            "key1": {
                "calls_used": self.keys[0]["calls"],
                "calls_budget": self.DAILY_QUOTA,
                "active": self.keys[0]["active"]
            },
            "key2": {
                "calls_used": self.keys[1]["calls"],
                "calls_budget": self.DAILY_QUOTA,
                "active": self.keys[1]["active"]
            },
            "total_calls_used": sum(k["calls"] for k in self.keys),
            "total_budget": self.DAILY_QUOTA * 2,
            "active_key": self.keys[self.current]["id"]
        }

    def _save_usage_to_firebase(self):
        """Sauvegarde le statut quota dans Firebase."""
        try:
            from infrastructure.firebase_manager import firebase_manager
            firebase_manager.save_quota_status(self.get_status())
        except Exception as e:
            logger.debug(f"Firebase quota save skipped: {e}")


# Instance globale
quota_manager = GeminiKeyRotator()
