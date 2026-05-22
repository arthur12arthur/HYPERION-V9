"""HYPERION V9 — Run Manager"""
from domain.schemas import PipelineRun, PipelineState
from utils.helpers import today_str, now_iso, generate_run_id
from utils.logger  import get_logger
logger = get_logger(__name__)

class RunManager:
    def create_run(self, mode: str = "morning_analysis") -> PipelineRun:
        run = PipelineRun(
            run_id=generate_run_id(), date=today_str(),
            statut=PipelineState.CREATED, heure_debut=now_iso(), mode=mode
        )
        logger.info(f"[RUN] Nouveau run: {run.run_id}")
        return run

    def finalize_run(self, run: PipelineRun, success: bool) -> PipelineRun:
        run.heure_fin = now_iso()
        run.statut = PipelineState.DELIVERED if success else PipelineState.FAILED_PARTIAL
        try:
            from infrastructure.firebase_manager import firebase_manager
            firebase_manager.save_pipeline_run(run.run_id, run.dict())
        except Exception as e:
            logger.error(f"[RUN] Save failed: {e}")
        return run

run_manager = RunManager()
