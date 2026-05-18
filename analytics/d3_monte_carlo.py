import numpy as np
from typing import List
from domain.schemas import ScoredRunner, MonteCarloResult

class MonteCarloEngine:
    def __init__(self, simulations: int = 10000, sigma: float = 0.15):
        self.simulations = simulations
        self.sigma = sigma

    def run_simulation(self, runners: List[ScoredRunner], seed: int) -> List[MonteCarloResult]:
        np.random.seed(seed)
        win_counts = {r.numero: 0 for r in runners}
        place_counts = {r.numero: 0 for r in runners}
        top3_counts = {r.numero: 0 for r in runners}

        for _ in range(self.simulations):
            sim_scores = []
            for r in runners:
                # Perturber les scores avec un bruit gaussien
                noise = np.random.normal(0, self.sigma)
                sim_score = r.score_global + noise
                sim_scores.append((r.numero, sim_score))

            # Classer les coureurs par score simulé (descendant)
            ranked = sorted(sim_scores, key=lambda x: x[1], reverse=True)
            
            # Mise à jour des probabilités
            win_counts[ranked[0][0]] += 1
            for i in range(min(2, len(ranked))):
                place_counts[ranked[i][0]] += 1
            for i in range(min(3, len(ranked))):
                top3_counts[ranked[i][0]] += 1

        results = []
        for r in runners:
            results.append(MonteCarloResult(
                numero=r.numero,
                win_prob=win_counts[r.numero] / self.simulations,
                place_prob=place_counts[r.numero] / self.simulations,
                top3_prob=top3_counts[r.numero] / self.simulations
            ))
        return results
