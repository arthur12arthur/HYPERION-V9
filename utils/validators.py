"""
HYPERION V9 — Validateurs de données
Trois niveaux : STRICT, RELAXED, MINIMAL
"""
from typing import List, Optional, Tuple
from domain.schemas import Runner, Course, ProgramDocument
from utils.logger import get_logger

logger = get_logger(__name__)


def validate_runner_strict(runner: Runner) -> Tuple[bool, List[str]]:
    """
    Validation STRICT : rejette si un champ obligatoire manque ou type incorrect.
    Retourne (valide: bool, erreurs: List[str])
    """
    errors = []

    if runner.numero <= 0:
        errors.append(f"Numéro invalide : {runner.numero}")
    if not runner.nom or runner.nom.strip() == "":
        errors.append("Nom du cheval vide")
    if runner.cote_officielle < 0:
        errors.append(f"Cote négative : {runner.cote_officielle}")
    if runner.poids <= 0:
        errors.append(f"Poids invalide : {runner.poids}")
    if runner.is_non_partant:
        errors.append("Cheval non partant — à exclure")

    return len(errors) == 0, errors


def validate_runner_relaxed(runner: Runner) -> Runner:
    """
    Validation RELAXED : remplace les valeurs manquantes par des défauts.
    Retourne un Runner corrigé.
    """
    data = runner.dict()

    if not data.get("nom"):
        data["nom"] = f"CHEVAL_{data.get('numero', '?')}"
    if data.get("cote_officielle", 0) <= 0:
        data["cote_officielle"] = 9.99  # cote inconnue
    if data.get("poids", 0) <= 0:
        data["poids"] = 58.0
    if data.get("forme_brute") and not data.get("forme_parsed"):
        data["forme_parsed"] = parse_forme(data["forme_brute"])

    return Runner(**data)


def parse_forme(forme_brute: str) -> List[int]:
    """
    Parse la forme brute en liste d'entiers.
    "1a 2a 3a" → [1, 2, 3]
    "D 1 2" → [0, 1, 2]  (D = Disqualifié → 0)
    """
    if not forme_brute:
        return []

    result = []
    for token in forme_brute.strip().split():
        # Extraire le chiffre (ignore les suffixes a, b, g...)
        digits = "".join(c for c in token if c.isdigit())
        if digits:
            result.append(int(digits))
        elif token.upper() in ("D", "T", "A"):
            result.append(0)  # Disqualifié / Tombé / Arrêté

    return result[:10]  # max 10 dernières courses


def filter_valid_runners(runners: List[Runner]) -> Tuple[List[Runner], List[Runner]]:
    """
    Filtre les partants valides.
    Retourne (valides, rejetes)
    """
    valid, rejected = [], []

    seen_numeros = set()
    for runner in runners:
        ok, errors = validate_runner_strict(runner)

        # Doublon de numéro
        if runner.numero in seen_numeros:
            errors.append(f"Numéro en doublon : {runner.numero}")
            ok = False

        if ok:
            seen_numeros.add(runner.numero)
            # Parser la forme si pas encore fait
            if runner.forme_brute and not runner.forme_parsed:
                runner = runner.copy(update={"forme_parsed": parse_forme(runner.forme_brute)})
            valid.append(runner)
        else:
            rejected.append(runner)
            logger.warning(f"Runner rejeté #{runner.numero} {runner.nom}: {errors}")

    logger.info(f"Validation runners: {len(valid)} valides, {len(rejected)} rejetés")
    return valid, rejected


def validate_course(course: Course) -> Tuple[bool, List[str]]:
    """Validation basique d'une course."""
    errors = []
    if not course.course_id:
        errors.append("course_id manquant")
    if not course.nom:
        errors.append("nom de course manquant")
    if len(course.partants) < 3:
        errors.append(f"Trop peu de partants : {len(course.partants)} (minimum 3)")
    return len(errors) == 0, errors


def validate_program_document(doc: ProgramDocument) -> Tuple[bool, List[str]]:
    """Validation du document programme complet."""
    errors = []
    if not doc.date:
        errors.append("date manquante")
    if doc.nb_courses == 0 or not doc.courses:
        errors.append("Aucune course dans le document")
    return len(errors) == 0, errors
