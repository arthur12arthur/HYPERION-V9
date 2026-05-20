"""
HYPERION V9 — Consensus Borda Interne (D4)
Agrège les 5 variantes Monte Carlo en un classement robuste unique.
"""
from typing import List, Dict
from domain.schemas import MonteCarloResult, InternalConsensus
from utils.logger import get_logger
from utils.config import config

logger = get_logger(__name__)


class BordaConsensus:
    """
    Méthode de Borda appliquée aux résultats Monte Carlo.
    Points attribués : position 1 → N-1, position 2 → N-2, ...
    """

    @staticmethod
    def compute(
        variantes_results: List[List[MonteCarloResult]],
        course_id: str,
        seeds: List[int] = None
    ) -> InternalConsensus:
        """
        Calcule le consensus de Borda sur plusieurs variantes.
        """
        if not variantes_results:
            raise ValueError(f"[{course_id}] Aucun résultat de simulation fourni")

        if len(variantes_results) < 2:
            logger.warning(f"[{course_id}] Une seule variante — consensus peu fiable")

        if seeds is None:
            seeds = list(range(len(variantes_results)))

        all_numeros = [r.numero for r in variantes_results[0]]
        n = len(all_numeros)

        borda_scores: Dict[int, int] = {num: 0 for num in all_numeros}

        # Classements de chaque variante (pour calcul de robustesse)
        classements_par_variante: List[List[int]] = []

        for variante in variantes_results:
            # Trier par win_prob décroissant pour cette variante
            ranked = sorted(variante, key=lambda x: x.win_prob, reverse=True)
            classement = [r.numero for r in ranked]
            classements_par_variante.append(classement)

            # Attribuer les points Borda
            for rank, r in enumerate(ranked):
                points = n - 1 - rank
                borda_scores[r.numero] += points

        # Classement final par score Borda décroissant
        final_ranking = sorted(all_numeros, key=lambda num: borda_scores[num], reverse=True)

        # Scores Borda formatés pour stockage
        scores_borda_full = {str(num): borda_scores[num] for num in all_numeros}

        # Calcul dynamique de la robustesse
        robuste, confiance = BordaConsensus._compute_robustness(
            classements_par_variante,
            final_ranking,
            config.borda_threshold
        )

        logger.info(
            f"[{course_id}] Borda: #1={final_ranking[0]} "
            f"(score={borda_scores[final_ranking[0]]}) | "
            f"robuste={robuste} | confiance={confiance:.2f}"
        )

        return InternalConsensus(
            course_id         = course_id,
            nb_variantes      = len(variantes_results),
            variants_seeds    = seeds if seeds else list(range(len(variantes_results))),
            consensus_borda   = final_ranking,
            scores_borda_full = scores_borda_full,
            robuste_threshold = config.borda_threshold,
            robuste           = robuste,
            confiance_interne = round(confiance, 3)
        )

    @staticmethod
    def _compute_robustness(
        classements: List[List[int]],
        final_ranking: List[int],
        threshold: float
    ):
        """
        Calcule la robustesse du consensus.
        Mesure : dans quelle proportion des variantes le cheval #1 est-il classé premier ?
        """
        if not classements or not final_ranking:
            return False, 0.0

        winner = final_ranking[0]
        nb_variantes = len(classements)

        # Compter les variantes où le gagnant Borda est classé 1er ou 2e
        winner_top2_count = sum(
            1 for classement in classements
            if classement.index(winner) < 2
        )

        robustesse_score = winner_top2_count / nb_variantes

        # Calcul de la confiance globale :
        # moyenne de la fréquence top-2 du top-3 Borda sur toutes les variantes
        top3_borda = final_ranking[:3]
        top3_consistencies = []

        for cheval in top3_borda:
            count = sum(
                1 for classement in classements
                if cheval in classement[:3]
            )
            top3_consistencies.append(count / nb_variantes)

        confiance = sum(top3_consistencies) / len(top3_consistencies) if top3_consistencies else 0.0
        robuste   = robustesse_score >= threshold

        return robuste, confiance


# Instance globale
borda_consensus = BordaConsensus()
