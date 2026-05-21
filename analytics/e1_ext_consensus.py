"""
HYPERION V9 — E1 External Consensus
Construit le consensus Borda depuis les pronostics externes.
Déjà partiellement géré dans web_scraper.py —
ce module centralise et enrichit la logique.
"""
from typing import List, Dict
from domain.schemas import ExternalData, ExternalConsensus, ExternalQualite
from utils.logger import get_logger
from utils.config import config

logger = get_logger(__name__)


class E1ExternalConsensus:
    """
    Étape E1 : construit l'ExternalConsensus depuis ExternalData.
    Applique la méthode Borda pondérée par la confiance de chaque source.
    """

    def compute(
        self,
        course_id: str,
        external_data: ExternalData,
        sources_config: List[dict] = None
    ) -> ExternalConsensus:
        """
        Construit le consensus externe pondéré.

        La pondération tient compte de la confiance de chaque source
        (définie dans sources.yaml).
        """
        if external_data.nb_sources == 0 or not external_data.aggregation:
            logger.info(f"[E1] {course_id}: aucune source externe — consensus vide")
            return ExternalConsensus(
                course_id = course_id,
                qualite   = ExternalQualite.INDISPONIBLE
            )

        # Récupérer les confiances depuis la config
        confiances: Dict[str, float] = {}
        if sources_config:
            for src in sources_config:
                confiances[src.get("nom", "")] = src.get("confiance", 0.5)
        else:
            # Confiances par défaut
            confiances = {
                "Paris-Turf": 0.85,
                "Equidia":    0.80,
                "Zone-Turf":  0.65,
            }

        all_numeros = set()
        for key in external_data.aggregation:
            try:
                all_numeros.add(int(key))
            except ValueError:
                continue

        if not all_numeros:
            return ExternalConsensus(
                course_id = course_id,
                qualite   = ExternalQualite.INDISPONIBLE
            )

        # Score Borda pondéré par source
        borda_scores: Dict[int, float] = {num: 0.0 for num in all_numeros}
        n = len(all_numeros)

        for key, data in external_data.aggregation.items():
            try:
                num     = int(key)
                mentions = data.get("mentions", 0)
                ranks    = data.get("ranks", [])

                if not ranks:
                    continue

                avg_rank = sum(ranks) / len(ranks)

                # Points Borda inversés par rang (1er = n-1 points)
                borda_pts = max(0, n - avg_rank)

                # Pondération par confiance de la source
                # On utilise la confiance moyenne des sources qui ont mentionné ce cheval
                source_confiance = sum(
                    confiances.get(s.nom, 0.5)
                    for s in external_data.sources
                ) / max(len(external_data.sources), 1)

                borda_scores[num] += borda_pts * source_confiance * mentions

            except (ValueError, ZeroDivisionError):
                continue

        # Tri final
        top5_sorted = sorted(
            borda_scores.keys(),
            key=lambda n: borda_scores[n],
            reverse=True
        )[:5]

        # Normalisation des scores (0-1)
        max_score = max(borda_scores.values()) if borda_scores else 1
        ext_scores = {
            str(num): round(borda_scores[num] / max_score, 3)
            for num in top5_sorted
        }

        # Qualité selon nb sources et scores
        if external_data.nb_sources >= 3:
            qualite = ExternalQualite.HAUTE
        elif external_data.nb_sources == 2:
            qualite = ExternalQualite.MOYENNE
        elif external_data.nb_sources == 1:
            qualite = ExternalQualite.FAIBLE
        else:
            qualite = ExternalQualite.INDISPONIBLE

        logger.info(
            f"[E1] {course_id}: top5={top5_sorted} | "
            f"qualité={qualite.value} | {external_data.nb_sources} sources"
        )

        return ExternalConsensus(
            course_id          = course_id,
            sources_pronostics = [s.nom for s in external_data.sources],
            top5_external      = top5_sorted,
            external_scores    = ext_scores,
            qualite            = qualite
        )


# Instance globale
e1_ext_consensus = E1ExternalConsensus()
