"""
HYPERION V9 — E3 Tie-Break Pairwise
Départage les chevaux à meta_score très proche
en analysant les confrontations directes dans les simulations.
"""
from typing import List, Dict, Tuple
from domain.schemas import MetaPrediction, MonteCarloResult, TopPrediction
from utils.logger import get_logger

logger = get_logger(__name__)

# Seuil de proximité : si |score_A - score_B| < THRESHOLD → appliquer le tiebreak
TIEBREAK_THRESHOLD = 0.03


class E3TieBreak:
    """
    Étape E3 : affine le classement en cas d'égalité proche.
    Compare les chevaux par confrontations directes dans les simulations MC.
    """

    def apply(
        self,
        top_prediction: TopPrediction,
        all_mc_results: List[List[MonteCarloResult]]
    ) -> TopPrediction:
        """
        Vérifie si des chevaux consécutifs méritent un départage.
        Si oui, applique le tiebreak pairwise.

        Args:
            top_prediction : TopPrediction issue de E2 (classement provisoire)
            all_mc_results : les 5 variantes MC (List[List[MonteCarloResult]])

        Returns:
            TopPrediction avec classement affiné si nécessaire
        """
        predictions = top_prediction.predictions
        if len(predictions) < 2:
            return top_prediction

        # Construire la matrice de confrontations directes depuis les simulations
        pairwise_matrix = self._build_pairwise_matrix(all_mc_results)

        # Vérifier chaque paire consécutive
        reordered = list(predictions)
        swapped   = False

        for i in range(len(reordered) - 1):
            a = reordered[i]
            b = reordered[i + 1]

            # Score proche → appliquer tiebreak
            if abs(a.meta_score - b.meta_score) < TIEBREAK_THRESHOLD:
                winner = self._pairwise_winner(a.numero, b.numero, pairwise_matrix)

                if winner == b.numero:
                    # B bat A en direct → inverser
                    reordered[i], reordered[i + 1] = reordered[i + 1], reordered[i]
                    # Mettre à jour les positions
                    reordered[i]     = reordered[i].copy(update={"position": i + 1})
                    reordered[i + 1] = reordered[i + 1].copy(update={"position": i + 2})
                    swapped = True
                    logger.info(
                        f"[E3] {top_prediction.course_id}: "
                        f"Tiebreak #{a.numero} vs #{b.numero} → #{winner} gagne"
                    )

        if not swapped:
            logger.debug(f"[E3] {top_prediction.course_id}: aucun tiebreak nécessaire")

        # Mettre à jour le classement legacy
        new_classement = [p.numero for p in reordered]

        return top_prediction.copy(update={
            "predictions"    : reordered,
            "classement_final": new_classement
        })

    def _build_pairwise_matrix(
        self,
        all_mc_results: List[List[MonteCarloResult]]
    ) -> Dict[Tuple[int, int], int]:
        """
        Construit une matrice de confrontations directes.
        pairwise[(A, B)] = nb de simulations où A a battu B.

        Pour 5 variantes × 10 000 sims, on agrège les win_prob relatives.
        """
        if not all_mc_results:
            return {}

        # Collecter tous les numéros
        all_numeros = set()
        for variante in all_mc_results:
            for mc in variante:
                all_numeros.add(mc.numero)

        # Pour chaque variante, construire le classement par win_prob
        # et compter les confrontations directes
        pairwise: Dict[Tuple[int, int], float] = {}

        for variante in all_mc_results:
            # Trier par win_prob décroissant = ordre prédit
            ranked = sorted(variante, key=lambda r: r.win_prob, reverse=True)
            numeros_ranked = [r.numero for r in ranked]
            n = len(numeros_ranked)

            # Chaque cheval bat tous ceux classés après lui
            for i in range(n):
                for j in range(i + 1, n):
                    a = numeros_ranked[i]
                    b = numeros_ranked[j]
                    key = (a, b)
                    pairwise[key] = pairwise.get(key, 0) + 1

        return pairwise

    def _pairwise_winner(
        self,
        num_a: int,
        num_b: int,
        matrix: Dict[Tuple[int, int], int]
    ) -> int:
        """
        Retourne le numéro du cheval qui bat l'autre en confrontation directe.
        """
        score_a = matrix.get((num_a, num_b), 0)
        score_b = matrix.get((num_b, num_a), 0)

        if score_a >= score_b:
            return num_a
        return num_b


# Instance globale
e3_tiebreak = E3TieBreak()
