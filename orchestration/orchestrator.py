"""
HYPERION V9 — Orchestrateur Principal (Agent A)
Coordonne les 9 agents de bout en bout.
"""
import os
from typing import List, Optional
from domain.schemas import (
    Course, CourseReport, PipelineRun,
    PipelineState, TopPrediction
)
from utils.logger  import get_logger
from utils.helpers import today_str, now_iso
from utils.config  import config

logger = get_logger(__name__)


class HyperionOrchestrator:
    """
    Agent A — Orchestre le pipeline complet matin.
    Coordonne : B (LONAB) → C (Enrichissement) → D (Scoring)
              → E (Fusion) → F (Risque) → G (Reporting) → I (Monitoring)
    """

    def __init__(self):
        # Imports tardifs pour éviter les cycles
        from monitoring.pipeline_monitor  import pipeline_monitor
        from monitoring.alert_sender      import alert_sender
        from orchestration.run_manager    import run_manager
        from orchestration.state_machine  import StateMachine
        from infrastructure.firebase_manager import firebase_manager

        self.monitor   = pipeline_monitor
        self.alerter   = alert_sender
        self.run_mgr   = run_manager
        self.firebase  = firebase_manager

        # Injecter l'alerter dans le monitor
        self.monitor.set_alerter(self.alerter)

        # Injecter le monitor dans les adapters
        from data.lonab_adapter import lonab_adapter
        from data.pmu_adapter   import pmu_adapter
        from data.web_scraper   import web_scraper
        lonab_adapter.set_monitor(self.monitor)
        pmu_adapter.set_monitor(self.monitor)
        web_scraper.set_monitor(self.monitor)

    def run_morning(self, date_str: str = None, chat_id: str = None) -> bool:
        """
        Pipeline complet du matin.
        Retourne True si succès, False si échec partiel ou total.
        """
        if date_str is None:
            date_str = today_str()

        self.monitor.reset()
        run = self.run_mgr.create_run("morning_analysis")

        logger.info(f"[ORCHESTRATOR] Démarrage pipeline matin {date_str} | run={run.run_id}")

        try:
            # ── AGENT B : Identification LONAB ────────────────────
            lonab_course = self._step_identify_lonab(date_str)

            # ── Sélection 10 courses ──────────────────────────────
            courses = self._step_select_courses(lonab_course, date_str)
            if not courses:
                self.monitor.log("COURSES_SELECTED", "FAIL", "Aucune course sélectionnée")
                return self._finalize(run, success=False)

            # ── AGENT C + D + E + F pour chaque course ────────────
            course_reports = self._step_analyze_all(courses, date_str)

            if not course_reports:
                self.monitor.log("ANALYSIS", "FAIL", "Aucun rapport généré")
                return self._finalize(run, success=False)

            # ── Sauvegarder prédictions Firebase ─────────────────
            self._step_save_predictions(course_reports, date_str)

            # ── AGENT G : Reporting & Delivery ───────────────────
            self._step_deliver_reports(course_reports, chat_id)

            # ── Rapport santé Agent I ─────────────────────────────
            self._send_health_report(mode="morning")

            run.courses_traitees = len(course_reports)
            return self._finalize(run, success=True)

        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Erreur fatale: {e}")
            self.monitor.log("ORCHESTRATOR", "FAIL", str(e)[:100])
            self._send_health_report(mode="morning")
            return self._finalize(run, success=False)

    # ──────────────────────────────────────────────────────────────
    # ÉTAPES INTERNES
    # ──────────────────────────────────────────────────────────────
    def _step_identify_lonab(self, date_str: str) -> Optional[Course]:
        from data.lonab_adapter import lonab_adapter
        course, method = lonab_adapter.get_lonab_course(date_str)
        if course:
            self.monitor.log("LONAB_IDENTIFICATION", "OK", f"via {method}")
        else:
            self.monitor.log("LONAB_IDENTIFICATION", "WARNING",
                           "Inaccessible — course PMU de remplacement")
        return course

    def _step_select_courses(
        self, lonab_course: Optional[Course], date_str: str
    ) -> List[Course]:
        from data.pmu_adapter import pmu_adapter
        pmu_adapter.set_monitor(self.monitor)
        courses = pmu_adapter.select_daily_courses(
            lonab_course,
            max_courses=config.max_courses
        )
        self.monitor.log("COURSES_SELECTED", "OK", f"{len(courses)} courses")
        return courses

    def _step_analyze_all(
        self, courses: List[Course], date_str: str
    ) -> List[CourseReport]:
        from analytics             import run_full_analytics
        from data.fusion_engine    import fusion_engine
        from risk.risk_manager     import risk_manager

        fusion_engine.set_monitor(self.monitor)

        enriched    = fusion_engine.enrich_all_courses(courses)
        reports     = []

        for course, ext_data, ext_consensus in enriched:
            try:
                # D1 → E3
                top_pred, internal = run_full_analytics(
                    course, ext_data, ext_consensus
                )
                self.monitor.log(f"ANALYSIS_{course.course_id}", "OK")

                # F : Risque & Finance
                hades, ev_results, recommendations, risk = risk_manager.analyze(
                    course, top_pred
                )

                # Construire le rapport
                report = CourseReport(
                    course_id  = course.course_id,
                    date       = date_str,
                    hippodrome = course.hippodrome,
                    distance   = course.distance,
                    is_lonab   = course.is_lonab,
                    top5       = top_pred,
                    hades      = hades,
                    ev_kelly   = ev_results,
                    risk       = risk,
                    confiance  = top_pred.confidence_global
                )
                reports.append(report)

            except Exception as e:
                logger.error(f"[ORCHESTRATOR] Analyse {course.course_id}: {e}")
                self.monitor.log(f"ANALYSIS_{course.course_id}", "FAIL", str(e)[:60])
                continue

        self.monitor.log("ANALYSIS_ALL", "OK", f"{len(reports)}/{len(courses)} rapports")
        return reports

    def _step_save_predictions(
        self, reports: List[CourseReport], date_str: str
    ):
        for report in reports:
            try:
                pred_data = {
                    "date"          : date_str,
                    "course_id"     : report.course_id,
                    "hippodrome"    : report.hippodrome,
                    "is_lonab"      : report.is_lonab,
                    "predicted_top5": report.top5.classement_final if report.top5 else [],
                    "predicted_winner": report.top5.classement_final[0]
                                        if report.top5 and report.top5.classement_final else None,
                    "confidence"    : report.confiance,
                    "hades_niveau"  : report.hades.niveau_global.value if report.hades else "GREEN"
                }
                self.firebase.save_prediction(date_str, report.course_id, pred_data)
            except Exception as e:
                logger.error(f"[ORCHESTRATOR] Save prediction {report.course_id}: {e}")

        self.monitor.log("FIREBASE_SAVE", "OK", f"{len(reports)} prédictions")

    def _step_deliver_reports(
        self, reports: List[CourseReport], chat_id: str = None
    ):
        from output.report_generator import report_generator
        from output.telegram_bot     import telegram_bot

        messages = report_generator.generate_all(reports, chat_id)
        sent     = telegram_bot.send_multiple(messages)

        self.monitor.log(
            "TELEGRAM_SEND", "OK" if sent > 0 else "FAIL",
            f"{sent}/{len(messages)} messages envoyés"
        )

    def _send_health_report(self, mode: str):
        from monitoring.health_reporter import health_reporter
        from output.telegram_bot        import telegram_bot

        summary = self.monitor.get_summary()
        text    = health_reporter.build_message(summary, mode)
        telegram_bot.send_text(text)

    def _finalize(self, run: PipelineRun, success: bool) -> bool:
        self.run_mgr.finalize_run(run, success)
        status = "SUCCESS" if success else "PARTIAL_FAIL"
        logger.info(f"[ORCHESTRATOR] Run terminé: {status} | {run.run_id}")
        return success


# Instance globale
orchestrator = HyperionOrchestrator()
