"""
HYPERION V9 — Evaluation Report (Agent H - Output)
Génère le rapport d'évaluation du soir sur Telegram.
Compare prédictions du matin vs résultats officiels.
"""
import json
from typing import Dict, List, Optional
from domain.schemas import (
    EvaluationDailyReport, CourseEvaluation,
    TelegramMessage
)
from utils.quota_manager import quota_manager, AllKeysExhaustedError
from utils.helpers import escape_markdown_v2, today_str, truncate_message
from utils.config  import config
from utils.logger  import get_logger

logger = get_logger(__name__)

DISCLAIMER = "_⚠️ Outil statistique\\. Aucune garantie de gain\\._"


class EvaluationReportBuilder:
    """
    Construit le rapport d'évaluation du soir.
    Tente Gemini pour la narration, fallback template sinon.
    """

    def __init__(self):
        self.prompt_template = config.load_prompt("evaluation")

    def build_and_send(
        self,
        eval_report: EvaluationDailyReport,
        predictions: Dict[str, dict],
        results: Dict[str, dict],
        chat_id: str = None
    ) -> TelegramMessage:
        """
        Calcule les scores + génère le message Telegram du soir.

        Args:
            eval_report  : rapport d'évaluation calculé
            predictions  : {course_id: {"predicted_top5": [...], ...}}
            results      : {course_id: {"winner": N, "top3": [...], ...}}
            chat_id      : ID du canal Telegram
        """
        # Tentative Gemini pour la narration
        narrative = None
        if quota_manager.can_use(1):
            narrative = self._generate_narrative(eval_report)

        # Construire le message
        text = self._build_telegram_text(eval_report, narrative)

        from output.telegram_bot import telegram_bot
        cid = chat_id or telegram_bot.chat_id

        return TelegramMessage(
            chat_id    = cid,
            parse_mode = "MarkdownV2",
            text       = truncate_message(text, 4096)
        )

    def _generate_narrative(self, eval_report: EvaluationDailyReport) -> Optional[str]:
        """Génère la narration analytique via Gemini (1 appel)."""
        try:
            payload = {
                "jour"              : eval_report.day_number,
                "date"              : eval_report.date,
                "score_top1_pct"    : eval_report.score_jour_top1,
                "score_top3_pct"    : eval_report.score_jour_top3,
                "running_top1"      : eval_report.running_top1_all_days,
                "running_top3"      : eval_report.running_top3_all_days,
                "lonab_correct"     : eval_report.lonab_precision,
                "nb_courses"        : len(eval_report.courses),
                "courses_detail"    : [
                    {
                        "course_id"     : c.course_id,
                        "is_lonab"      : c.is_lonab,
                        "top1_correct"  : c.top1_correct,
                        "top3_score"    : c.top3_score
                    }
                    for c in eval_report.courses
                ]
            }

            prompt = (
                f"{self.prompt_template}\n\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            )

            system = (
                "Tu es l'Agent Auto-Évaluation HYPERION V9. "
                "Génère un rapport d'évaluation Telegram honnête et concis. "
                "Retourne UNIQUEMENT le texte formaté MarkdownV2, sans JSON."
            )

            narrative = quota_manager.call_gemini(prompt, system=system)
            logger.info("[EVAL] Narration générée via Gemini")
            return narrative.strip() if narrative else None

        except AllKeysExhaustedError:
            logger.warning("[EVAL] Quota Gemini épuisé — template statique")
            return None
        except Exception as e:
            logger.error(f"[EVAL] Erreur Gemini narration: {e}")
            return None

    def _build_telegram_text(
        self,
        report: EvaluationDailyReport,
        narrative: Optional[str]
    ) -> str:
        """Construit le message Telegram d'évaluation."""

        # Si Gemini a généré la narration complète, l'utiliser directement
        if narrative and len(narrative) > 100:
            return truncate_message(narrative, 4096)

        # Sinon : template statique
        lines = []
        day   = report.day_number
        date_ = escape_markdown_v2(report.date)

        lines.append(f"📊 *ÉVALUATION J{day}/30* — {date_}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("✅ *RÉSULTATS OFFICIELS*")
        lines.append("")

        # Course LONAB en premier
        lonab_courses = [c for c in report.courses if c.is_lonab]
        other_courses = [c for c in report.courses if not c.is_lonab]

        for course in lonab_courses:
            lines.append(self._format_course_result(course, is_lonab=True))

        if other_courses:
            correct_count  = sum(1 for c in other_courses if c.top1_correct)
            top3_total     = sum(c.top3_score for c in other_courses)
            top3_max       = len(other_courses) * 3
            lines.append(
                f"📌 *Autres courses \\({len(other_courses)}\\)* : "
                f"Top1 {correct_count}/{len(other_courses)} \\| "
                f"Top3 {top3_total}/{top3_max}"
            )

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")

        # Score du jour
        top1_pct = round(report.score_jour_top1, 1)
        top3_pct = round(report.score_jour_top3, 1)
        correct_today = sum(1 for c in report.courses if c.top1_correct)
        total_today   = len(report.courses)

        lines.append("📈 *SCORE DU JOUR*")
        lines.append(
            f"  Top1 : {correct_today}/{total_today} "
            f"\\({escape_markdown_v2(str(top1_pct))}%\\)"
        )
        lines.append(
            f"  Top3 : \\({escape_markdown_v2(str(top3_pct))}%\\)"
        )

        lines.append("")

        # Score cumulé
        run_top1 = round(report.running_top1_all_days, 1)
        run_top3 = round(report.running_top3_all_days, 1)
        tendance = "📈" if run_top1 >= 30 else "📉"

        lines.append(f"🎯 *SCORE CUMULÉ J{day}/30*")
        lines.append(
            f"  Top1 global : "
            f"{escape_markdown_v2(str(run_top1))}%"
        )
        lines.append(
            f"  Top3 global : "
            f"{escape_markdown_v2(str(run_top3))}%"
        )
        lines.append(f"  Tendance : {tendance}")

        if report.lonab_precision is not None:
            lonab_pct = round(report.lonab_precision * 100, 1)
            lines.append(
                f"  LONAB précision : "
                f"{escape_markdown_v2(str(lonab_pct))}%"
            )

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(DISCLAIMER)

        return "\n".join(lines)

    def _format_course_result(self, course: CourseEvaluation, is_lonab: bool) -> str:
        """Formate le résultat d'une course."""
        badge = "⭐ *Course LONAB* " if is_lonab else f"  Course {course.course_id} "

        predicted = course.predicted_winner or "?"
        official  = course.official_winner  or "?"

        if course.top1_correct:
            result_line = f"{badge}: Prédit \\#{predicted} → ✅ CORRECT"
        else:
            result_line = (
                f"{badge}: Prédit \\#{predicted} → "
                f"❌ Réel: \\#{official}"
            )

        top3_line = (
            f"  Top3 : {course.top3_score}/3 corrects"
            if course.top3_score is not None else ""
        )

        return f"{result_line}\n{top3_line}" if top3_line else result_line


# Instance globale
evaluation_report_builder = EvaluationReportBuilder()
