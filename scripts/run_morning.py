import os
import logging
import yaml
from datetime import datetime
from data.lonab_adapter import LonabAdapter
from data.pmu_adapter import PmuAdapter
from analytics.d1_normalizer import Normalizer
from analytics.d2_scorer import Scorer
from analytics.d3_monte_carlo import MonteCarloEngine
from analytics.d4_consensus import BordaConsensus
from analytics.e2_meta_fusion import MetaFusionEngine
from output.report_generator import ReportGenerator
from output.telegram_bot import TelegramBot
from utils.quota_manager import GeminiKeyRotator

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HYPERION_MORNING")

def run():
    date_str = datetime.now().strftime("%Y%m%d")
    logger.info(f"--- DÉBUT PIPELINE MATIN {date_str} ---")

    # 1. Initialisation
    rotator = GeminiKeyRotator()
    bot = TelegramBot()
    mc_engine = MonteCarloEngine()
    
    # Charger les poids de scoring
    try:
        with open("config/scoring.yaml", "r") as f:
            scoring_config = yaml.safe_load(f)
            weights = scoring_config['weights']
    except Exception:
        weights = {'score_historique': 0.35, 'score_forme': 0.25, 'score_terrain': 0.20, 'score_handicap': 0.10, 'score_fraicheur': 0.10}

    # 2. Collecte des courses
    lonab_course = LonabAdapter.identify_lonab_course(date_str)
    pmu_program = PmuAdapter.get_daily_program(date_str)
    
    # Sélection des 10 courses
    selected_courses = []
    if lonab_course: selected_courses.append(lonab_course)
    for c in pmu_program:
        if len(selected_courses) >= 10: break
        if lonab_course and c.course_id == lonab_course.course_id: continue
        selected_courses.append(c)

    # 3. Analyse
    all_predictions = []
    for course in selected_courses:
        logger.info(f"Analyse de la course {course.course_id}...")
        
        # D1 & D2
        normalized = Normalizer.process(course)
        scored = Scorer.process(normalized, weights)
        
        # D3 Monte Carlo (5 variantes)
        variantes = []
        for seed in [42, 43, 44, 45, 46]:
            res = mc_engine.run_simulation(scored, seed)
            variantes.append(res)
            
        # D4 Consensus Borda
        internal_consensus = BordaConsensus.compute(variantes, course.course_id)
        
        # E2 Méta-fusion (Simulation de consensus externe)
        prediction = MetaFusionEngine.fuse(internal_consensus, None)
        all_predictions.append(prediction)

    # 4. Reporting & Envoi
    report_gen = ReportGenerator(rotator)
    narrative_report = report_gen.generate_batch_report(all_predictions)
    
    bot.send_message(narrative_report)
    logger.info("--- PIPELINE MATIN TERMINÉ ---")

if __name__ == "__main__":
    run()
