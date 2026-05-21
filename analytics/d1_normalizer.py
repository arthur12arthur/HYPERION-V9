"""
HYPERION V9 — D1 Normalizer
Filtrage et normalisation des partants avant scoring.
Étape critique : données propres = résultats fiables.
"""
from typing import List, Tuple, Dict
from domain.schemas import Runner, ScoredRunner, Course
from utils.logger import get_logger
from utils.validators import filter_valid_runners, parse_forme
from utils.config import config

logger = get_logger(__name__)

POIDS_REF = 58.0  # poids de référence pour le handicap


class D1Normalizer:
    """
    Étape D1 du moteur analytique.
    Nettoie, valide et prépare les Runner pour le scoring.
    """

    def process(self, course: Course) -> Tuple[List[Runner], List[str]]:
        """
        Normalise les partants d'une course.

        Returns:
            (runners_valides, messages_log)
        """
        messages = []
        runners  = course.partants

        if not runners:
            logger.warning(f"[D1] {course.course_id}: aucun partant")
            return [], [f"Course {course.course_id}: aucun partant"]

        # 1. Filtrage strict
        valid, rejected = filter_valid_runners(runners)

        if rejected:
            messages.append(
                f"[D1] {course.course_id}: {len(rejected)} partants rejetés "
                f"(#{[r.numero for r in rejected]})"
            )

        if len(valid) < 3:
            messages.append(
                f"[D1] {course.course_id}: seulement {len(valid)} partants valides "
                f"— course non analysable"
            )
            return [], messages

        # 2. Normalisation des formes
        normalized = []
        for runner in valid:
            runner = self._normalize_forme(runner)
            runner = self._normalize_poids(runner)
            runner = self._normalize_cote(runner, valid)
            normalized.append(runner)

        messages.append(
            f"[D1] {course.course_id}: {len(normalized)} partants normalisés ✅"
        )
        logger.info(f"[D1] {course.course_id}: {len(normalized)}/{len(runners)} OK")
        return normalized, messages

    def _normalize_forme(self, runner: Runner) -> Runner:
        """Parse la forme brute si forme_parsed est vide."""
        if runner.forme_brute and not runner.forme_parsed:
            parsed = parse_forme(runner.forme_brute)
            return runner.copy(update={"forme_parsed": parsed})
        return runner

    def _normalize_poids(self, runner: Runner) -> Runner:
        """Corrige un poids aberrant."""
        poids = runner.poids
        # Poids hors normes pour les courses françaises (50-65 kg)
        if poids < 50 or poids > 70:
            return runner.copy(update={"poids": POIDS_REF})
        return runner

    def _normalize_cote(self, runner: Runner, all_runners: List[Runner]) -> Runner:
        """Remplace une cote à 0 par la cote moyenne des autres."""
        if runner.cote_officielle > 0:
            return runner

        valid_cotes = [r.cote_officielle for r in all_runners
                      if r.cote_officielle > 0 and r.numero != runner.numero]
        if valid_cotes:
            cote_avg = sum(valid_cotes) / len(valid_cotes)
            return runner.copy(update={"cote_officielle": round(cote_avg, 2)})
        return runner


# Instance globale
d1_normalizer = D1Normalizer()
