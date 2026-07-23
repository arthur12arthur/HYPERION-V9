import requests
import logging
from typing import List
from domain.schemas import Course, Runner

logger = logging.getLogger(__name__)

class PmuAdapter:
    BASE_URL = "https://www.pmu.fr/turf/api/v1/programme"

    @staticmethod
    def get_daily_program(date_str: str) -> List[Course]:
        """
        Récupère le programme PMU pour une date donnée (format YYYYMMDD).
        """
        try:
            # Note: PMU API est souvent protégée ou changeante. 
            # Ceci est une structure d'appel type.
            # response = requests.get(f"{PmuAdapter.BASE_URL}/{date_str}")
            # data = response.json()
            
            logger.info(f"Récupération du programme PMU pour le {date_str}")
            # Simulation de données pour le développement
            return [PmuAdapter._mock_course(date_str)]
        except Exception as e:
            logger.error(f"Erreur lors de la récupération PMU: {e}")
            return []

    @staticmethod
    def _mock_course(date_str: str) -> Course:
        return Course(
            course_id="R1C1",
            nom="Prix d'Amérique",
            hippodrome="Vincennes",
            date=date_str,
            heure="15:15",
            partants=[
                Runner(numero=1, nom="Face Time Bourbon", cote_officielle=2.5, poids=0, forme_brute="1a 2a 1a"),
                Runner(numero=2, nom="Davidson du Pont", cote_officielle=4.8, poids=0, forme_brute="3a 1a 2a"),
                Runner(numero=3, nom="Belina Josselyn", cote_officielle=8.2, poids=0, forme_brute="5a 4a 1a"),
            ]
        )
