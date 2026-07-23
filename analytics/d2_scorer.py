import logging
from typing import List
from domain.schemas import Course, ScoredRunner

logger = logging.getLogger(__name__)

class Scorer:
    @staticmethod
    def process(course: Course, weights: dict) -> List[ScoredRunner]:
        """
        D2 - Scoring Multicritères
        """
        scored_runners = []
        for r in course.partants:
            # Calculs simplifiés pour l'exemple (à enrichir avec la logique réelle)
            score_hist = Scorer._calc_historique(r)
            score_forme = Scorer._calc_forme(r)
            score_terrain = 0.5 # Valeur par défaut
            score_handicap = Scorer._calc_handicap(r)
            score_fraicheur = 0.5 # Valeur par défaut
            
            global_score = (
                score_hist * weights.get('score_historique', 0.35) +
                score_forme * weights.get('score_forme', 0.25) +
                score_terrain * weights.get('score_terrain', 0.20) +
                score_handicap * weights.get('score_handicap', 0.10) +
                score_fraicheur * weights.get('score_fraicheur', 0.10)
            )
            
            scored_runners.append(ScoredRunner(
                **r.dict(),
                score_historique=score_hist,
                score_forme=score_forme,
                score_terrain=score_terrain,
                score_handicap=score_handicap,
                score_fraicheur=score_fraicheur,
                score_global=global_score
            ))
            
        return sorted(scored_runners, key=lambda x: x.score_global, reverse=True)

    @staticmethod
    def _calc_historique(runner) -> float:
        if not runner.forme_parsed: return 0.5
        # Plus le chiffre est petit (1er, 2ème), plus le score est haut
        avg = sum(runner.forme_parsed) / len(runner.forme_parsed)
        return max(0, 1 - (avg / 10))

    @staticmethod
    def _calc_forme(runner) -> float:
        if not runner.forme_parsed: return 0.5
        # On regarde la dernière course
        last = runner.forme_parsed[0]
        return 1.0 if last == 1 else (0.8 if last == 2 else 0.5)

    @staticmethod
    def _calc_handicap(runner) -> float:
        # Référence 58kg
        return 1.0 if runner.poids <= 58 else 0.7
