"""
HYPERION V9 — Point d'entrée pipeline soir (20h00)
Appelé par GitHub Actions : evening_evaluation.yml
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger
from utils.helpers import today_str

logger = get_logger("run_evening")


def main():
    logger.info(f"=== HYPERION V9 — Évaluation Soir {today_str()} ===")

    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    try:
        from evaluation.daily_report import daily_report_orchestrator
        daily_report_orchestrator.run(chat_id=chat_id)

        # Rapport santé soir
        from monitoring.pipeline_monitor import pipeline_monitor
        from monitoring.health_reporter  import health_reporter
        from output.telegram_bot         import telegram_bot

        summary = pipeline_monitor.get_summary()
        text    = health_reporter.build_message(summary, mode="evening")
        telegram_bot.send_text(text)

        # Reset quota pour le lendemain (si minuit passé)
        from utils.quota_manager import quota_manager
        quota_manager._auto_reset_if_new_day()

        logger.info("=== Évaluation soir terminée ===")
        sys.exit(0)

    except Exception as e:
        logger.error(f"=== ERREUR FATALE pipeline soir: {e} ===")
        try:
            from monitoring.alert_sender import alert_sender
            alert_sender.send_alert(
                f"HYPERION ERREUR FATALE SOIR\n{str(e)[:200]}"
            )
        except Exception:
            pass
        sys.exit(2)


if __name__ == "__main__":
    main()
