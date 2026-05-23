"""
HYPERION V9 — Alert Sender (Agent I - Alerting)
Envoie les alertes immédiates sans passer par le bot principal.
"""
import os
import requests
from utils.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class AlertSender:
    """Envoi d'alertes Telegram immédiates — sans retry long."""

    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def send_alert(self, message: str) -> bool:
        if not self.token or not self.chat_id:
            logger.warning(f"[ALERT] Token/ChatID manquant: {message[:80]}")
            return False

        # Tentative MarkdownV2
        for parse_mode in ["MarkdownV2", None]:
            try:
                data = {
                    "chat_id"   : self.chat_id,
                    "text"      : message[:4096],
                    "parse_mode": parse_mode
                }
                # Retirer parse_mode si None
                if parse_mode is None:
                    data.pop("parse_mode")
                    data["text"] = self._strip_md(message[:4096])

                resp = requests.post(
                    TELEGRAM_API.format(token=self.token),
                    json=data, timeout=10
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    return True
            except Exception as e:
                logger.debug(f"[ALERT] Send error: {e}")
                continue

        logger.error(f"[ALERT] Échec envoi: {message[:80]}")
        return False

    def _strip_md(self, text: str) -> str:
        import re
        text = re.sub(r"\\([_*\[\]()~`>#+=|{}.!-])", r"\1", text)
        return re.sub(r"[*_`]", "", text)


alert_sender = AlertSender()
