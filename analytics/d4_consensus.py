from typing import List, Dict
from domain.schemas import MonteCarloResult, InternalConsensus

class BordaConsensus:
    @staticmethod
    def compute(variantes_results: List[List[MonteCarloResult]], course_id: str) -> InternalConsensus:
        """
        Calcule le consensus de Borda sur plusieurs variantes de Monte Carlo.
        """
        if not variantes_results:
            raise ValueError("Aucun résultat de simulation fourni")

        all_nums = [r.numero for r in variantes_results[0]]
        n = len(all_nums)
        borda_scores = {num: 0 for num in all_nums}

        for variante in variantes_results:
            # Trier les coureurs par win_prob pour cette variante
            ranked = sorted(variante, key=lambda x: x.win_prob, reverse=True)
            for rank, r in enumerate(ranked):
                points = n - 1 - rank
                borda_scores[r.numero] += points

        # Classement final par score de Borda
        final_ranking = sorted(all_nums, key=lambda num: borda_scores[num], reverse=True)
        
        # Calcul de robustesse simplifié (ici arbitraire pour l'exemple)
        # Dans la réalité, on comparerait la variance entre les variantes
        robuste = True 
        
        return InternalConsensus(
            course_id=course_id,
            consensus_borda=final_ranking,
            robuste=robuste,
            confiance_interne=0.85 # Valeur d'exemple
        )
