"""
HYPERION V9 — Static Template
Génère un rapport Telegram structuré SANS Gemini.
Activé automatiquement si quota épuisé ou Gemini KO.
"""
from typing import List, Optional
from domain.schemas import (
    CourseReport, TopPrediction, HadesReport,
    HadesNiveau, EVKellyResult, RiskAssessment
)
from utils.helpers import escape_markdown_v2, stars_from_confidence, format_fcfa
from utils.logger  import get_logger

logger = get_logger(__name__)

DISCLAIMER = (
    "_⚠️ HYPERION est un outil d'analyse statistique\\. "
    "Aucune garantie de gain\\. "
    "Jouer comporte des risques\\._"
)


class StaticTemplate:
    """
    Construit les messages Telegram depuis des templates statiques.
    Qualité moindre que Gemini mais 100% fonctionnel.
    """

    def build_morning_report(self, report: CourseReport) -> str:
        """Construit le rapport du matin pour une course."""
        lines = []

        # En-tête
        is_lonab = report.is_lonab
        badge    = "⭐ *COURSE LONAB DU JOUR*\n" if is_lonab else ""
        hippodrome = escape_markdown_v2(report.hippodrome or "?")
        nom_course = escape_markdown_v2(
            report.top5.predictions[0].course_id if report.top5 else report.course_id
        )

        lines.append(f"🏇 *HYPERION V9* — Pronostics")
        lines.append(f"{badge}📍 *{hippodrome}*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")

        # Top 5
        if report.top5 and report.top5.predictions:
            for pred in report.top5.predictions[:5]:
                nom  = escape_markdown_v2(pred.nom or f"#{pred.numero}")
                line = f"{pred.position}️⃣ *{pred.numero} \\- {nom}*"

                # Score de confiance
                line += f"\n   {pred.stars}"

                # Signal externe
                if pred.signal_externe and "interne" not in pred.signal_externe:
                    line += f" \\| {escape_markdown_v2(pred.signal_externe)}"

                lines.append(line)
        else:
            lines.append("_Prédictions non disponibles_")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")

        # EV/Kelly — meilleur value bet
        if report.ev_kelly:
            vb = next((r for r in report.ev_kelly if r.is_value_bet), None)
            if vb:
                mise_str = format_fcfa(vb.mise_recommandee)
                lines.append(
                    f"💰 *Value bet :* #{vb.cheval_numero} "
                    f"\\| EV\\=\\+{vb.ev*100:.1f}% "
                    f"\\| Kelly\\: {escape_markdown_v2(mise_str)}"
                )

        # HADES
        if report.hades:
            hades_line = self._build_hades_line(report.hades)
            if hades_line:
                lines.append(hades_line)

        # Confiance globale
        if report.confiance:
            stars = stars_from_confidence(report.confiance)
            lines.append(f"📊 *Confiance globale :* {stars} \\({report.confiance*100:.0f}%\\)")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(DISCLAIMER)

        return "\n".join(lines)

    def build_batch_report(self, reports: List[CourseReport]) -> str:
        """
        Construit le rapport du matin pour toutes les courses.
        1 message consolidé.
        """
        from utils.helpers import today_str
        lines = []
        lines.append(f"🏇 *HYPERION V9* — {escape_markdown_v2(today_str())}")
        lines.append(f"📊 {len(reports)} courses analysées")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")

        for i, report in enumerate(reports):
            lines.append(self._build_course_block(report, i + 1))
            if i < len(reports) - 1:
                lines.append("")  # séparateur entre courses

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(DISCLAIMER)

        full_text = "\n".join(lines)

        # Tronquer si trop long pour Telegram (4096 chars)
        from utils.helpers import truncate_message
        return truncate_message(full_text, 4096)

    def _build_course_block(self, report: CourseReport, index: int) -> str:
        """Bloc compact pour une course dans le rapport batch."""
        lines = []

        badge      = "⭐ " if report.is_lonab else f"{index}\\. "
        hippodrome = escape_markdown_v2(report.hippodrome or "?")
        lines.append(f"{badge}*{hippodrome}*")

        if report.top5 and report.top5.predictions:
            top3 = report.top5.predictions[:3]
            nums = " \\- ".join(
                f"*{p.numero}*" for p in top3
            )
            stars = top3[0].stars if top3 else "⭐"
            lines.append(f"   {nums} \\| {stars}")

            # Value bet si présent
            if report.ev_kelly:
                vb = next((r for r in report.ev_kelly if r.is_value_bet), None)
                if vb:
                    lines.append(
                        f"   💰 \\#{vb.cheval_numero} EV\\=\\+{vb.ev*100:.1f}%"
                    )

            # HADES si alerte
            if report.hades and report.hades.niveau_global != HadesNiveau.GREEN:
                niveau = report.hades.niveau_global.value
                lines.append(f"   {self._hades_emoji(report.hades.niveau_global)} HADES: {niveau}")
        else:
            lines.append("   _Données insuffisantes_")

        return "\n".join(lines)

    def _build_hades_line(self, hades: HadesReport) -> Optional[str]:
        """Construit la ligne HADES pour le rapport."""
        emoji = self._hades_emoji(hades.niveau_global)
        if hades.niveau_global == HadesNiveau.GREEN:
            return f"{emoji} HADES: Aucune anomalie"
        elif hades.niveau_global == HadesNiveau.YELLOW:
            suspects = ", ".join(f"\\#{n}" for n in hades.chevaux_suspects)
            return f"{emoji} HADES: Vigilance sur {suspects}"
        else:
            return f"{emoji} *HADES ALERTE ROUGE* — Mises en observation"

    def _hades_emoji(self, niveau: HadesNiveau) -> str:
        return {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(niveau.value, "⚪")


# Instance globale
static_template = StaticTemplate()
