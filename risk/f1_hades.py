import logging
from typing import List, Dict
from domain.schemas import TopPrediction

logger = logging.getLogger(__name__)

class HadesRiskManager:
    """
    Agent F1 - HADES (Hazard Detection & Evaluation System)
    """
    def __init__(self, mode_test: bool = True):
        self.mode_test = mode_test

    def analyze_prediction(self, prediction: TopPrediction) -> Dict:
        """
        Analyse les risques d'une prédiction.
        """
        alerts = []
        
        # Exemple de détection d'anomalie : confiance trop faible
        if len(prediction.confiance_etoiles) < 2:
            alerts.append("⚠️ Confiance faible détectée")

        # Logique HADES
        if alerts:
            for alert in alerts:
                logger.warning(f"HADES Alert: {alert}")
                
        return {
            "prediction_id": prediction.course_id,
            "alerts": alerts,
            "blocked": False if self.mode_test else len(alerts) > 0,
            "mode": "TEST" if self.mode_test else "PRODUCTION"
        }
