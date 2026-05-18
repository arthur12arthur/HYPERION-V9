from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class Runner(BaseModel):
    numero: int
    nom: str
    cote_officielle: float
    poids: float
    forme_brute: str
    forme_parsed: List[int] = []
    is_non_partant: bool = False

class Course(BaseModel):
    course_id: str
    nom: str
    hippodrome: str
    date: str
    heure: str
    partants: List[Runner]
    is_lonab: bool = False
    is_lonab_replacement: bool = False

class ScoredRunner(Runner):
    score_historique: float = 0.0
    score_forme: float = 0.0
    score_terrain: float = 0.0
    score_handicap: float = 0.0
    score_fraicheur: float = 0.0
    score_global: float = 0.0

class MonteCarloResult(BaseModel):
    numero: int
    win_prob: float
    place_prob: float
    top3_prob: float

class InternalConsensus(BaseModel):
    course_id: str
    consensus_borda: List[int]
    robuste: bool
    confiance_interne: float

class TopPrediction(BaseModel):
    course_id: str
    classement_final: List[int]
    confiance_etoiles: str
    signal: str
