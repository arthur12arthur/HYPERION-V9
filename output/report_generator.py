"""
HYPERION V9 — Report Generator (Agent G)
Génère les rapports narratifs Telegram via Gemini.
1 seul appel batch pour toutes les courses.
Fallback automatique sur template statique si Gemini KO.
"""
import json
from typing import List, Optional
from domain.schemas import CourseReport, TelegramMessage
from output.static_template import static_template
from utils.quota_manager import quota_manager, AllKeysExhaustedError
from utils.helpers import safe_json_loads, truncate_message, today_str
from utils.config  import config
from utils.logger  import get_logger

logger = get_logger(__name__)

CHAT_ID = None  # injecté au démarrage depuis les secrets


class ReportGenerator:
    """
    Agent G — Génère les rapports Telegram pour toutes les courses.
    Stratégie : 1 appel Gemini batch → fallback template si KO.
    """

    def __init__(self):
        self.prompt_template = config.load_prompt("reporting_batch")

    def generate_all(
        self,
        reports: List[CourseReport],
        chat_id: str = None
    ) -> List[TelegramMessage]:
        """
        Génère les messages Telegram pour toutes les courses.
        1 appel Gemini pour toutes, ou template statique si KO.

        Returns:
            Liste de TelegramMessage prêts à envoyer
        """
        if not reports:
            return []

        # Tentative Gemini batch
        if quota_manager.can_use(1):
            messages = self._generate_with_gemini(reports, chat_id)
            if messages:
                logger.info(
                    f"[REPORT] {len(messages)} rapports générés via Gemini "
                    f"({quota_manager.keys[quota_manager.current]['id']})"
                )
                return messages

        # Fallback template statique
        logger.warning("[REPORT] Fallback template statique activé")
        return self._generate_with_template(reports, chat_id)

    def _generate_with_gemini(
        self,
        reports: List[CourseReport],
        chat_id: str = None
    ) -> List[TelegramMessage]:
        """Génère tous les rapports en 1 appel Gemini batch."""
        try:
            # Préparer le payload pour Gemini
            courses_payload = self._build_gemini_payload(reports)
            prompt          = f"{self.prompt_template}\n\n{json.dumps(courses_payload, ensure_ascii=False)}"

            system = (
                "Tu es l'Agent Reporting HYPERION V9. "
                "Retourne UNIQUEMENT un tableau JSON de rapports Telegram. "
                "Pas de texte avant ou après le JSON."
            )

            response_text = quota_manager.call_gemini(prompt, system=system)

            # Parser la réponse JSON
            parsed = safe_json_loads(response_text)
            if not parsed or not isinstance(parsed, list):
                logger.warning("[REPORT] Réponse Gemini non parsable")
                return []

            # Construire les TelegramMessage
            messages    = []
            reports_map = {r.course_id: r for r in reports}

            for item in parsed:
                if not isinstance(item, dict):
                    continue

                course_id = item.get("course_id", "")
                text      = item.get("telegram_text", "")

                if not text:
                    continue

                report = reports_map.get(course_id)
                cid    = chat_id or CHAT_ID or ""

                messages.append(TelegramMessage(
                    chat_id             = cid,
                    parse_mode          = "MarkdownV2",
                    disable_notification= False,
                    text                = truncate_message(text, 4096)
                ))

            return messages if messages else []

        except AllKeysExhaustedError:
            logger.warning("[REPORT] Toutes les clés Gemini KO")
            return []
        except Exception as e:
            logger.error(f"[REPORT] Erreur Gemini: {e}")
            return []

    def _build_gemini_payload(self, reports: List[CourseReport]) -> List[dict]:
        """Construit le payload JSON à envoyer à Gemini."""
        payload = []

        for report in reports:
            top5_data = []
            if report.top5:
                for pred in report.top5.predictions[:5]:
                    top5_data.append({
                        "position"       : pred.position,
                        "numero"         : pred.numero,
                        "nom"            : pred.nom or f"#{pred.numero}",
                        "stars"          : pred.stars,
                        "meta_score_pct" : round(pred.meta_score * 100, 1),
                        "signal_externe" : pred.signal_externe,
                        "raisons"        : pred.raisons[:2]  # max 2 raisons
                    })

            ev_data = []
            for ev in report.ev_kelly[:3]:  # top 3 EV
                if ev.is_value_bet:
                    ev_data.append({
                        "numero"  : ev.cheval_numero,
                        "ev_pct"  : round(ev.ev * 100, 1),
                        "mise_fcfa": int(ev.mise_recommandee),
                        "risque"  : ev.niveau_risque.value
                    })

            hades_data = None
            if report.hades and report.hades.niveau_global.value != "GREEN":
                hades_data = {
                    "niveau"   : report.hades.niveau_global.value,
                    "suspects" : report.hades.chevaux_suspects,
                    "message"  : report.hades.recommendations
                }

            payload.append({
                "course_id"  : report.course_id,
                "hippodrome" : report.hippodrome or "?",
                "distance"   : report.distance,
                "is_lonab"   : report.is_lonab,
                "confiance"  : round(report.confiance * 100, 0),
                "top5"       : top5_data,
                "value_bets" : ev_data,
                "hades"      : hades_data
            })

        return payload

    def _generate_with_template(
        self,
        reports: List[CourseReport],
        chat_id: str = None
    ) -> List[TelegramMessage]:
        """Génère les rapports via template statique — zéro Gemini."""
        messages = []
        cid = chat_id or CHAT_ID or ""

        # Un seul message consolidé pour toutes les courses
        batch_text = static_template.build_batch_report(reports)
        messages.append(TelegramMessage(
            chat_id             = cid,
            parse_mode          = "MarkdownV2",
            disable_notification= False,
            text                = batch_text
        ))

        return messages


# Instance globale
report_generator = ReportGenerator()
