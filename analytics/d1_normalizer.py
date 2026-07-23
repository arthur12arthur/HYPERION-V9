import logging
from typing import List
from domain.schemas import Course, Runner

logger = logging.getLogger(__name__)

class Normalizer:
    @staticmethod
    def process(course: Course) -> Course:
        """
        D1 - Filtrage & Normalisation
        1. Supprimer non-partants
        2. Rejeter Runner avec cote <= 0
        3. Parser forme_brute
        4. Normaliser poids
        """
        valid_runners = []
        for r in course.partants:
            if r.is_non_partant:
                continue
            if r.cote_officielle <= 0:
                continue
            
            # Parsing forme_brute "1a 2a 3a" -> [1, 2, 3]
            try:
                r.forme_parsed = [int(x[0]) for x in r.forme_brute.split() if x[0].isdigit()]
            except Exception:
                r.forme_parsed = []
                
            valid_runners.append(r)
            
        course.partants = valid_runners
        logger.info(f"Normalisation terminée pour la course {course.course_id}: {len(valid_runners)} partants valides.")
        return course
