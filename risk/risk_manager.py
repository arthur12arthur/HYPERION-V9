"""
HYPERION V9 — Risk Manager
Consolide HADES + EV/Kelly en un RiskAssessment final.
Point d'entrée unique pour toute la logique risque.
"""
from typing import List, Dict, Optional, Tuple
from domain.schemas import (
    Course, Runner, TopPrediction,
    HadesReport, HadesNiveau,
    EVKellyResult, BettingRecommendation,
    RiskAssessment, RiskLevel
)
from risk.f1_hades    import hades_engine
from risk.f2_ev_kelly import ev_kelly_calc
from utils.logger     import get_logger
from utils.config     import config

logger = get_logger(__name__)


class RiskManager:
    """
    Agent F — Orchestre l'analyse de risque complète.
    Coordonne HADES (F1) et EV/Kelly (F2).
    Produit le RiskAssessment final.
    """

    def analyze(
        self,
        course: Course,
        top_prediction: TopPrediction,
        cotes_initiales: Optional[Dict[int, float]] = None,
        external_buzz: Optional[Dict[int, int]] = None
    ) -> Tuple[HadesReport, List[EVKellyResult], List[BettingRecommendation], RiskAssessment]:
        """
        Analyse complète du risque pour une course.

        Returns:
            (hades_report, ev_results, recommendations, risk_assessment)
        """
        runners   = course.partants
        course_id = course.course_id

        # ── F1 : HADES ────────────────────────────────────────────
        hades_report = hades_engine.analyze_course(
            course_id       = course_id,
            top_prediction  = top_prediction,
            runners         = runners,
            cotes_initiales = cotes_initiales,
            external_buzz   = external_buzz
        )

        # ── F2 : EV/Kelly ─────────────────────────────────────────
        cotes = {r.numero: r.cote_officielle for r in runners}
        ev_results = ev_kelly_calc.compute_all(top_prediction, cotes)

        # HADES bloque les mises en production si RED
        # En mode test → jamais bloqué (observation seule)
        hades_blocked = (
            hades_report.niveau_global == HadesNiveau.RED
            and not config.hades_mode_test
        )

        recommendations = ev_kelly_calc.build_recommendations(
            ev_results, course_id, hades_blocked
        )

        # ── RiskAssessment consolidé ───────────────────────────────
        risk_assessment = self._build_risk_assessment(
            course_id, hades_report, ev_results, hades_blocked
        )

        logger.info(
            f"[RISK] {course_id}: HADES={hades_report.niveau_global.value} | "
            f"value_bets={len([r for r in ev_results if r.is_value_bet])} | "
            f"bloqué={hades_blocked}"
        )

        return hades_report, ev_results, recommendations, risk_assessment

    def _build_risk_assessment(
        self,
        course_id: str,
        hades: HadesReport,
        ev_results: List[EVKellyResult],
        hades_blocked: bool
    ) -> RiskAssessment:
        """Construit le RiskAssessment final consolidé."""

        alertes       = []
        recommandations = []

        # Alertes HADES
        for alert in hades.signaux_detail:
            alertes.append(
                f"#{alert.cheval_numero} {alert.cheval_nom or ''}: "
                f"{', '.join(alert.signaux)}"
            )

        # Niveau global
        if hades_blocked:
            niveau_global = "BLOQUÉ"
            recommandations.append("⛔ Aucune mise conseillée — anomalie marché détectée")
        elif hades.niveau_global == HadesNiveau.YELLOW:
            niveau_global = "VIGILANCE"
            recommandations.append("⚠️ Réduire les mises de 50% sur les chevaux suspects")
        else:
            niveau_global = "ACCEPTABLE"

        # Recommandations EV
        value_bets = [r for r in ev_results if r.is_value_bet]
        if value_bets and not hades_blocked:
            top_vb = value_bets[0]
            recommandations.append(
                f"Value bet principal : #{top_vb.cheval_numero} "
                f"(EV=+{top_vb.ev*100:.1f}%)"
            )
        elif not value_bets:
            recommandations.append("Aucun value bet détecté sur cette course")

        # Mise totale max
        mise_totale_max = sum(
            r.mise_recommandee for r in ev_results
            if r.is_value_bet and not hades_blocked
        )

        return RiskAssessment(
            course_id       = course_id,
            niveau_global   = niveau_global,
            nb_alertes      = hades.nb_signaux,
            mise_totale_max = mise_totale_max,
            hades_blocked   = hades_blocked,
            alertes         = alertes,
            recommandations = recommandations
        )


# Instance globale
risk_manager = RiskManager()
