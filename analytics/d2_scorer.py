"""
HYPERION V9 — D2 Scorer
Scoring multicritères déterministe — 5 critères pondérés.
Zéro aléatoire, zéro Gemini. Python pur.
"""
import math
from typing import List, Dict, Tuple
from domain.schemas import Runner, ScoredRunner
from utils.logger import get_logger
from utils.config import config

logger = get_logger(__name__)

POIDS_REF   = 58.0   # kg de référence pour le handicap
FORME_DEPTH = 8      # nb de courses de forme analysées
FRESHNESS_OPTIMAL_MIN = 14  # jours de repos optimal minimum
FRESHNESS_OPTIMAL_MAX = 28  # jours de repos optimal maximum


class D2Scorer:
    """
    Étape D2 : applique les 5 critères de scoring à chaque Runner.
    Chaque critère produit un score entre 0.0 et 10.0.
    Le score global est la moyenne pondérée.
    """

    def __init__(self):
        w = config.scoring_weights
        self.w_historique = w.get("historique", 0.35)
        self.w_forme      = w.get("forme",      0.25)
        self.w_terrain    = w.get("terrain",    0.20)
        self.w_handicap   = w.get("handicap",   0.10)
        self.w_fraicheur  = w.get("fraicheur",  0.10)

    def score_all(
        self,
        runners: List[Runner],
        course_distance: int = None,
        course_type: str = None
    ) -> List[ScoredRunner]:
        """
        Score tous les partants d'une course.
        Retourne une liste de ScoredRunner triée par score_global décroissant.
        """
        scored = []
        for runner in runners:
            sr = self._score_runner(runner, runners, course_distance, course_type)
            scored.append(sr)

        # Trier par score global décroissant
        scored.sort(key=lambda r: r.score_global, reverse=True)

        # Attribuer les rangs théoriques
        for rank, sr in enumerate(scored, 1):
            sr = sr.copy(update={"rang_theorique": rank})
            scored[rank - 1] = sr

        logger.info(
            f"[D2] Scoring terminé: {len(scored)} partants | "
            f"#1={scored[0].nom} ({scored[0].score_global:.2f})"
        )
        return scored

    def _score_runner(
        self,
        runner: Runner,
        all_runners: List[Runner],
        course_distance: int = None,
        course_type: str = None
    ) -> ScoredRunner:
        """Calcule les 5 critères pour un Runner."""

        s_hist    = self._score_historique(runner)
        s_forme   = self._score_forme(runner)
        s_terrain = self._score_terrain(runner, course_distance, course_type)
        s_handicap= self._score_handicap(runner)
        s_fraich  = self._score_fraicheur(runner)

        score_global = (
            s_hist     * self.w_historique +
            s_forme    * self.w_forme      +
            s_terrain  * self.w_terrain    +
            s_handicap * self.w_handicap   +
            s_fraich   * self.w_fraicheur
        )

        return ScoredRunner(
            **runner.dict(),
            score_historique = round(s_hist, 3),
            score_forme      = round(s_forme, 3),
            score_terrain    = round(s_terrain, 3),
            score_handicap   = round(s_handicap, 3),
            score_fraicheur  = round(s_fraich, 3),
            score_global     = round(score_global, 4),
        )

    # ──────────────────────────────────────────────────────────────
    # CRITÈRE 1 — HISTORIQUE (poids 0.35)
    # Performance générale sur la carrière récente
    # ──────────────────────────────────────────────────────────────
    def _score_historique(self, runner: Runner) -> float:
        """
        Mesure la performance globale sur les dernières courses.
        Score = moyenne pondérée des positions (course récente = poids fort).
        Gains totaux comme signal secondaire.
        """
        forme = runner.forme_parsed

        if not forme:
            # Pas de forme → score neutre légèrement sous la moyenne
            return 4.5

        # Ne garder que les N dernières courses
        recent = forme[-FORME_DEPTH:]
        n = len(recent)

        if n == 0:
            return 4.5

        # Poids décroissants du plus récent au plus ancien
        weights = [n - i for i in range(n)]  # [n, n-1, ..., 1]
        total_weight = sum(weights)

        # Convertir position en score (1er = 10, 2e = 8, 3e = 6, ...)
        position_scores = []
        for pos in recent:
            if pos == 0:
                score = 2.0    # Disqualifié / non classé
            elif pos == 1:
                score = 10.0
            elif pos == 2:
                score = 8.0
            elif pos == 3:
                score = 6.5
            elif pos == 4:
                score = 5.0
            elif pos == 5:
                score = 4.0
            else:
                score = max(1.0, 10.0 - pos * 0.8)
            position_scores.append(score)

        # Moyenne pondérée
        weighted_sum = sum(s * w for s, w in zip(position_scores, weights))
        base_score   = weighted_sum / total_weight if total_weight > 0 else 5.0

        # Bonus gains (si disponible)
        if runner.gains_totaux and runner.gains_totaux > 0:
            # Normaliser les gains (référence : 100 000 = score neutre)
            gains_bonus = min(1.0, math.log10(runner.gains_totaux + 1) / 6.0)
            base_score  = min(10.0, base_score + gains_bonus * 0.5)

        return round(base_score, 3)

    # ──────────────────────────────────────────────────────────────
    # CRITÈRE 2 — FORME RÉCENTE (poids 0.25)
    # Tendance des 5 dernières courses : progression ou déclin
    # ──────────────────────────────────────────────────────────────
    def _score_forme(self, runner: Runner) -> float:
        """
        Mesure la tendance récente (progression ou déclin).
        Une amélioration continue donne un score élevé.
        """
        forme = runner.forme_parsed

        if not forme or len(forme) < 2:
            return 5.0

        # Prendre les 5 dernières courses
        recent = forme[-5:]
        n = len(recent)

        # Calculer la pente (régression linéaire simple)
        # Les positions sont inversées : amélioration = pente négative
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n

        numerator   = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0

        # Pente négative = amélioration des positions (1er est mieux que 5ème)
        # Transformer en score 0-10
        if slope < -0.5:    # forte progression
            tendance_score = 9.0
        elif slope < 0:     # légère progression
            tendance_score = 7.0
        elif slope < 0.5:   # stable
            tendance_score = 5.5
        elif slope < 1.0:   # légère régression
            tendance_score = 3.5
        else:               # forte régression
            tendance_score = 2.0

        # Bonus : régularité (faible écart-type)
        if n >= 3:
            variance   = sum((p - y_mean) ** 2 for p in recent) / n
            std_dev    = math.sqrt(variance)
            # Faible écart-type = régularité = bonus
            regularite = max(0, 1.0 - std_dev / 3.0)
            tendance_score = min(10.0, tendance_score + regularite * 0.5)

        return round(tendance_score, 3)

    # ──────────────────────────────────────────────────────────────
    # CRITÈRE 3 — TERRAIN / DISTANCE (poids 0.20)
    # Adéquation cheval ↔ conditions du jour
    # ──────────────────────────────────────────────────────────────
    def _score_terrain(
        self,
        runner: Runner,
        course_distance: int = None,
        course_type: str = None
    ) -> float:
        """
        Évalue l'adéquation du cheval avec les conditions de la course.
        Sans données historiques détaillées → score neutre pondéré.
        """
        score = 5.0  # base neutre

        # Si pas de conditions connues → score neutre
        if not course_distance and not course_type:
            return score

        # Ajustement par type de course
        if course_type:
            type_lower = course_type.lower()
            # Les chevaux avec forme "rapide" (positions basses sur peu de distance)
            # avantagés sur plat vs attelé
            if "attel" in type_lower:
                # Attelé : favoriser les formes régulières
                if runner.forme_parsed and len(runner.forme_parsed) >= 3:
                    recent = runner.forme_parsed[-3:]
                    if max(recent) <= 4:
                        score += 1.5
            elif "plat" in type_lower or "haie" in type_lower:
                # Plat/haies : favoriser les formes récentes bonnes
                if runner.forme_parsed and runner.forme_parsed[-1] <= 3:
                    score += 1.0

        # Ajustement par distance
        if course_distance:
            # Poids : plus le cheval est léger, plus il est avantagé sur longues distances
            if course_distance >= 2400 and runner.poids < POIDS_REF:
                score += 0.5
            elif course_distance <= 1400 and runner.poids <= POIDS_REF - 2:
                score += 0.8

        return round(min(10.0, max(0.0, score)), 3)

    # ──────────────────────────────────────────────────────────────
    # CRITÈRE 4 — HANDICAP POIDS (poids 0.10)
    # Avantage ou désavantage du poids imposé
    # ──────────────────────────────────────────────────────────────
    def _score_handicap(self, runner: Runner) -> float:
        """
        Mesure l'écart par rapport au poids de référence.
        Poids léger = avantage → score plus élevé.
        """
        ecart = runner.poids - POIDS_REF

        # Chaque kg en moins = avantage
        if ecart <= -4:
            return 9.5
        elif ecart <= -2:
            return 8.0
        elif ecart <= 0:
            return 6.5
        elif ecart <= 2:
            return 5.0
        elif ecart <= 4:
            return 3.5
        else:
            return 2.0

    # ──────────────────────────────────────────────────────────────
    # CRITÈRE 5 — FRAÎCHEUR (poids 0.10)
    # Repos depuis la dernière course
    # ──────────────────────────────────────────────────────────────
    def _score_fraicheur(self, runner: Runner) -> float:
        """
        Évalue le repos du cheval.
        Optimal : 14-28 jours. Trop court ou trop long = désavantage.
        """
        if not runner.date_dernier_depart:
            # Pas de date connue → score neutre
            return 5.5

        try:
            from datetime import date
            last_date = date.fromisoformat(runner.date_dernier_depart)
            today     = date.today()
            jours     = (today - last_date).days

            if jours < 7:
                return 3.0   # trop frais, peut manquer de condition
            elif 7 <= jours < FRESHNESS_OPTIMAL_MIN:
                return 5.5   # légèrement sous-optimal
            elif FRESHNESS_OPTIMAL_MIN <= jours <= FRESHNESS_OPTIMAL_MAX:
                return 9.0   # optimal
            elif jours <= 45:
                return 7.0   # un peu long mais acceptable
            elif jours <= 90:
                return 5.0   # assez long
            else:
                return 3.0   # trop long — rouillé

        except (ValueError, TypeError):
            return 5.5


# Instance globale
d2_scorer = D2Scorer()
