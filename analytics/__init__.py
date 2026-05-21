"""
HYPERION V9 — Package Analytics
Expose la fonction run_full_analytics() qui orchestre D1→E3.
"""
from typing import List, Tuple

from analytics.d1_normalizer  import d1_normalizer
from analytics.d2_scorer      import d2_scorer
from analytics.d3_monte_carlo import mc_engine, SEEDS_DEFAULT
from analytics.d4_consensus   import borda_consensus
from analytics.e1_ext_consensus import e1_ext_consensus
from analytics.e2_meta_fusion import e2_meta_fusion
from analytics.e3_tiebreak    import e3_tiebreak

from domain.schemas import (
    Course, ExternalData, ExternalConsensus,
    TopPrediction, InternalConsensus
)
from utils.logger import get_logger

logger = get_logger(__name__)


def run_full_analytics(
    course: Course,
    external_data: ExternalData,
    external_consensus: ExternalConsensus
) -> Tuple[TopPrediction, InternalConsensus]:
    """
    Pipeline analytique complet D1 → E3 pour une course.

    Returns:
        (top_prediction, internal_consensus)
    """
    course_id = course.course_id
    logger.info(f"[ANALYTICS] Démarrage pipeline pour {course_id}")

    # D1 — Filtrage & Normalisation
    runners, d1_logs = d1_normalizer.process(course)
    for log in d1_logs:
        logger.info(log)

    if not runners:
        raise ValueError(f"[{course_id}] D1: aucun partant valide")

    # D2 — Scoring Multicritères
    scored_runners = d2_scorer.score_all(
        runners,
        course_distance = course.distance,
        course_type     = course.type_course
    )

    # D3 — Monte Carlo (5 variantes)
    all_variants = mc_engine.run_all_variants(scored_runners, SEEDS_DEFAULT)

    if not all_variants:
        raise ValueError(f"[{course_id}] D3: Monte Carlo a échoué")

    # Aplatir pour E2 (prendre win_prob moyens sur toutes variantes)
    mc_averaged = _average_mc_results(all_variants)

    # D4 — Consensus Borda Interne
    internal_consensus = borda_consensus.compute(
        all_variants, course_id, SEEDS_DEFAULT
    )

    # E1 — Consensus Externe (déjà calculé dans fusion_engine, on le ré-affine)
    refined_external = e1_ext_consensus.compute(
        course_id,
        external_data,
        sources_config=None
    )
    # Utiliser le consensus passé en paramètre s'il est meilleur
    if (external_consensus.nb_sources if hasattr(external_consensus, 'nb_sources')
            else len(external_consensus.sources_pronostics)) >= \
       len(refined_external.sources_pronostics):
        final_external = external_consensus
    else:
        final_external = refined_external

    # E2 — Méta-Fusion (classement interne + confiance externe)
    top_prediction = e2_meta_fusion.fuse(
        internal_consensus,
        final_external,
        mc_averaged,
        course_date = course.date
    )

    # E3 — Tie-Break Pairwise (si nécessaire)
    top_prediction = e3_tiebreak.apply(top_prediction, all_variants)

    logger.info(
        f"[ANALYTICS] {course_id} terminé ✅ | "
        f"Top1=#{top_prediction.predictions[0].numero if top_prediction.predictions else '?'} "
        f"({top_prediction.predictions[0].stars if top_prediction.predictions else ''})"
    )

    return top_prediction, internal_consensus


def _average_mc_results(all_variants):
    """Calcule la moyenne des win_prob sur toutes les variantes."""
    from domain.schemas import MonteCarloResult
    from collections import defaultdict

    sums   = defaultdict(lambda: {"win": 0, "place": 0, "top3": 0, "rank": 0, "count": 0})
    names  = {}

    for variante in all_variants:
        for mc in variante:
            sums[mc.numero]["win"]   += mc.win_prob
            sums[mc.numero]["place"] += mc.place_prob
            sums[mc.numero]["top3"]  += mc.top3_prob
            sums[mc.numero]["rank"]  += mc.expected_rank or 0
            sums[mc.numero]["count"] += 1
            if mc.cheval_nom:
                names[mc.numero] = mc.cheval_nom

    averaged = []
    for numero, data in sums.items():
        n = data["count"]
        averaged.append(MonteCarloResult(
            numero       = numero,
            cheval_nom   = names.get(numero),
            win_prob     = round(data["win"]   / n, 4),
            place_prob   = round(data["place"] / n, 4),
            top3_prob    = round(data["top3"]  / n, 4),
            expected_rank= round(data["rank"]  / n, 2) if data["rank"] > 0 else None,
            simulations  = mc_engine.simulations * len(all_variants),
        ))

    return averaged
