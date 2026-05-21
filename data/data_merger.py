"""
HYPERION V9 — Data Merger
Nettoie, fusionne et normalise les données multi-sources
avant de les passer au moteur analytique.
"""
from typing import List, Optional, Dict
from domain.schemas import Course, Runner, ScoredRunner
from utils.logger import get_logger
from utils.validators import filter_valid_runners, validate_runner_relaxed, parse_forme
from utils.config import config

logger = get_logger(__name__)


class DataMerger:
    """
    Prépare les données pour le pipeline analytique.
    Fusionne les données LONAB + PMU + sources externes.
    """

    def merge_course_data(
        self,
        course: Course,
        pmu_runners: Optional[List[Runner]] = None
    ) -> Course:
        """
        Fusionne les partants LONAB avec les données enrichies PMU.
        LONAB = source de vérité pour les numéros et noms.
        PMU = enrichissement (cotes live, forme, jockey...).
        """
        if not pmu_runners:
            # Pas de données PMU — utiliser LONAB seul
            logger.info(f"[MERGE] {course.course_id}: LONAB seul ({len(course.partants)} partants)")
            return self._normalize_course(course)

        # Créer un index PMU par numéro
        pmu_index: Dict[int, Runner] = {r.numero: r for r in pmu_runners}

        merged_runners = []
        for lonab_runner in course.partants:
            pmu_runner = pmu_index.get(lonab_runner.numero)

            if pmu_runner:
                # Fusionner : LONAB donne l'identité, PMU enrichit
                merged = self._merge_runner(lonab_runner, pmu_runner)
            else:
                # Partant LONAB sans correspondance PMU — garder LONAB
                merged = lonab_runner

            merged_runners.append(merged)

        course.partants = merged_runners
        logger.info(
            f"[MERGE] {course.course_id}: "
            f"{len(merged_runners)} partants fusionnés "
            f"({len(pmu_index)} depuis PMU)"
        )
        return self._normalize_course(course)

    def _merge_runner(self, lonab: Runner, pmu: Runner) -> Runner:
        """
        Fusionne deux Runner — LONAB a priorité sur l'identité,
        PMU enrichit les données manquantes.
        """
        return Runner(
            numero          = lonab.numero,
            nom             = lonab.nom or pmu.nom,
            age             = lonab.age or pmu.age,
            sexe            = lonab.sexe or pmu.sexe,
            poids           = lonab.poids if lonab.poids != 58.0 else pmu.poids,
            corde           = lonab.corde or pmu.corde,
            forme_brute     = lonab.forme_brute or pmu.forme_brute,
            forme_parsed    = lonab.forme_parsed or pmu.forme_parsed or
                              parse_forme(lonab.forme_brute or pmu.forme_brute or ""),
            gains_totaux    = lonab.gains_totaux or pmu.gains_totaux,
            jockey          = lonab.jockey or pmu.jockey,
            entraineur      = lonab.entraineur or pmu.entraineur,
            proprietaire    = lonab.proprietaire or pmu.proprietaire,
            # Cote : préférer PMU (plus fraîche) si disponible
            cote_officielle = pmu.cote_officielle if pmu.cote_officielle > 0
                              else lonab.cote_officielle,
            source          = f"MERGED_{lonab.source}+{pmu.source}"
        )

    def _normalize_course(self, course: Course) -> Course:
        """Normalise et filtre les partants d'une course."""
        valid_runners, rejected = filter_valid_runners(course.partants)

        # Appliquer RELAXED sur les runners valides avec données manquantes
        normalized = []
        for runner in valid_runners:
            if not runner.forme_parsed and runner.forme_brute:
                runner = runner.copy(
                    update={"forme_parsed": parse_forme(runner.forme_brute)}
                )
            normalized.append(runner)

        if rejected:
            logger.warning(
                f"[NORMALIZE] {course.course_id}: "
                f"{len(rejected)} partants rejetés"
            )

        course.partants    = normalized
        course.nb_partants = len(normalized)
        return course

    def normalize_runners_list(self, runners: List[Runner]) -> List[Runner]:
        """Normalise une liste de runners standalone."""
        valid, _ = filter_valid_runners(runners)
        return valid


# Instance globale
data_merger = DataMerger()
