"""
HYPERION V9 — Score Tracker
Maintient et met à jour les scores cumulés sur 30 jours dans Firebase.
"""
from typing import Dict
from utils.logger import get_logger

logger = get_logger(__name__)


class ScoreTracker:

    def get_running_scores(self, date_str: str = None) -> Dict[str, float]:
        """Charge les scores cumulés depuis Firebase."""
        try:
            from infrastructure.firebase_manager import firebase_manager
            doc = firebase_manager.get_running_scores()
            if doc:
                return doc
        except Exception as e:
            logger.warning(f"[TRACKER] Firebase load failed: {e}")
        return {"running_top1": 0.0, "running_top3": 0.0, "days_evaluated": 0}

    def update_running_scores(
        self,
        running_top1: float,
        running_top3: float,
        days_evaluated: int
    ):
        """Sauvegarde les scores cumulés dans Firebase."""
        data = {
            "running_top1"  : running_top1,
            "running_top3"  : running_top3,
            "days_evaluated": days_evaluated
        }
        try:
            from infrastructure.firebase_manager import firebase_manager
            firebase_manager.save_running_scores(data)
            logger.info(
                f"[TRACKER] J{days_evaluated}: "
                f"Top1={running_top1:.1f}% | Top3={running_top3:.1f}%"
            )
        except Exception as e:
            logger.error(f"[TRACKER] Firebase save failed: {e}")

    def get_day_number(self) -> int:
        """Retourne le numéro du jour actuel (1-30)."""
        scores = self.get_running_scores()
        return scores.get("days_evaluated", 0) + 1


score_tracker = ScoreTracker()
