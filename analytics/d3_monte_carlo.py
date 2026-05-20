"""
HYPERION V9 — Monte Carlo Engine (D3)
50 000 simulations par course (5 variantes × 10 000)
"""
import numpy as np
from typing import List
from domain.schemas import ScoredRunner, MonteCarloResult
from utils.logger import get_logger
from utils.config import config

logger = get_logger(__name__)

SEEDS_DEFAULT = [42, 43, 44, 45, 46]


class MonteCarloEngine:
    """
    Moteur de simulation Monte Carlo.
    Utilise un RNG par seed (thread-safe) au lieu de np.random.seed() global.
    """

    def __init__(self):
        self.simulations = config.mc_simulations   # 10 000
        self.sigma       = config.mc_sigma          # 0.15
        self.nb_variantes = config.mc_variantes     # 5

    def run_simulation(self, runners: List[ScoredRunner], seed: int) -> List[MonteCarloResult]:
        """
        Lance N simulations pour une variante donnée.
        Utilise un générateur RNG local (thread-safe).
        """
        if not runners:
            return []

        # RNG local — évite les conflits si 5 variantes tournent en parallèle
        rng = np.random.default_rng(seed)

        n = len(runners)
        win_counts   = {r.numero: 0 for r in runners}
        place_counts = {r.numero: 0 for r in runners}
        top3_counts  = {r.numero: 0 for r in runners}
        rank_sums    = {r.numero: 0 for r in runners}

        base_scores = np.array([r.score_global for r in runners])
        numeros     = [r.numero for r in runners]

        for _ in range(self.simulations):
            # Perturbation gaussienne sur les scores
            noise      = rng.normal(0, self.sigma, size=n)
            sim_scores = base_scores + noise

            # Classement par score décroissant
            ranked_idx = np.argsort(-sim_scores)

            for rank, idx in enumerate(ranked_idx):
                num = numeros[idx]
                rank_sums[num] += rank + 1  # rang 1-based

                if rank == 0:
                    win_counts[num] += 1
                if rank < 2:
                    place_counts[num] += 1
                if rank < 3:
                    top3_counts[num] += 1

        results = []
        for r in runners:
            win_prob   = win_counts[r.numero] / self.simulations
            place_prob = place_counts[r.numero] / self.simulations
            top3_prob  = top3_counts[r.numero] / self.simulations
            exp_rank   = rank_sums[r.numero] / self.simulations

            # confiance_mc : basée sur la concentration des victoires
            # Plus win_prob est stable → plus c'est fiable
            confiance_mc = min(1.0, win_prob * 3.0) if win_prob > 0 else 0.0

            results.append(MonteCarloResult(
                numero       = r.numero,
                cheval_nom   = r.nom,
                win_prob     = round(win_prob, 4),
                place_prob   = round(place_prob, 4),
                top3_prob    = round(top3_prob, 4),
                expected_rank= round(exp_rank, 2),
                confiance_mc = round(confiance_mc, 3),
                simulations  = self.simulations,
                seed         = seed
            ))

        return results

    def run_all_variants(
        self,
        runners: List[ScoredRunner],
        seeds: List[int] = None
    ) -> List[List[MonteCarloResult]]:
        """
        Lance les 5 variantes Monte Carlo sur la même liste de runners.
        Retourne une liste de 5 résultats (un par seed).
        """
        if seeds is None:
            seeds = SEEDS_DEFAULT[:self.nb_variantes]

        if not runners:
            logger.warning("run_all_variants: liste runners vide")
            return []

        logger.info(
            f"Monte Carlo: {len(runners)} partants × "
            f"{self.simulations} sims × {len(seeds)} variantes"
        )

        all_variants = []
        for seed in seeds:
            variant_results = self.run_simulation(runners, seed)
            all_variants.append(variant_results)

        logger.info(f"Monte Carlo terminé: {len(seeds) * self.simulations} simulations totales")
        return all_variants


# Instance globale
mc_engine = MonteCarloEngine()
