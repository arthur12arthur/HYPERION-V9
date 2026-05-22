"""
HYPERION V9 — Pipeline Monitor (Agent I - Core)
Surveille chaque étape en temps réel.
Logge, alerte, construit le rapport de santé.
"""
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from utils.logger import get_logger
from utils.helpers import now_iso

logger = get_logger(__name__)


@dataclass
class StepLog:
    name      : str
    status    : str        # "OK" | "WARNING" | "FAIL" | "SKIP"
    message   : str = ""
    timestamp : str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = now_iso()


class PipelineMonitor:
    """
    Agent I — Surveillance temps réel du pipeline.
    Collecte tous les logs d'étapes et déclenche
    les alertes Telegram si nécessaire.
    """

    def __init__(self):
        self.steps      : List[StepLog] = []
        self.start_time : float         = time.time()
        self.gemini_key1_calls : int    = 0
        self.gemini_key2_calls : int    = 0
        self.active_key : str           = "KEY1"
        self._alerter   = None

    def set_alerter(self, alerter):
        self._alerter = alerter

    def log(self, step: str, status: str, message: str = ""):
        """Enregistre le résultat d'une étape."""
        entry = StepLog(name=step, status=status, message=message)
        self.steps.append(entry)

        level = {
            "OK"     : logger.info,
            "WARNING": logger.warning,
            "FAIL"   : logger.error,
            "SKIP"   : logger.debug
        }.get(status, logger.info)

        level(f"[MONITOR] {step}: {status} {message}".strip())

        if status == "FAIL" and self._is_critical(step):
            self._send_immediate_alert(step, message)

    def update_quota(self, key_id: str, calls: int):
        if key_id == "KEY1":
            self.gemini_key1_calls = calls
        else:
            self.gemini_key2_calls = calls
        self.active_key = key_id

    def alert_telegram(self, message: str):
        if self._alerter:
            try:
                self._alerter.send_alert(message)
            except Exception as e:
                logger.error(f"[MONITOR] Alert failed: {e}")
        else:
            logger.warning(f"[MONITOR] Alert (no alerter): {message[:100]}")

    def _send_immediate_alert(self, step: str, message: str):
        text = (
            f"HYPERION — Étape critique KO\n"
            f"Étape : {step}\n"
            f"Erreur : {message[:200]}"
        )
        self.alert_telegram(text)

    def _is_critical(self, step: str) -> bool:
        critical = [
            "LONAB_ALL_METHODS", "PMU_PROGRAMME",
            "SCORING", "MONTE_CARLO",
            "FIREBASE_SAVE", "TELEGRAM_SEND"
        ]
        return any(c in step.upper() for c in critical)

    def get_summary(self) -> dict:
        duration = round(time.time() - self.start_time, 1)
        ok       = [s for s in self.steps if s.status == "OK"]
        warnings = [s for s in self.steps if s.status == "WARNING"]
        fails    = [s for s in self.steps if s.status == "FAIL"]

        return {
            "total_steps" : len(self.steps),
            "ok"          : len(ok),
            "warnings"    : len(warnings),
            "failures"    : len(fails),
            "duration_s"  : duration,
            "gemini_key1" : self.gemini_key1_calls,
            "gemini_key2" : self.gemini_key2_calls,
            "active_key"  : self.active_key,
            "steps"       : [
                {"name": s.name, "status": s.status, "msg": s.message}
                for s in self.steps
            ]
        }

    def reset(self):
        self.steps      = []
        self.start_time = time.time()


# Instance globale
pipeline_monitor = PipelineMonitor()
