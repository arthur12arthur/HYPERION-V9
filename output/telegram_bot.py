import os
import requests
import logging
import time

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_message(self, text: str, retries: int = 3):
        """
        Envoie un message sur Telegram avec retry automatique.
        """
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2"
        }
        
        for attempt in range(retries):
            try:
                response = requests.post(self.base_url, json=payload)
                if response.status_code == 200:
                    logger.info("Message envoyé sur Telegram.")
                    return True
                else:
                    logger.warning(f"Echec Telegram (Tentative {attempt+1}): {response.text}")
                    # Fallback texte brut si MarkdownV2 échoue
                    payload["parse_mode"] = None
            except Exception as e:
                logger.error(f"Erreur Telegram: {e}")
            
            time.sleep(2 * (attempt + 1))
            
        return False
