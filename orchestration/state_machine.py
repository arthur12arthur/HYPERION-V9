"""HYPERION V9 — State Machine"""
from domain.schemas import PipelineState
from utils.logger import get_logger
logger = get_logger(__name__)

TRANSITIONS = {
    PipelineState.CREATED          : [PipelineState.LONAB_IDENTIFIED, PipelineState.FAILED_FATAL],
    PipelineState.LONAB_IDENTIFIED : [PipelineState.COURSES_SELECTED, PipelineState.FAILED_PARTIAL],
    PipelineState.COURSES_SELECTED : [PipelineState.EXTRACTED, PipelineState.FAILED_PARTIAL],
    PipelineState.EXTRACTED        : [PipelineState.ENRICHED, PipelineState.SCORED],
    PipelineState.ENRICHED         : [PipelineState.SCORED],
    PipelineState.SCORED           : [PipelineState.SIMULATED, PipelineState.FAILED_PARTIAL],
    PipelineState.SIMULATED        : [PipelineState.FUSED],
    PipelineState.FUSED            : [PipelineState.RISK_ANALYZED, PipelineState.REPORTED],
    PipelineState.RISK_ANALYZED    : [PipelineState.REPORTED],
    PipelineState.REPORTED         : [PipelineState.DELIVERED, PipelineState.FAILED_PARTIAL],
    PipelineState.DELIVERED        : [PipelineState.RESULTS_FETCHED, PipelineState.EVALUATED],
    PipelineState.RESULTS_FETCHED  : [PipelineState.EVALUATED],
    PipelineState.EVALUATED        : [PipelineState.ARCHIVED],
    PipelineState.ARCHIVED         : [],
    PipelineState.FAILED_PARTIAL   : [PipelineState.REPORTED, PipelineState.ARCHIVED],
    PipelineState.FAILED_FATAL     : []
}

class StateMachine:
    def __init__(self):
        self.state = PipelineState.CREATED

    def transition(self, new_state: PipelineState) -> bool:
        allowed = TRANSITIONS.get(self.state, [])
        if new_state in allowed:
            logger.info(f"[STATE] {self.state.value} -> {new_state.value}")
            self.state = new_state
            return True
        logger.error(f"[STATE] Transition invalide: {self.state.value} -> {new_state.value}")
        return False

    def fail(self, fatal: bool = False):
        self.state = PipelineState.FAILED_FATAL if fatal else PipelineState.FAILED_PARTIAL
