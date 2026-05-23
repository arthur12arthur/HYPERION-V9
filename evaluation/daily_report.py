"""
HYPERION V9 — Daily Report Builder
Orchestre l'évaluation du soir : fetch résultats, évaluer, rapport Telegram.
"""
from typing import Dict, Optional
from utils.logger import get_logger
from utils.helpers import today_str

logger = get_logger(__name__)


class DailyReportOrchestrator:
    """Orchestre tout le pipeline d'évaluation du soir."""

    def run(self, date_str: str = None, chat_id: str = None):
        """
        Pipeline complet du soir :
        1. Charger prédictions Firebase
        2. Fetch résultats officiels PMU
        3. Évaluer
        4. Mettre à jour scores cumulés
        5. Envoyer rapport Telegram
        """
        from data.results_fetcher       import results_fetcher
        from evaluation.auto_evaluator  import auto_evaluator
        from evaluation.score_tracker   import score_tracker
        from output.evaluation_report   import evaluation_report_builder
        from output.telegram_bot        import telegram_bot
        from infrastructure.firebase_manager import firebase_manager
        from monitoring.pipeline_monitor import pipeline_monitor

        if date_str is None:
            date_str = today_str()

        logger.info(f"[EVAL_PIPELINE] Démarrage évaluation {date_str}")

        # 1. Charger les prédictions du matin depuis Firebase
        try:
            predictions = firebase_manager.load_predictions(date_str)
            if not predictions:
                logger.warning("[EVAL] Aucune prédiction trouvée en Firebase")
                pipeline_monitor.log("EVAL_LOAD", "WARNING", "Aucune prédiction")
                return
            pipeline_monitor.log("EVAL_LOAD", "OK", f"{len(predictions)} prédictions")
        except Exception as e:
            pipeline_monitor.log("EVAL_LOAD", "FAIL", str(e)[:80])
            return

        # 2. Fetch résultats officiels
        course_ids = list(predictions.keys())
        results = results_fetcher.fetch_all_results(date_str, course_ids)

        if not results:
            pipeline_monitor.log("RESULTS_FETCH", "FAIL", "Résultats non disponibles")
            return
        pipeline_monitor.log("RESULTS_FETCH", "OK", f"{len(results)} résultats")

        # 3. Évaluer
        running = score_tracker.get_running_scores()
        day_num = score_tracker.get_day_number()

        eval_report = auto_evaluator.evaluate_day(
            date_str, day_num, predictions, results, running
        )
        pipeline_monitor.log("EVALUATION", "OK",
            f"Top1={eval_report.score_jour_top1:.1f}%")

        # 4. Sauvegarder dans Firebase
        try:
            firebase_manager.save_evaluation(date_str, eval_report.dict())
            firebase_manager.save_results(date_str, results)
            score_tracker.update_running_scores(
                eval_report.running_top1_all_days,
                eval_report.running_top3_all_days,
                day_num
            )
            pipeline_monitor.log("FIREBASE_EVAL", "OK")
        except Exception as e:
            pipeline_monitor.log("FIREBASE_EVAL", "WARNING", str(e)[:60])

        # 5. Rapport Telegram
        msg = evaluation_report_builder.build_and_send(
            eval_report, predictions, results, chat_id
        )
        success = telegram_bot.send(msg)
        pipeline_monitor.log(
            "TELEGRAM_EVAL", "OK" if success else "FAIL"
        )

        logger.info(f"[EVAL_PIPELINE] Terminé J{day_num}/30")


daily_report_orchestrator = DailyReportOrchestrator()
