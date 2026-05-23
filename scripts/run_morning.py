"""
HYPERION V9 — Point d'entrée pipeline matin (09h00)
Appelé par GitHub Actions : morning_pipeline.yml
"""
import os
import sys

# Ajouter le répertoire racine au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger
from utils.helpers import today_str

logger = get_logger("run_morning")


def main():
    logger.info(f"=== HYPERION V9 — Pipeline Matin {today_str()} ===")

    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    try:
        from orchestration.orchestrator import orchestrator
        success = orchestrator.run_morning(chat_id=chat_id)

        if success:
            logger.info("=== Pipeline matin terminé avec succès ===")
            sys.exit(0)
        else:
            logger.warning("=== Pipeline matin terminé avec erreurs partielles ===")
            sys.exit(1)

    except Exception as e:
        logger.error(f"=== ERREUR FATALE pipeline matin: {e} ===")
        # Tenter d'envoyer une alerte d'urgence
        try:
            from monitoring.alert_sender import alert_sender
            alert_sender.send_alert(
                f"HYPERION ERREUR FATALE MATIN\n{str(e)[:200]}"
            )
        except Exception:
            pass
        sys.exit(2)


if __name__ == "__main__":
    main()
