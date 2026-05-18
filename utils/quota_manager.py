import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class QuotaExceededError(Exception):
    pass

class APIError(Exception):
    pass

class AllKeysExhaustedError(Exception):
    pass

class GeminiKeyRotator:
    """
    Gestionnaire de rotation automatique des clés Gemini.
    """

    def __init__(self):
        self.keys = [
            {"id": "KEY1", "value": os.getenv("GEMINI_API_KEY_1"), "calls": 0, "active": True},
            {"id": "KEY2", "value": os.getenv("GEMINI_API_KEY_2"), "calls": 0, "active": True},
        ]
        self.current = 0

    def call_gemini(self, prompt: str, **kwargs) -> str:
        """
        Appel Gemini avec rotation automatique.
        """
        for attempt in range(len(self.keys)):
            key = self.keys[self.current]

            if not key["active"]:
                self._switch_key("Clé désactivée")
                continue

            try:
                # Simulation de l'appel API - À remplacer par l'appel réel google-generativeai
                response = self._do_call(key["value"], prompt, **kwargs)
                key["calls"] += 1
                self._save_usage_to_firebase()
                return response

            except Exception as e:
                # Logique simplifiée pour l'exemple
                if "quota" in str(e).lower():
                    logger.warning(f"⚠️ {key['id']} quota épuisé → bascule")
                    key["active"] = False
                    self._switch_key("Quota épuisé")
                else:
                    logger.error(f"⚠️ {key['id']} erreur API: {e} → bascule")
                    self._switch_key("Erreur API")

        raise AllKeysExhaustedError("Les deux clés Gemini sont KO")

    def _do_call(self, api_key: str, prompt: str, **kwargs) -> str:
        # Implémentation réelle avec google.generativeai
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text

    def _switch_key(self, reason: str):
        previous = self.keys[self.current]["id"]
        self.current = (self.current + 1) % len(self.keys)
        next_key = self.keys[self.current]["id"]
        logger.info(f"KEY_ROTATION: {previous} → {next_key} ({reason})")

    def _save_usage_to_firebase(self):
        # Sera implémenté avec FirebaseManager
        pass

    def reset_daily(self):
        for key in self.keys:
            key["calls"] = 0
            key["active"] = True
        logger.info("QUOTA_RESET: Les deux clés réinitialisées")
