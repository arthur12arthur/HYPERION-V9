"""
HYPERION V9 — HADES (Hazard & Anomaly Detection Engine for Stakes) — F1
Détecte les anomalies de marché avant de conseiller une mise.
MODE TEST (30 jours) : observation seule, aucun blocage.
"""
from typing import List, Dict, Optional
from domain.schemas import (
    Runner, TopPrediction, MetaPrediction,
    HadesAlert, HadesReport, HadesNiveau
)
from utils.logger import get_logger
from utils.config import config
from utils.helpers import now_iso

logger = get_logger(__name__)


class HadesEngine:
    """
    Agent F1 — Détection d'anomalies sur les marchés hippiques.

    Signaux surveillés :
    - VARIATION_COTE    : cote a bougé de > 20% depuis publication LONAB
    - FAVORI_ARTIFICIEL : win_prob < 10% mais cheval est favori du marché
    - BUZZ_ARTIFICIEL   : mentions externes 3× supérieures à la normale
    """

    def __init__(self):
        cfg = config.hades
        self.enabled             = cfg.get("enabled", True)
        self.mode_test           = cfg.get("mode_test", True)
        self.cote_deviation_thr  = cfg.get("cote_deviation_threshold", 0.20)
        self.fav_prob_max        = cfg.get("artificial_favorite_prob_max", 0.10)
        self.buzz_multiplier     = cfg.get("buzz_multiplier", 3.0)
        self.alerte_threshold    = cfg.get("score_alerte_threshold", 0.70)
        self.niveau_yellow_max   = cfg.get("niveau_yellow_max", 0.70)
        self.niveau_green_max    = cfg.get("niveau_green_max", 0.40)

    def analyze_course(
        self,
        course_id: str,
        top_prediction: TopPrediction,
        runners: List[Runner],
        cotes_initiales: Optional[Dict[int, float]] = None,
        external_buzz: Optional[Dict[int, int]] = None
    ) -> HadesReport:
        """
        Analyse complète d'une course.

        Args:
            course_id       : identifiant de la course
            top_prediction  : prédictions MetaPrediction (win_prob depuis MC)
            runners         : liste des partants avec cotes actuelles
            cotes_initiales : cotes publiées initialement (pour détecter variation)
            external_buzz   : nb mentions externes par numéro de cheval

        Returns:
            HadesReport avec niveau global et alertes détaillées
        """
        if not self.enabled:
            return self._empty_report(course_id)

        alerts: List[HadesAlert] = []

        # Préparer les win_prob depuis les prédictions MC
        win_probs: Dict[int, float] = {}
        for pred in top_prediction.predictions:
            win_probs[pred.numero] = pred.score_mc

        for runner in runners:
            runner_alerts = self._analyze_runner(
                runner, win_probs, cotes_initiales, external_buzz
            )
            alerts.extend(runner_alerts)

        # Niveau global = max des niveaux individuels
        niveau_global = HadesNiveau.GREEN
        if any(a.niveau == HadesNiveau.RED for a in alerts):
            niveau_global = HadesNiveau.RED
        elif any(a.niveau == HadesNiveau.YELLOW for a in alerts):
            niveau_global = HadesNiveau.YELLOW

        chevaux_suspects = list({a.cheval_numero for a in alerts})
        recommendations = self._build_recommendations(niveau_global, alerts)

        report = HadesReport(
            course_id        = course_id,
            niveau_global    = niveau_global,
            nb_signaux       = len(alerts),
            chevaux_suspects = chevaux_suspects,
            signaux_detail   = alerts,
            recommendations  = recommendations,
            mode_test        = self.mode_test
        )

        self._log_report(report)
        return report

    def _analyze_runner(
        self,
        runner: Runner,
        win_probs: Dict[int, float],
        cotes_initiales: Optional[Dict[int, float]],
        external_buzz: Optional[Dict[int, int]]
    ) -> List[HadesAlert]:
        """Analyse un cheval individuel pour tous les signaux."""
        alerts = []
        signaux = []
        raisons = []
        score = 0.0

        num = runner.numero
        cote_actuelle = runner.cote_officielle
        win_prob = win_probs.get(num, 0.0)

        # ── Signal 1 : VARIATION_COTE ──────────────────────────────────
        if cotes_initiales and num in cotes_initiales:
            cote_init = cotes_initiales[num]
            if cote_init > 0:
                variation = abs(cote_actuelle - cote_init) / cote_init
                if variation >= self.cote_deviation_thr:
                    signaux.append("VARIATION_COTE")
                    direction = "baissé" if cote_actuelle < cote_init else "monté"
                    raisons.append(
                        f"Cote a {direction} de {variation*100:.0f}% "
                        f"({cote_init} → {cote_actuelle})"
                    )
                    score += 0.40

        # ── Signal 2 : FAVORI_ARTIFICIEL ───────────────────────────────
        if cote_actuelle > 0:
            prob_implicite = 1.0 / cote_actuelle
            # Favori du marché (prob implicite élevée) mais MC dit < 10%
            if prob_implicite > 0.25 and win_prob < self.fav_prob_max:
                signaux.append("FAVORI_ARTIFICIEL")
                raisons.append(
                    f"Marché implique {prob_implicite*100:.0f}% de chance "
                    f"mais Monte Carlo donne seulement {win_prob*100:.1f}%"
                )
                score += 0.50

        # ── Signal 3 : BUZZ_ARTIFICIEL ─────────────────────────────────
        if external_buzz:
            mentions = external_buzz.get(num, 0)
            avg_mentions = sum(external_buzz.values()) / max(len(external_buzz), 1)
            if avg_mentions > 0 and mentions > avg_mentions * self.buzz_multiplier:
                signaux.append("BUZZ_ARTIFICIEL")
                raisons.append(
                    f"Mentions externes {mentions/avg_mentions:.1f}× supérieures à la normale"
                )
                score += 0.35

        if not signaux:
            return []

        # Déterminer le niveau
        score = min(score, 1.0)
        if score >= self.niveau_yellow_max:
            niveau = HadesNiveau.RED
        elif score >= self.niveau_green_max:
            niveau = HadesNiveau.YELLOW
        else:
            niveau = HadesNiveau.GREEN

        # Pas d'alerte si green
        if niveau == HadesNiveau.GREEN:
            return []

        alerts.append(HadesAlert(
            cheval_numero = num,
            cheval_nom    = runner.nom,
            niveau        = niveau,
            score         = round(score, 3),
            signaux       = signaux,
            raisons       = raisons,
            date_detectee = now_iso()
        ))

        return alerts

    def _build_recommendations(self, niveau: HadesNiveau, alerts: List[HadesAlert]) -> str:
        if niveau == HadesNiveau.GREEN:
            return "Aucune anomalie détectée."
        if niveau == HadesNiveau.YELLOW:
            suspects = [str(a.cheval_numero) for a in alerts]
            if self.mode_test:
                return f"⚠️ Mode test — vigilance sur : #{', #'.join(suspects)}"
            return f"Réduire les mises de 50% sur #{', #'.join(suspects)}"
        if niveau == HadesNiveau.RED:
            suspects = [str(a.cheval_numero) for a in alerts]
            if self.mode_test:
                return f"🔴 Mode test — forte anomalie sur #{', #'.join(suspects)} (observation)"
            return f"⛔ Mises déconseillées sur #{', #'.join(suspects)}"
        return ""

    def _empty_report(self, course_id: str) -> HadesReport:
        return HadesReport(
            course_id=course_id,
            niveau_global=HadesNiveau.GREEN,
            recommendations="HADES désactivé",
            mode_test=self.mode_test
        )

    def _log_report(self, report: HadesReport):
        if report.nb_signaux == 0:
            logger.info(f"[{report.course_id}] HADES: 🟢 GREEN — aucune anomalie")
        else:
            logger.warning(
                f"[{report.course_id}] HADES: {report.niveau_global.value} — "
                f"{report.nb_signaux} signaux | suspects: {report.chevaux_suspects}"
            )


# Instance globale
hades_engine = HadesEngine()
