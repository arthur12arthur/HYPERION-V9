"""
HYPERION V9 — Auto Evaluator (Agent H - Core)
Compare prédictions du matin vs résultats officiels PMU.
"""
from typing import Dict, List, Optional
from domain.schemas import EvaluationDailyReport, CourseEvaluation
from utils.logger import get_logger

logger = get_logger(__name__)


class AutoEvaluator:

    def evaluate_day(
        self,
        date_str: str,
        day_number: int,
        predictions: Dict[str, dict],
        results: Dict[str, dict],
        running_scores: Dict[str, float]
    ) -> EvaluationDailyReport:

        course_evals = []
        lonab_corrects = []

        for course_id, pred in predictions.items():
            result = results.get(course_id)
            if not result:
                logger.warning(f"[EVAL] {course_id}: résultat absent")
                continue
            ev = self._evaluate_single(course_id, pred, result)
            course_evals.append(ev)
            if pred.get("is_lonab") and ev.top1_correct is not None:
                lonab_corrects.append(ev.top1_correct)

        nb = len(course_evals)
        top1_ok  = sum(1 for c in course_evals if c.top1_correct)
        top3_tot = sum(c.top3_score for c in course_evals)

        score_top1 = (top1_ok / nb * 100) if nb > 0 else 0.0
        score_top3 = (top3_tot / (nb * 3) * 100) if nb > 0 else 0.0

        days_done = running_scores.get("days_evaluated", 0)
        r_top1    = running_scores.get("running_top1", 0.0)
        r_top3    = running_scores.get("running_top3", 0.0)

        if days_done > 0:
            r_top1 = (r_top1 * days_done + score_top1) / (days_done + 1)
            r_top3 = (r_top3 * days_done + score_top3) / (days_done + 1)
        else:
            r_top1, r_top3 = score_top1, score_top3

        lonab_precision = (
            sum(lonab_corrects) / len(lonab_corrects)
            if lonab_corrects else None
        )

        logger.info(
            f"[EVAL] J{day_number}: Top1={score_top1:.1f}% "
            f"({top1_ok}/{nb}) | Top3={score_top3:.1f}%"
        )

        return EvaluationDailyReport(
            date                  = date_str,
            day_number            = day_number,
            courses               = course_evals,
            score_jour_top1       = round(score_top1, 2),
            score_jour_top3       = round(score_top3, 2),
            running_top1_all_days = round(r_top1, 2),
            running_top3_all_days = round(r_top3, 2),
            lonab_precision       = lonab_precision,
            lonab_available       = any(p.get("is_lonab") for p in predictions.values())
        )

    def _evaluate_single(
        self, course_id: str, prediction: dict, result: dict
    ) -> CourseEvaluation:

        pred_top5 = prediction.get("predicted_top5", [])
        pred_top3 = pred_top5[:3]
        pred_win  = pred_top5[0] if pred_top5 else None

        off_win  = result.get("winner")
        off_top3 = result.get("top3", [])
        off_top5 = result.get("top5", [])

        top1_ok    = (pred_win == off_win) if pred_win and off_win else None
        top3_score = len(set(pred_top3) & set(off_top3))
        top5_score = len(set(pred_top5[:5]) & set(off_top5[:5]))

        return CourseEvaluation(
            course_id        = course_id,
            is_lonab         = prediction.get("is_lonab", False),
            predicted_winner = pred_win,
            official_winner  = off_win,
            top1_correct     = top1_ok,
            top3_predicted   = pred_top3,
            top3_official    = off_top3,
            top3_score       = top3_score,
            top5_predicted   = pred_top5[:5],
            top5_official    = off_top5[:5],
            top5_score       = top5_score
        )


auto_evaluator = AutoEvaluator()
