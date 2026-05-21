"""
HYPERION V9 — Fusion Engine
Orchestre la collecte et fusion de toutes les sources de données
pour produire des courses enrichies prêtes pour l'analytique.
"""
from typing import List, Tuple, Optional
from domain.schemas import Course, ExternalData, ExternalConsensus

from data.pmu_adapter   import pmu_adapter
from data.web_scraper   import web_scraper
from data.data_merger   import data_merger
from utils.logger       import get_logger
from utils.helpers      import today_str

logger = get_logger(__name__)


class FusionEngine:
    """
    Combine LONAB + PMU + sources externes en un package complet
    prêt pour le moteur analytique (D1-D4).
    """

    def __init__(self):
        self.monitor = None

    def set_monitor(self, monitor):
        self.monitor = monitor
        pmu_adapter.set_monitor(monitor)
        web_scraper.set_monitor(monitor)

    def _log(self, step: str, status: str, msg: str = ""):
        logger.info(f"[FUSION] {step}: {status} {msg}".strip())

    def enrich_all_courses(
        self,
        courses: List[Course]
    ) -> List[Tuple[Course, ExternalData, ExternalConsensus]]:
        """
        Enrichit toutes les courses avec données PMU + sources externes.

        Returns:
            Liste de tuples (course_enrichie, external_data, external_consensus)
        """
        enriched = []

        for course in courses:
            try:
                result = self.enrich_single_course(course)
                enriched.append(result)
            except Exception as e:
                logger.error(f"[FUSION] Erreur enrichissement {course.course_id}: {e}")
                # Retourner la course telle quelle avec données externes vides
                empty_ext = ExternalData(course_id=course.course_id, nb_sources=0)
                empty_con = ExternalConsensus(
                    course_id=course.course_id,
                    qualite="INDISPONIBLE"
                )
                enriched.append((course, empty_ext, empty_con))

        self._log("ALL", "DONE", f"{len(enriched)}/{len(courses)} courses enrichies")
        return enriched

    def enrich_single_course(
        self,
        course: Course
    ) -> Tuple[Course, ExternalData, ExternalConsensus]:
        """
        Enrichit une seule course :
        1. Enrichissement partants PMU si vides
        2. Collecte pronostics externes
        3. Construction consensus externe
        4. Normalisation finale
        """
        # Étape 1 : enrichir les partants si nécessaire
        if len(course.partants) == 0:
            pmu_runners = pmu_adapter.get_runners(course)
            course = data_merger.merge_course_data(course, pmu_runners)
        else:
            # Normaliser les partants existants
            course = data_merger.merge_course_data(course, None)

        self._log(course.course_id, "PARTANTS",
                 f"{len(course.partants)} partants normalisés")

        # Étape 2 : pronostics externes (scraping pur)
        external_data = web_scraper.enrich_course(course)
        self._log(course.course_id, "EXTERNE",
                 f"{external_data.nb_sources} sources | qualité={external_data.qualite_score:.2f}")

        # Étape 3 : consensus externe
        external_consensus = web_scraper.build_external_consensus(course, external_data)
        self._log(course.course_id, "CONSENSUS_EXT",
                 f"top5={external_consensus.top5_external} | {external_consensus.qualite.value}")

        return course, external_data, external_consensus


# Instance globale
fusion_engine = FusionEngine()
