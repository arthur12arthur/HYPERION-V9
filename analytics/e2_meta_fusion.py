"""
HYPERION V9 — E2 Méta-Fusion (Système définitif V9.3+)

PRINCIPE FONDAMENTAL :
  Le CLASSEMENT = consensus interne (Monte Carlo + Borda) UNIQUEMENT.
  L'externe MODIFIE UNIQUEMENT le score de confiance (étoiles Telegram).
  L'externe ne peut JAMAIS changer l'ordre des chevaux.
"""
from typing import List, Optional
from domain.schemas import (
    InternalConsensus, ExternalConsensus, MonteCarloResult,
    MetaPrediction, TopPrediction, ExternalQualite
)
from utils.logger  import get_logger
from utils.helpers import stars_from_confidence, today_str

logger = get_logger(__name__)

# Modificateurs de confiance selon divergence externe
BOOST_CONFIRMED     = +0.10   # externe confirme ou plus optimiste
PENALTY_WEAK_DIV    = -0.05   # légère divergence (rang diff ≤ 2)
PENALTY_STRONG_DIV  = -0.10   # forte divergence (rang diff > 2)


class E2MetaFusion:
    """
    Étape E2 : fusionne le consensus interne et externe.
    Le classement final est IMMUABLE (interne seulement).
    L'externe agit uniquement comme modificateur de confiance.
    """

    def fuse(
        self,
        internal: InternalConsensus,
        external: ExternalConsensus,
        mc_results: List[MonteCarloResult],
        course_date: str = None
    ) -> TopPrediction:
        """
        Produit le TopPrediction final.

        Args:
            internal    : classement Borda interne (IMMUABLE)
            external    : consensus externe (modifie confiance uniquement)
            mc_results  : résultats Monte Carlo pour win_prob par cheval
            course_date : date de la course
        """
        if course_date is None:
            course_date = today_str()

        # Index Monte Carlo par numéro
        mc_index = {r.numero: r for r in mc_results}

        classement_final = internal.consensus_borda
        predictions      = []

        for position, numero in enumerate(classement_final[:5], 1):
            mc = mc_index.get(numero)

            if mc:
                confiance_base = mc.win_prob
                cheval_nom     = mc.cheval_nom or f"#{numero}"
            else:
                # Fallback : score interne normalisé
                confiance_base = max(0.1, (5 - position) / 10)
                cheval_nom     = f"#{numero}"

            # ── Modification de confiance par l'externe ──────────
            confiance_finale, signal = self._apply_external_modifier(
                numero, position, confiance_base, external
            )

            # ── Étoiles Telegram ─────────────────────────────────
            stars = stars_from_confidence(confiance_finale)

            # ── Raisons ──────────────────────────────────────────
            raisons = self._build_raisons(numero, position, mc, internal, external)

            predictions.append(MetaPrediction(
                course_id      = internal.course_id,
                position       = position,
                numero         = numero,
                nom            = cheval_nom,
                meta_score     = round(confiance_finale, 4),
                score_mc       = round(confiance_base, 4),
                score_externe  = external.external_scores.get(str(numero)),
                signal_externe = signal,
                robuste        = internal.robuste,
                stars          = stars,
                raisons        = raisons
            ))

        # Confiance globale = moyenne des 3 premiers
        confidence_global = (
            sum(p.meta_score for p in predictions[:3]) / min(3, len(predictions))
            if predictions else 0.0
        )

        # Classement legacy pour compatibilité
        classement_legacy = [p.numero for p in predictions]

        logger.info(
            f"[E2] {internal.course_id}: "
            f"#1={predictions[0].numero if predictions else '?'} "
            f"({predictions[0].stars if predictions else ''})"
            f" | confiance_global={confidence_global:.3f}"
        )

        return TopPrediction(
            course_id         = internal.course_id,
            date              = course_date,
            confidence_global = round(confidence_global, 3),
            predictions       = predictions,
            classement_final  = classement_legacy,
            confiance_etoiles = predictions[0].stars if predictions else "⭐",
            signal            = predictions[0].signal_externe if predictions else ""
        )

    def _apply_external_modifier(
        self,
        numero: int,
        position_interne: int,
        confiance_base: float,
        external: ExternalConsensus
    ):
        """
        Calcule la confiance finale et le signal selon le consensus externe.
        Le classement n'est PAS modifié.
        """
        # Pas de données externes → confiance inchangée
        if external.qualite == ExternalQualite.INDISPONIBLE or not external.top5_external:
            return confiance_base, "🔵 Analyse interne seule"

        rang_externe = external.get_rank(numero)  # 999 si absent du top5 externe
        diff         = rang_externe - position_interne  # positif = externe moins optimiste

        if rang_externe == 999:
            # Cheval absent du top5 externe → légère pénalité
            confiance_finale = max(0.05, confiance_base + PENALTY_WEAK_DIV)
            signal           = "⚠️ Absent du top5 externe"

        elif diff <= 0:
            # Externe confirme ou est encore plus optimiste → boost
            boost            = min(BOOST_CONFIRMED, abs(diff) * 0.03 + 0.05)
            confiance_finale = min(1.0, confiance_base + boost)
            signal           = "✅ Confirmé externe"

        elif diff <= 2:
            # Légère divergence → petite pénalité
            confiance_finale = max(0.05, confiance_base + PENALTY_WEAK_DIV)
            signal           = "🟡 Légère divergence externe"

        else:
            # Forte divergence → pénalité plus marquée
            confiance_finale = max(0.05, confiance_base + PENALTY_STRONG_DIV)
            signal           = f"⚠️ Divergence forte \\(externe rang {rang_externe}\\)"

        return round(confiance_finale, 4), signal

    def _build_raisons(
        self,
        numero: int,
        position: int,
        mc: Optional[MonteCarloResult],
        internal: InternalConsensus,
        external: ExternalConsensus
    ) -> List[str]:
        """Construit la liste de raisons pour le rapport."""
        raisons = []

        # Raison Borda
        score_borda = internal.scores_borda_full.get(str(numero), 0)
        raisons.append(f"Score Borda interne : {score_borda} pts (rang {position})")

        # Raison Monte Carlo
        if mc:
            raisons.append(
                f"Monte Carlo : win={mc.win_prob*100:.1f}% | "
                f"top3={mc.top3_prob*100:.1f}%"
            )
            if internal.robuste:
                raisons.append("Classement robuste (>80% variantes concordantes)")

        # Raison externe
        if external.qualite != ExternalQualite.INDISPONIBLE:
            rang_ext = external.get_rank(numero)
            if rang_ext <= 3:
                raisons.append(
                    f"Support externe fort : rang {rang_ext} "
                    f"({', '.join(external.sources_pronostics)})"
                )
            elif rang_ext <= 5:
                raisons.append(f"Mentionné top5 externe (rang {rang_ext})")

        return raisons


# Instance globale
e2_meta_fusion = E2MetaFusion()
