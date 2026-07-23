"""
HYPERION V9 — Schémas Pydantic complets
S001 → S033 : tous les contrats de données du système
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


# ─────────────────────────────────────────────
# ENUMERATIONS
# ─────────────────────────────────────────────

class PipelineState(str, Enum):
    CREATED = "CREATED"
    LONAB_IDENTIFIED = "LONAB_IDENTIFIED"
    COURSES_SELECTED = "COURSES_SELECTED"
    EXTRACTED = "EXTRACTED"
    ENRICHED = "ENRICHED"
    SCORED = "SCORED"
    SIMULATED = "SIMULATED"
    FUSED = "FUSED"
    RISK_ANALYZED = "RISK_ANALYZED"
    REPORTED = "REPORTED"
    DELIVERED = "DELIVERED"
    RESULTS_FETCHED = "RESULTS_FETCHED"
    EVALUATED = "EVALUATED"
    ARCHIVED = "ARCHIVED"
    FAILED_PARTIAL = "FAILED_PARTIAL"
    FAILED_FATAL = "FAILED_FATAL"


class HadesNiveau(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class ExternalQualite(str, Enum):
    HAUTE = "HAUTE"
    MOYENNE = "MOYENNE"
    FAIBLE = "FAIBLE"
    INDISPONIBLE = "INDISPONIBLE"


class RiskLevel(str, Enum):
    FAIBLE = "FAIBLE"
    MODERE = "MODERE"
    ELEVE = "ELEVE"
    BLOQUE = "BLOQUE"


# ─────────────────────────────────────────────
# S001 — ProgramDocument
# ─────────────────────────────────────────────
class ProgramDocument(BaseModel):
    """Document racine retourné par l'extraction LONAB/PMU."""
    date: str                          # "2025-01-15"
    source: str                        # "LONAB_PDF_OFFICIEL" | "PMU_SCRAPING"
    hippodrome: Optional[str] = None
    nb_courses: int
    courses: List["Course"]            # forward ref


# ─────────────────────────────────────────────
# S002 — Course
# ─────────────────────────────────────────────
class Course(BaseModel):
    """Une course individuelle avec ses paramètres."""
    course_id: str                     # "R1C1"
    nom: str
    date: str
    heure: Optional[str] = None
    hippodrome: Optional[str] = None
    type_course: Optional[str] = None  # "Attelé" | "Monté" | "Plat" | "Obstacle"
    distance: Optional[int] = None     # en mètres
    conditions: Optional[str] = None
    nb_partants: Optional[int] = None
    source: Optional[str] = None
    is_lonab: bool = False
    is_lonab_replacement: bool = False
    partants: List["Runner"] = []


# ─────────────────────────────────────────────
# S003 — Runner (Partant)
# ─────────────────────────────────────────────
class Runner(BaseModel):
    """Un cheval inscrit dans une course."""
    numero: int
    nom: str
    age: Optional[int] = None
    sexe: Optional[str] = None         # "M" | "F" | "H" (hongre)
    poids: float = 58.0
    corde: Optional[int] = None        # position au départ
    forme_brute: Optional[str] = None  # "1a 2a 1a 3a"
    forme_parsed: List[int] = []       # [1, 2, 1, 3]
    gains_totaux: Optional[float] = None
    jockey: Optional[str] = None
    entraineur: Optional[str] = None
    proprietaire: Optional[str] = None
    cote_officielle: float = 0.0
    date_dernier_depart: Optional[str] = None
    source: Optional[str] = None
    is_non_partant: bool = False

    @field_validator("cote_officielle")
    @classmethod
    def cote_must_be_positive(cls, v):
        if v < 0:
            raise ValueError("cote_officielle doit être >= 0")
        return v


# ─────────────────────────────────────────────
# S004 — ScoredRunner
# ─────────────────────────────────────────────
class ScoredRunner(Runner):
    """Runner enrichi avec les métriques de scoring."""
    score_historique: float = 0.0
    score_forme: float = 0.0
    score_terrain: float = 0.0
    score_handicap: float = 0.0
    score_fraicheur: float = 0.0
    score_global: float = 0.0
    rang_theorique: Optional[int] = None


# ─────────────────────────────────────────────
# S005 — MonteCarloResult
# ─────────────────────────────────────────────
class MonteCarloResult(BaseModel):
    """Résultat statistique après N simulations."""
    numero: int
    cheval_nom: Optional[str] = None
    win_prob: float                    # probabilité de victoire
    place_prob: float                  # probabilité top 2
    top3_prob: float                   # probabilité top 3
    expected_rank: Optional[float] = None  # rang moyen
    confiance_mc: Optional[float] = None  # fiabilité simulation
    simulations: int = 10000
    seed: Optional[int] = None


# ─────────────────────────────────────────────
# S006 — InternalConsensus
# ─────────────────────────────────────────────
class InternalConsensus(BaseModel):
    """Agrégation des variantes Monte Carlo via Borda."""
    course_id: str
    nb_variantes: int = 5
    variants_seeds: List[int] = [42, 43, 44, 45, 46]
    consensus_borda: List[int]         # classement final [3, 7, 12, 1, 5]
    scores_borda_full: Dict[str, int] = {}  # {"3": 43, "7": 35, ...}
    robuste_threshold: float = 0.80
    robuste: bool = True
    confiance_interne: float = 0.0


# ─────────────────────────────────────────────
# S007 — ExternalData
# ─────────────────────────────────────────────
class ExternalSource(BaseModel):
    nom: str
    type: str = "web"               # "web" | "social"
    url: Optional[str] = None
    confiance: float = 0.5


class ExternalData(BaseModel):
    """Données collectées depuis le web."""
    course_id: Optional[str] = None
    nb_sources: int = 0
    timestamp: Optional[str] = None
    qualite_score: float = 0.0
    sources: List[ExternalSource] = []
    aggregation: Dict[str, Any] = {}  # {"3": {"mentions": 14, "sentiment_avg": 0.8}}


# ─────────────────────────────────────────────
# S008 — ExternalConsensus
# ─────────────────────────────────────────────
class ExternalConsensus(BaseModel):
    """Synthèse des pronostics externes."""
    course_id: str
    sources_pronostics: List[str] = []
    top5_external: List[int] = []
    external_scores: Dict[str, float] = {}  # {"3": 0.95, "12": 0.82}
    qualite: ExternalQualite = ExternalQualite.INDISPONIBLE

    def get_rank(self, numero: int) -> int:
        """Retourne le rang externe d'un cheval (1-based). 999 si absent."""
        if numero in self.top5_external:
            return self.top5_external.index(numero) + 1
        return 999


# ─────────────────────────────────────────────
# S009 — MetaPrediction
# ─────────────────────────────────────────────
class MetaPrediction(BaseModel):
    """Prédiction finale unitaire pour un cheval."""
    course_id: str
    position: int
    numero: int
    nom: Optional[str] = None
    meta_score: float
    score_mc: float
    score_externe: Optional[float] = None
    signal_externe: str = "🔵 Analyse interne seule"
    robuste: bool = True
    stars: str = "⭐"
    raisons: List[str] = []


# ─────────────────────────────────────────────
# S010 — TopPrediction
# ─────────────────────────────────────────────
class TopPrediction(BaseModel):
    """Top 5 final ordonné et validé."""
    course_id: str
    date: Optional[str] = None
    confidence_global: float = 0.0
    predictions: List[MetaPrediction] = []
    # Champs legacy conservés pour compatibilité
    classement_final: List[int] = []
    confiance_etoiles: str = "⭐"
    signal: str = ""


# ─────────────────────────────────────────────
# S011 — HadesAlert
# ─────────────────────────────────────────────
class HadesAlert(BaseModel):
    """Alerte unitaire détectée sur un cheval."""
    cheval_numero: int
    cheval_nom: Optional[str] = None
    niveau: HadesNiveau = HadesNiveau.GREEN
    score: float = 0.0
    signaux: List[str] = []           # ["VARIATION_COTE", "BUZZ_ARTIFICIEL"]
    raisons: List[str] = []
    date_detectee: Optional[str] = None


# ─────────────────────────────────────────────
# S012 — HadesReport
# ─────────────────────────────────────────────
class HadesReport(BaseModel):
    """Rapport d'intégrité de la course entière."""
    course_id: str
    niveau_global: HadesNiveau = HadesNiveau.GREEN
    nb_signaux: int = 0
    chevaux_suspects: List[int] = []
    signaux_detail: List[HadesAlert] = []
    recommendations: str = ""
    mode_test: bool = True            # En test : log only, no block


# ─────────────────────────────────────────────
# S013 — EVKellyResult
# ─────────────────────────────────────────────
class EVKellyResult(BaseModel):
    """Calculs financiers pour un cheval."""
    cheval_numero: int
    cheval: str
    prob_reelle: float
    prob_implicite: float
    ev: float                         # Expected Value
    is_value_bet: bool = False
    kelly_raw: float = 0.0
    kelly_applique: float = 0.0
    kelly_cappe: float = 0.0
    mise_recommandee: float = 0.0     # en FCFA
    niveau_risque: RiskLevel = RiskLevel.MODERE


# ─────────────────────────────────────────────
# S014 — BettingRecommendation
# ─────────────────────────────────────────────
class BettingRecommendation(BaseModel):
    """Objet actionnable pour l'utilisateur final."""
    course_id: str
    cheval: str                       # "3 - STAR WINNER"
    cote: float
    prob_win: float
    mise_max_fcfa: float
    mise_conseillee_fcfa: float
    ev_pct: float
    risque: RiskLevel
    justification: str


# ─────────────────────────────────────────────
# S015 — RiskAssessment
# ─────────────────────────────────────────────
class RiskAssessment(BaseModel):
    """Analyse consolidée du risque avant reporting."""
    course_id: str
    niveau_global: str = "ACCEPTABLE"
    nb_alertes: int = 0
    mise_totale_max: float = 0.0
    hades_blocked: bool = False
    alertes: List[str] = []
    recommandations: List[str] = []


# ─────────────────────────────────────────────
# S016 — PipelineRun
# ─────────────────────────────────────────────
class PipelineRun(BaseModel):
    """Objet racine sauvegardé pour tracer l'exécution."""
    run_id: str
    date: str
    statut: PipelineState = PipelineState.CREATED
    heure_debut: Optional[str] = None
    heure_fin: Optional[str] = None
    duree_secondes: Optional[float] = None
    courses_traitees: int = 0
    nb_erreurs: int = 0
    mode: str = "morning_analysis"    # "morning_analysis" | "evening_evaluation"
    resultats_par_course: List[str] = []
    gemini_calls_used: int = 0
    active_key: str = "KEY1"


# ─────────────────────────────────────────────
# S017 — StepResult
# ─────────────────────────────────────────────
class StepResult(BaseModel):
    """Traçabilité d'une étape spécifique du pipeline."""
    step_name: str
    agent: str
    statut: str                        # "success" | "warning" | "error"
    duree_ms: Optional[float] = None
    output_schema: Optional[str] = None
    errors: List[str] = []
    timestamp: Optional[str] = None


# ─────────────────────────────────────────────
# S019 — AgentMessage
# ─────────────────────────────────────────────
class AgentMessage(BaseModel):
    """Bus de message interne entre agents."""
    from_agent: str
    to_agent: str
    message_type: str                  # "request" | "response" | "error"
    payload_schema: Optional[str] = None
    correlation_id: Optional[str] = None
    status: str = "pending"
    timestamp: Optional[str] = None


# ─────────────────────────────────────────────
# S021 — CourseReport
# ─────────────────────────────────────────────
class CourseReport(BaseModel):
    """Document complet compilé par l'Agent Reporting."""
    course_id: str
    date: str
    hippodrome: Optional[str] = None
    distance: Optional[int] = None
    is_lonab: bool = False
    top5: Optional[TopPrediction] = None
    hades: Optional[HadesReport] = None
    ev_kelly: List[EVKellyResult] = []
    risk: Optional[RiskAssessment] = None
    confiance: float = 0.0
    raw_analysis: Optional[str] = None   # narration Gemini
    telegram_message: Optional[str] = None


# ─────────────────────────────────────────────
# S022 — DailySummary
# ─────────────────────────────────────────────
class DailySummary(BaseModel):
    """Synthèse multi-courses de la journée."""
    date: str
    nb_courses: int = 0
    nb_courses_completees: int = 0
    ev_moyen_jour: float = 0.0
    duree_totale: float = 0.0
    run_id: Optional[str] = None
    top_global: List[Dict[str, Any]] = []
    hades_summary: str = ""
    lonab_course_id: Optional[str] = None
    lonab_available: bool = True


# ─────────────────────────────────────────────
# S023 — TelegramMessage
# ─────────────────────────────────────────────
class TelegramMessage(BaseModel):
    """Charge utile prête pour l'API Telegram."""
    chat_id: str
    parse_mode: str = "MarkdownV2"
    disable_notification: bool = False
    text: str


# ─────────────────────────────────────────────
# S024 — ArchivedResult
# ─────────────────────────────────────────────
class ArchivedResult(BaseModel):
    """Schéma d'insertion Firebase."""
    archive_id: str
    date: str
    course_id: str
    is_lonab: bool = False
    top5_json: str = "[]"
    hades_json: str = "{}"
    ev_kelly_json: str = "[]"
    bankroll_impact: float = 0.0
    timestamp: Optional[str] = None


# ─────────────────────────────────────────────
# S025-S028 — Configs (représentation Python)
# ─────────────────────────────────────────────
class ScoringWeights(BaseModel):
    historique: float = 0.35
    forme: float = 0.25
    terrain: float = 0.20
    handicap: float = 0.10
    fraicheur: float = 0.10

    @field_validator("fraicheur")
    @classmethod
    def weights_sum_to_one(cls, v, info):
        values = info.data
        total = sum([
            values.get("historique", 0),
            values.get("forme", 0),
            values.get("terrain", 0),
            values.get("handicap", 0),
            v
        ])
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Les poids doivent sommer à 1.0, obtenu: {total}")
        return v


class HADESConfig(BaseModel):
    enabled: bool = True
    mode_test: bool = True
    cote_deviation_threshold: float = 0.20
    artificial_favorite_prob_max: float = 0.10
    buzz_multiplier: float = 3.0
    score_alerte_threshold: float = 0.70


class FinanceConfig(BaseModel):
    kelly_fraction: float = 0.25
    kelly_max_pct: float = 0.05
    ev_threshold: float = 0.05
    bookmaker_margin: float = 0.15
    capital_reference: float = 100000.0  # FCFA


# ─────────────────────────────────────────────
# S031 — WebScraperResult
# ─────────────────────────────────────────────
class WebScraperResult(BaseModel):
    """Data extraite d'une URL cible."""
    source: str
    url: str
    status_code: int = 200
    data: Dict[str, Any] = {}
    timestamp: Optional[str] = None
    quality_score: float = 1.0
    errors: List[str] = []


# ─────────────────────────────────────────────
# S033 — EvaluationDailyReport (NOUVEAU V9)
# ─────────────────────────────────────────────
class CourseEvaluation(BaseModel):
    course_id: str
    is_lonab: bool = False
    predicted_winner: Optional[int] = None
    official_winner: Optional[int] = None
    top1_correct: Optional[bool] = None
    top3_predicted: List[int] = []
    top3_official: List[int] = []
    top3_score: int = 0               # nb corrects dans top3 (0-3)
    top5_predicted: List[int] = []
    top5_official: List[int] = []
    top5_score: int = 0


class EvaluationDailyReport(BaseModel):
    """Rapport d'auto-évaluation quotidien."""
    date: str
    day_number: int                   # J1 → J30
    courses: List[CourseEvaluation] = []
    score_jour_top1: float = 0.0      # % top1 corrects ce jour
    score_jour_top3: float = 0.0      # % top3 corrects ce jour
    running_top1_all_days: float = 0.0
    running_top3_all_days: float = 0.0
    lonab_precision: Optional[float] = None
    lonab_available: bool = True
    evaluation_narrative: Optional[str] = None  # narration Gemini


# ─────────────────────────────────────────────
# Gemini Quota Tracking
# ─────────────────────────────────────────────
class GeminiKeyStatus(BaseModel):
    key_id: str
    calls_used: int = 0
    calls_budget: int = 24
    active: bool = True
    last_error: Optional[str] = None


class GeminiQuotaReport(BaseModel):
    date: str
    key1: GeminiKeyStatus
    key2: GeminiKeyStatus
    total_calls_used: int = 0
    total_budget: int = 48
    active_key: str = "KEY1"
    rotations_today: int = 0


# Résolution des références forward
ProgramDocument.model_rebuild()
Course.model_rebuild()
