import logging
from typing import List
from domain.schemas import TopPrediction
from utils.quota_manager import GeminiKeyRotator

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, rotator: GeminiKeyRotator):
        self.rotator = rotator

    def generate_batch_report(self, predictions: List[TopPrediction]) -> str:
        """
        Génère un rapport narratif pour un lot de prédictions via Gemini.
        """
        prompt = self._build_prompt(predictions)
        try:
            report = self.rotator.call_gemini(prompt)
            return report
        except Exception as e:
            logger.error(f"Erreur lors de la génération du rapport Gemini: {e}")
            return self._generate_static_report(predictions)

    def _build_prompt(self, predictions: List[TopPrediction]) -> str:
        content = "\n".join([f"Course {p.course_id}: {p.classement_final[:3]}" for p in predictions])
        return f"Analyse ces prédictions hippiques et rédige un rapport narratif court :\n{content}"

    def _generate_static_report(self, predictions: List[TopPrediction]) -> str:
        report = "📋 RAPPORT HYPERION V9 (MODE STATIQUE)\n\n"
        for p in predictions:
            report += f"Course {p.course_id} : {', '.join(map(str, p.classement_final[:5]))} {p.confiance_etoiles}\n"
        return report
