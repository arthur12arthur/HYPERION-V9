"""
HYPERION V9 — F2 EV/Kelly Calculator
Calcule la valeur espérée (EV) et la mise optimale (Kelly)
pour chaque cheval du Top 5.
Zéro Gemini — formules financières pures.
"""
from typing import List, Optional
from domain.schemas import (
    TopPrediction, MetaPrediction,
    EVKellyResult, BettingRecommendation, RiskLevel
)
from utils.logger import get_logger
from utils.config import config
from utils.helpers import format_fcfa

logger = get_logger(__name__)


class EVKellyCalculator:
    """
    Étape F2 : calcule EV et Kelly pour chaque cheval prédit.

    Formules :
      prob_implicite = 1 / cote_officielle
      EV             = (prob_reelle × (cote - 1)) - (1 - prob_reelle)
      kelly_raw      = (prob_reelle × cote - 1) / (cote - 1)
      kelly_applique = kelly_raw × kelly_fraction
      kelly_cappe    = min(kelly_applique, kelly_max_pct)
      mise           = kelly_cappe × capital
    """

    def __init__(self):
        cfg = config.finance
        self.kelly_fraction  = cfg.get("kelly_fraction",  0.25)
        self.kelly_max_pct   = cfg.get("kelly_max_pct",   0.05)
        self.ev_threshold    = cfg.get("ev_threshold",    0.05)
        self.bk_margin       = cfg.get("bookmaker_margin", 0.15)
        self.capital         = cfg.get("capital_reference", 100000.0)

    def compute_all(
        self,
        top_prediction: TopPrediction,
        cotes: dict  # {numero: cote_officielle}
    ) -> List[EVKellyResult]:
        """
        Calcule EV/Kelly pour les 5 chevaux du top.

        Args:
            top_prediction : résultat de E2/E3
            cotes          : {numero: cote} depuis les données Runner

        Returns:
            Liste de EVKellyResult triée par EV décroissant
        """
        results = []

        for pred in top_prediction.predictions:
            cote = cotes.get(pred.numero, 0.0)

            if cote <= 1.0:
                # Cote invalide ou absente → pas de calcul
                logger.debug(f"[F2] #{pred.numero}: cote invalide ({cote}) — skip")
                continue

            result = self._compute_single(pred, cote)
            results.append(result)

        # Trier par EV décroissant (meilleures opportunités en premier)
        results.sort(key=lambda r: r.ev, reverse=True)

        value_bets = [r for r in results if r.is_value_bet]
        logger.info(
            f"[F2] {top_prediction.course_id}: "
            f"{len(value_bets)} value bets sur {len(results)} chevaux"
        )
        return results

    def _compute_single(
        self,
        pred: MetaPrediction,
        cote: float
    ) -> EVKellyResult:
        """Calcule EV et Kelly pour un cheval."""

        prob_reelle    = pred.meta_score  # probabilité estimée par notre modèle
        prob_implicite = 1.0 / cote       # probabilité implicite du bookmaker

        # Ajustement de la marge bookmaker
        # La cote nette effective tient compte de la marge
        cote_nette = cote * (1 - self.bk_margin)

        # Expected Value
        ev = (prob_reelle * (cote - 1)) - (1 - prob_reelle)
        ev = round(ev, 4)
        is_value_bet = ev >= self.ev_threshold

        # Kelly Criterion
        if cote > 1 and prob_reelle > 0:
            kelly_raw = (prob_reelle * cote - 1) / (cote - 1)
            kelly_raw = max(0.0, kelly_raw)  # jamais négatif
        else:
            kelly_raw = 0.0

        kelly_applique = kelly_raw * self.kelly_fraction
        kelly_cappe    = min(kelly_applique, self.kelly_max_pct)

        mise = round(kelly_cappe * self.capital, 0) if is_value_bet else 0.0

        # Niveau de risque
        niveau_risque = self._determine_risk_level(
            ev, prob_reelle, prob_implicite, cote
        )

        return EVKellyResult(
            cheval_numero  = pred.numero,
            cheval         = f"{pred.numero} - {pred.nom or '?'}",
            prob_reelle    = round(prob_reelle, 4),
            prob_implicite = round(prob_implicite, 4),
            ev             = ev,
            is_value_bet   = is_value_bet,
            kelly_raw      = round(kelly_raw, 4),
            kelly_applique = round(kelly_applique, 4),
            kelly_cappe    = round(kelly_cappe, 4),
            mise_recommandee = mise,
            niveau_risque  = niveau_risque
        )

    def _determine_risk_level(
        self,
        ev: float,
        prob_reelle: float,
        prob_implicite: float,
        cote: float
    ) -> RiskLevel:
        """Détermine le niveau de risque d'une mise."""

        # Cote très haute = risque élevé même avec EV positif
        if cote > 15:
            return RiskLevel.ELEVE

        # EV fortement négatif = ne pas jouer
        if ev < -0.10:
            return RiskLevel.BLOQUE

        # Forte sous-évaluation par le marché
        if prob_reelle > prob_implicite * 1.5 and ev > 0.10:
            return RiskLevel.FAIBLE

        # Value bet modéré
        if ev >= self.ev_threshold:
            return RiskLevel.MODERE

        return RiskLevel.ELEVE

    def build_recommendations(
        self,
        ev_results: List[EVKellyResult],
        course_id: str,
        hades_blocked: bool = False
    ) -> List[BettingRecommendation]:
        """
        Construit les recommandations de mise finales.
        Tient compte de l'état HADES.
        """
        recommendations = []

        for result in ev_results:
            if not result.is_value_bet:
                continue

            # En mode test 30 jours ou si HADES bloque → mise à 0
            mise = 0.0 if hades_blocked else result.mise_recommandee

            justification = self._build_justification(result, hades_blocked)

            recommendations.append(BettingRecommendation(
                course_id          = course_id,
                cheval             = result.cheval,
                cote               = round(1.0 / result.prob_implicite, 2),
                prob_win           = result.prob_reelle,
                mise_max_fcfa      = round(self.capital * self.kelly_max_pct, 0),
                mise_conseillee_fcfa = mise,
                ev_pct             = round(result.ev * 100, 1),
                risque             = result.niveau_risque,
                justification      = justification
            ))

        return recommendations

    def _build_justification(
        self,
        result: EVKellyResult,
        hades_blocked: bool
    ) -> str:
        edge = result.prob_reelle - result.prob_implicite

        if hades_blocked:
            return (
                f"Value bet détecté \\(EV={result.ev*100:.1f}%\\) "
                f"mais mis en observation \\(HADES\\)\\."
            )

        if edge > 0.10:
            return (
                f"Forte sous\\-évaluation par le marché \\+{edge*100:.1f}% "
                f"| EV={result.ev*100:.1f}% | Kelly={result.kelly_cappe*100:.1f}%"
            )

        return (
            f"Value bet modéré | prob réelle {result.prob_reelle*100:.1f}% "
            f"vs marché {result.prob_implicite*100:.1f}% | "
            f"EV=\\+{result.ev*100:.1f}%"
        )


# Instance globale
ev_kelly_calc = EVKellyCalculator()
