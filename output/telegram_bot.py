"""
HYPERION V9 — Telegram Bot
Envoie les messages avec retry ×3 et fallback texte brut.
"""
import os
import re
import time
import requests
from typing import Optional, List
from domain.schemas import TelegramMessage
from utils.logger  import get_logger
from utils.helpers import truncate_message

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
RETRY_DELAYS = [30, 60, 90]   # secondes entre tentatives


class TelegramBot:
    """
    Envoie des messages Telegram avec robustesse maximale.
    Retry ×3 → fallback texte brut → log local si tout échoue.
    """

    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def send(self, message: TelegramMessage) -> bool:
        """
        Envoie un TelegramMessage avec retry automatique.
        Retourne True si succès, False sinon.
        """
        if not self.token:
            logger.error("[TELEGRAM] BOT_TOKEN non configuré")
            return False

        chat_id = message.chat_id or self.chat_id
        if not chat_id:
            logger.error("[TELEGRAM] CHAT_ID non configuré")
            return False

        # Tentatives MarkdownV2
        for i, delay in enumerate(RETRY_DELAYS):
            success = self._do_send(
                chat_id    = chat_id,
                text       = message.text,
                parse_mode = message.parse_mode,
                disable_notification = message.disable_notification
            )
            if success:
                logger.info(f"[TELEGRAM] Message envoyé (tentative {i+1})")
                return True

            if i < len(RETRY_DELAYS) - 1:
                logger.warning(f"[TELEGRAM] Échec tentative {i+1} — retry dans {delay}s")
                time.sleep(delay)

        # Fallback : envoyer en texte brut sans MarkdownV2
        logger.warning("[TELEGRAM] Fallback texte brut activé")
        plain_text = self._strip_markdown(message.text)
        success = self._do_send(
            chat_id    = chat_id,
            text       = plain_text,
            parse_mode = None
        )
        if success:
            logger.info("[TELEGRAM] Message envoyé en texte brut")
            return True

        # Échec total — log local
        logger.error("[TELEGRAM] ÉCHEC TOTAL — message logué localement")
        self._log_locally(message.text, chat_id)
        return False

    def send_text(self, text: str, chat_id: str = None) -> bool:
        """Raccourci pour envoyer du texte simple."""
        msg = TelegramMessage(
            chat_id    = chat_id or self.chat_id,
            parse_mode = "MarkdownV2",
            text       = truncate_message(text, 4096)
        )
        return self.send(msg)

    def send_alert(self, text: str) -> bool:
        """Envoie une alerte immédiate (pas de retry long)."""
        if not self.token or not self.chat_id:
            logger.warning(f"[TELEGRAM] Alert non envoyée: {text[:100]}")
            return False

        plain = self._strip_markdown(text)
        return self._do_send(
            chat_id    = self.chat_id,
            text       = f"⚡ HYPERION ALERT\n\n{plain}",
            parse_mode = None
        )

    def send_multiple(self, messages: List[TelegramMessage]) -> int:
        """
        Envoie plusieurs messages.
        Retourne le nombre de messages envoyés avec succès.
        """
        success_count = 0
        for msg in messages:
            if self.send(msg):
                success_count += 1
            time.sleep(1)  # pause entre messages (rate limit Telegram)
        return success_count

    def _do_send(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = "MarkdownV2",
        disable_notification: bool = False
    ) -> bool:
        """Effectue l'appel API Telegram."""
        if not text or not text.strip():
            return False

        url  = TELEGRAM_API.format(token=self.token, method="sendMessage")
        data = {
            "chat_id"              : chat_id,
            "text"                 : truncate_message(text, 4096),
            "disable_notification" : disable_notification,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode

        try:
            resp = requests.post(url, json=data, timeout=15)
            if resp.status_code == 200 and resp.json().get("ok"):
                return True

            error = resp.json().get("description", "Unknown error")
            logger.warning(f"[TELEGRAM] API error {resp.status_code}: {error}")

            # Erreur MarkdownV2 → suggérer fallback
            if "can't parse" in error.lower() or "parse_mode" in error.lower():
                logger.warning("[TELEGRAM] Erreur MarkdownV2 — fallback texte brut")
                return False

        except requests.RequestException as e:
            logger.warning(f"[TELEGRAM] Request failed: {e}")

        return False

    def _strip_markdown(self, text: str) -> str:
        """Supprime tous les marqueurs MarkdownV2 pour un texte brut lisible."""
        # Supprimer les backslashes d'échappement
        text = re.sub(r"\\([_*\[\]()~`>#+=|{}.!-])", r"\1", text)
        # Supprimer les marqueurs de formatage
        text = re.sub(r"[*_`]", "", text)
        # Supprimer les titres inline
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        return text.strip()

    def _log_locally(self, text: str, chat_id: str):
        """Sauvegarde le message localement si Telegram est inaccessible."""
        import os
        from datetime import datetime
        log_dir  = "./backup/logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(
            log_dir,
            f"telegram_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"chat_id: {chat_id}\n\n{text}")
            logger.info(f"[TELEGRAM] Message sauvegardé: {log_file}")
        except Exception as e:
            logger.error(f"[TELEGRAM] Impossible de sauvegarder: {e}")


# Instance globale
telegram_bot = TelegramBot()
