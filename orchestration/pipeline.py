"""
HYPERION V9 — Pipeline principal
Point d'entrée haut niveau — délègue à l'orchestrateur.
"""
import logging
from orchestration.orchestrator import orchestrator

logger = logging.getLogger("hyperion.pipeline")


class HyperionPipeline:
    """Façade simplifiée sur l'orchestrateur."""

    def run_morning_cycle(self, date_str: str = None, chat_id: str = None) -> bool:
        return orchestrator.run_morning(date_str=date_str, chat_id=chat_id)


if __name__ == "__main__":
    pipeline = HyperionPipeline()
    pipeline.run_morning_cycle()
