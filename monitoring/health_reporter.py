"""
HYPERION V9 — Health Reporter (Agent I - Output)
Construit le rapport de santé pipeline pour Telegram.
"""
from utils.helpers import escape_markdown_v2
from utils.logger  import get_logger

logger = get_logger(__name__)


class HealthReporter:

    def build_message(self, summary: dict, mode: str = "morning") -> str:
        lines = []
        icon  = "🔧" if mode == "morning" else "📋"
        label = "Pipeline Matin" if mode == "morning" else "Évaluation Soir"

        lines.append(f"{icon} *HYPERION — {label}*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")

        lines.append("📌 *Sources*")
        lines.append(self._section(summary["steps"], [
            "LONAB", "PMU_PROGRAMME", "PMU_RUNNERS",
            "SCRAPING_Paris-Turf", "SCRAPING_Equidia", "SCRAPING_Zone-Turf"
        ]))

        lines.append("")
        lines.append("📊 *Pipeline*")
        lines.append(self._section(summary["steps"], [
            "D1", "D2", "D3_MONTE", "D4_BORDA",
            "E2_FUSION", "F1_HADES", "F2_EV",
            "REPORT", "TELEGRAM"
        ]))

        if mode == "evening":
            lines.append("")
            lines.append("✅ *Résultats*")
            lines.append(self._section(summary["steps"], [
                "RESULTS_FETCH", "EVALUATION", "FIREBASE"
            ]))

        lines.append("")
        k1 = summary.get("gemini_key1", 0)
        k2 = summary.get("gemini_key2", 0)
        lines.append(f"🔑 *Gemini* : Clé1 {k1}/24 \\| Clé2 {k2}/24 \\| Total {k1+k2}/48")

        d = summary.get("duration_s", 0)
        lines.append(f"⏱ Durée : {int(d//60)}min {int(d%60)}s")

        fails = summary.get("failures", 0)
        warns = summary.get("warnings", 0)
        if fails == 0 and warns == 0:
            lines.append("✅ Pipeline OK")
        elif fails == 0:
            lines.append(f"⚠️ {warns} avertissement\\(s\\)")
        else:
            lines.append(f"❌ {fails} erreur\\(s\\) \\| {warns} warning\\(s\\)")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _section(self, steps: list, keys: list) -> str:
        lines = []
        for key in keys:
            matches = [s for s in steps if key.upper() in s["name"].upper()]
            if not matches:
                continue
            last  = matches[-1]
            emoji = {"OK": "✅", "WARNING": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}.get(last["status"], "⚪")
            name  = key.replace("_", " ")
            msg   = f" \\({escape_markdown_v2(last['msg'][:40])}\\)" if last["msg"] else ""
            lines.append(f"  {emoji} {name}{msg}")
        return "\n".join(lines) if lines else "  ⚪ Aucun log"


health_reporter = HealthReporter()
