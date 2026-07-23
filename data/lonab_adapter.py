"""
HYPERION V9 — LONAB Adapter (Agent B - Étape 1)
Identifie la course LONAB du jour via :
  1. Téléchargement + extraction PDF (lonab_scraper)
  2. Extraction via Gemini Vision
  3. Fallback : course PMU de remplacement

Utilise le scraper V7 éprouvé pour récupérer le PDF LONAB
"""
import os
import re
from io import BytesIO
from typing import Optional, Tuple, List
from datetime import datetime

from domain.schemas import Course, Runner, ProgramDocument
from utils.logger import get_logger
from utils.config import config
from utils.helpers import today_str, now_iso, safe_json_loads
from utils.validators import filter_valid_runners, parse_forme
from data.lonab_scraper import lonab_scraper, ScraperStatus

logger = get_logger(__name__)

TIMEOUT = config.sources.get("lonab", {}).get("timeout_seconds", 20)

# Dossier de debug : quand 0 partant est trouvé, on dépose un extrait du texte
# brut du PDF ici pour pouvoir diagnostiquer sans avoir à relancer le run.
DEBUG_DIR = "./data/cache/lonab/debug"


class LonabAdapter:
    """
    Extrait la course officielle LONAB du jour.
    Utilise le scraper PDF éprouvé de V7.
    Cascade : Scraper PDF → Gemini Vision → Fallback PMU
    """

    def __init__(self):
        self.scraper = lonab_scraper
        self.monitor = None  # injecté par l'orchestrateur
        logger.info("[LONAB] Adapter initialisé avec scraper PDF")

    def set_monitor(self, monitor):
        self.monitor = monitor

    def _log(self, step: str, status: str, message: str = ""):
        logger.info(f"[LONAB] {step}: {status} {message}".strip())
        if self.monitor:
            self.monitor.log(f"LONAB_{step}", status, message)

    # ──────────────────────────────────────────────────────────────────
    # MÉTHODE PRINCIPALE
    # ──────────────────────────────────────────────────────────────────
    def get_lonab_course(self, date_str: str = None) -> Tuple[Optional[Course], str]:
        """
        Retourne (course_lonab, methode_utilisee).
        course_lonab peut être None si toutes les méthodes échouent.

        Cascade :
          1. PDF Scraper (éprouvé V7)
          2. Gemini Vision (dernier recours)
          3. None → fallback PMU requis
        """
        if date_str is None:
            date_str = today_str()

        # Convertir format YYYY-MM-DD → datetime pour le scraper
        try:
            year, month, day = date_str.split("-")
            target_date = datetime(int(year), int(month), int(day))
        except Exception as e:
            logger.error(f"[LONAB] Format date invalide : {date_str}")
            return None, "FAILED"

        # Tentative 1 : Scraper PDF
        course = self._try_pdf_scraper(target_date, date_str)
        if course:
            self._log("PDF_SCRAPER", "OK", f"Course identifiée : {course.nom}")
            return course, "PDF_SCRAPER"

        # Tentative 2 : Gemini Vision
        course = self._try_gemini_vision(target_date, date_str)
        if course:
            self._log("GEMINI_VISION", "OK", f"Course identifiée : {course.nom}")
            return course, "GEMINI_VISION"

        # Aucune méthode n'a fonctionné
        self._log("ALL_METHODS", "FAILED", "LONAB inaccessible — fallback PMU requis")
        if self.monitor:
            self.monitor.alert_telegram(
                f"⚠️ LONAB inaccessible ce matin \\({date_str}\\)\n"
                f"Course officielle LONAB non identifiée\\.\n"
                f"Remplacée par une course PMU\\."
            )
        return None, "FAILED"

    # ──────────────────────────────────────────────────────────────────
    # TENTATIVE 1 — SCRAPER PDF (V7)
    # ──────────────────────────────────────────────────────────────────
    def _try_pdf_scraper(self, target_date: datetime, date_str: str) -> Optional[Course]:
        """
        Utilise le scraper PDF éprouvé de V7.
        Télécharge le PDF LONAB et l'extrait.
        """
        try:
            self._log("PDF_SCRAPER", "RUNNING", f"Téléchargement PDF {target_date.strftime('%d/%m/%Y')}")

            # Télécharger PDF via scraper V7
            scraper_result = self.scraper.get_program_status(target_date, force_download=False)

            if scraper_result.status == ScraperStatus.UNAVAILABLE:
                self._log("PDF_SCRAPER", "UNAVAILABLE", scraper_result.reason)
                return None

            if scraper_result.status == ScraperStatus.NOT_FOUND:
                self._log("PDF_SCRAPER", "NOT_FOUND", scraper_result.reason)
                return None

            # PDF trouvé et téléchargé
            pdf_path = scraper_result.pdf_path
            self._log("PDF_SCRAPER", "OK", f"PDF téléchargé : {pdf_path}")

            # Extraire contenu PDF via pdfplumber
            course = self._extract_from_pdf(pdf_path, date_str)
            return course

        except Exception as e:
            self._log("PDF_SCRAPER", "FAIL", str(e)[:100])
            return None

    def _extract_from_pdf(self, pdf_path, date_str: str) -> Optional[Course]:
        """Extrait une course depuis le PDF LONAB."""
        try:
            import pdfplumber

            logger.info(f"[LONAB] Extraction PDF : {pdf_path}")

            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    logger.warning("[LONAB] PDF vide (0 pages)")
                    return None

                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
                    # Filet de sécurité : certaines mises en page (réunions
                    # d'import comme Vincennes) ne se parsent pas bien avec
                    # les réglages par défaut. On retente avec un tolérance
                    # de tri de mots plus fine si la page n'a rien donné.
                    elif page.extract_words():
                        text_alt = page.extract_text(x_tolerance=1, y_tolerance=1)
                        if text_alt:
                            full_text += text_alt + "\n"

                if not full_text.strip():
                    logger.debug("[LONAB] PDF vide ou scanné — aucun texte extrait")
                    return None

                logger.info(f"[LONAB] {len(full_text)} caractères extraits du PDF")
                return self._parse_text_content(full_text, date_str, source="LONAB_PDF")

        except Exception as e:
            logger.warning(f"[LONAB] Erreur extraction PDF : {str(e)[:100]}")
            return None

    def _dump_debug_text(self, text: str, date_str: str, hippodrome: str):
        """
        Sauvegarde un extrait du texte brut quand 0 partant est trouvé,
        pour pouvoir diagnostiquer la mise en page sans reproduire le run.
        """
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            path = os.path.join(DEBUG_DIR, f"{date_str}_{hippodrome}_0partants.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text[:4000])
            logger.warning(f"[LONAB] 0 partants — extrait brut sauvegardé : {path}")
        except Exception as e:
            logger.debug(f"[LONAB] Impossible d'écrire le debug dump : {e}")

    def _parse_text_content(self, text: str, date_str: str, source: str) -> Optional[Course]:
        """
        Parse du texte brut (PDF) pour extraire une course.
        Patterns génériques adaptés aux journaux hippiques.

        Cascade de 3 patterns, du plus strict au plus permissif, car la
        mise en page LONAB diffère entre réunions locales et réunions
        d'import (Vincennes, Cagnes, etc.).
        """
        lines = text.split("\n")

        # Chercher hippodrome
        hippodromes_fr = [
            "Vincennes", "Cagnes", "Longchamp", "Auteuil", "Chantilly",
            "Deauville", "Saint-Cloud", "Pau", "Lyon", "Marseille",
            "Toulouse", "Bordeaux", "Nantes", "Strasbourg", "Paris",
            "Enghien", "Compiegne", "Fontainebleau", "Le Croise-Laroche"
        ]
        hippodrome = None

        for hp in hippodromes_fr:
            if hp.lower() in text.lower():
                hippodrome = hp
                break

        if not hippodrome:
            logger.debug("[LONAB] Aucun hippodrome détecté")
            return None

        logger.info(f"[LONAB] Hippodrome trouvé : {hippodrome}")

        runners = self._extract_runners(lines)

        logger.info(f"[LONAB] {len(runners)} partants trouvés")

        if len(runners) < 3:
            logger.warning(f"[LONAB] Insufficient runners: {len(runners)} < 3")
            self._dump_debug_text(text, date_str, hippodrome)
            return None

        # Chercher nom de course
        nom_match = re.search(
            r"(Prix|Course|Réunion|Conditions|NOCTURNE|PRIX|JH_?P[MU]{2})[^.\n]{5,80}",
            text,
            re.IGNORECASE
        )
        nom_course = nom_match.group(0).strip() if nom_match else "Course LONAB"

        # Nettoyer nom_course
        nom_course = nom_course.replace("JH_PMU", "").replace("JH_PMUB", "").strip()
        nom_course = re.sub(r"^(DU|DE|D')\s+", "", nom_course).strip()

        logger.info(f"[LONAB] Nom course : {nom_course}")

        # Chercher heure
        heure_match = re.search(r"(\d{1,2})[h:](\d{2})", text)
        heure = heure_match.group(0) if heure_match else None

        # Chercher distance
        distance_match = re.search(r"(\d{3,4})\s*m(?:ètres)?", text)
        distance = int(distance_match.group(1)) if distance_match else None

        logger.info(f"[LONAB] Heure: {heure}, Distance: {distance}m")

        return Course(
            course_id="R1C1_LONAB",
            nom=nom_course,
            date=date_str,
            heure=heure,
            hippodrome=hippodrome,
            distance=distance,
            partants=runners,
            is_lonab=True,
            source=source
        )

    def _extract_runners(self, lines: List[str]) -> List[Runner]:
        """
        Essaie plusieurs patterns d'extraction, du plus strict au plus
        permissif. S'arrête au premier pattern qui trouve >= 3 partants.
        """
        # Pattern 1 (original) : Numero Nom(MAJUSCULES) ... Cote décimale en fin de ligne
        strict_pattern = re.compile(
            r"^(\d{1,2})\s+([A-Z][A-Z\s\'\-]{2,50}?)\s+.*?(\d+[\.,]\d+)\s*$"
        )

        # Pattern 2 : plus tolérant sur la casse du nom et la position de la cote
        # (utile pour les réunions d'import dont la mise en page diffère)
        loose_pattern = re.compile(
            r"^(\d{1,2})\s{1,4}([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\'\-\.]{2,50}?)\s{2,}.*?(\d+[\.,]\d+)?\s*$"
        )

        # Pattern 3 : découpage par colonnes larges (2+ espaces), sans exiger
        # de cote — la cote sera enrichie plus tard via PMU si besoin.
        column_pattern = re.compile(r"^(\d{1,2})\s{2,}([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\'\-\.]{2,50})")

        for pattern in (strict_pattern, loose_pattern, column_pattern):
            runners = self._apply_runner_pattern(lines, pattern)
            if len(runners) >= 3:
                return runners

        # Aucun pattern n'a donné >= 3 : on retourne le meilleur essai quand même
        # (permet au caller de logguer le nombre réel trouvé)
        best = self._apply_runner_pattern(lines, strict_pattern)
        return best

    def _apply_runner_pattern(self, lines: List[str], pattern: re.Pattern) -> List[Runner]:
        runners = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or len(line_stripped) < 5:
                continue

            match = pattern.match(line_stripped)
            if not match:
                continue

            try:
                numero = int(match.group(1))
                nom = match.group(2).strip().upper()

                cote_raw = match.group(3) if match.lastindex and match.lastindex >= 3 else None
                cote = float(cote_raw.replace(",", ".")) if cote_raw else 0.0

                poids_match = re.search(r"(\d{2,3}[\.,]\d+)\s*kg", line)
                poids = float(poids_match.group(1).replace(",", ".")) if poids_match else 58.0

                runner = Runner(
                    numero=numero,
                    nom=nom,
                    poids=poids,
                    cote_officielle=cote,
                    source="LONAB_PDF"
                )
                runners.append(runner)
                logger.debug(f"[LONAB] Partant trouvé : {numero} {nom}")
            except Exception as e:
                logger.debug(f"[LONAB] Erreur parsing partant : {e}")
                continue

        return runners

    # ──────────────────────────────────────────────────────────────────
    # TENTATIVE 2 — GEMINI VISION (DERNIER RECOURS)
    # ──────────────────────────────────────────────────────────────────
    def _try_gemini_vision(self, target_date: datetime, date_str: str) -> Optional[Course]:
        """
        Utilise Gemini Vision comme dernier recours.

        Migré vers le SDK `google-genai` (le SDK `google-generativeai` est
        déprécié) et vers le modèle `gemini-2.0-flash` (gemini-1.5-flash
        n'est plus servi par l'API v1beta — d'où le 404 dans le run précédent).
        """
        try:
            from utils.quota_manager import quota_manager

            if not quota_manager.can_use(1):
                self._log("GEMINI_VISION", "SKIP", "Quota épuisé")
                return None

            scraper_result = self.scraper.get_program_status(target_date)
            if not scraper_result.pdf_path:
                return None

            pdf_path = scraper_result.pdf_path

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            prompt = self._build_vision_prompt(date_str)

            # Nouveau SDK : google-genai
            from google import genai
            from google.genai import types

            key = quota_manager.keys[quota_manager.current]["value"]
            client = genai.Client(api_key=key)

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                    prompt,
                ],
            )

            quota_manager.keys[quota_manager.current]["calls"] += 1
            self._log("GEMINI_VISION", "APPEL_EFFECTUE", "1 token utilisé")

            result = safe_json_loads(response.text)
            if not result:
                return None

            return self._build_course_from_gemini(result, date_str)

        except Exception as e:
            self._log("GEMINI_VISION", "FAIL", str(e)[:100])
            return None

    def _build_vision_prompt(self, date_str: str) -> str:
        """Construit le prompt pour Gemini Vision."""
        base_prompt = config.load_prompt("extraction") if hasattr(config, "load_prompt") else (
            "Extrais la course hippique principale du document en JSON. "
            "Format: {'course_id': '...', 'nom': '...', 'hippodrome': '...', 'partants': [...]}"
        )
        return f"{base_prompt}\nDate attendue : {date_str}"

    def _build_course_from_gemini(self, data: dict, date_str: str) -> Optional[Course]:
        """Construit une Course depuis la réponse JSON de Gemini."""
        try:
            courses_data = data.get("courses", [])
            if not courses_data:
                return None

            c_data = courses_data[0]
            partants = []

            for p in c_data.get("partants", []):
                try:
                    forme_brute = p.get("forme_brute")
                    runner = Runner(
                        numero=int(p.get("numero", 0)),
                        nom=str(p.get("nom", "")).strip(),
                        age=p.get("age"),
                        sexe=p.get("sexe"),
                        poids=float(p.get("poids", 58.0)),
                        corde=p.get("corde"),
                        forme_brute=forme_brute,
                        forme_parsed=parse_forme(forme_brute) if forme_brute else [],
                        gains_totaux=p.get("gains_totaux"),
                        jockey=p.get("jockey"),
                        entraineur=p.get("entraineur"),
                        cote_officielle=float(p.get("cote_officielle", 0.0)),
                        source="LONAB_GEMINI_VISION"
                    )
                    partants.append(runner)
                except Exception:
                    continue

            if len(partants) < 3:
                return None

            return Course(
                course_id=c_data.get("course_id", "R1C1_LONAB"),
                nom=c_data.get("nom", "Course LONAB"),
                date=date_str,
                heure=c_data.get("heure"),
                hippodrome=data.get("hippodrome") or c_data.get("hippodrome"),
                type_course=c_data.get("type_course"),
                distance=c_data.get("distance"),
                conditions=c_data.get("conditions"),
                partants=partants,
                is_lonab=True,
                source="LONAB_GEMINI_VISION"
            )
        except Exception as e:
            logger.warning(f"[LONAB] Erreur build course from Gemini : {e}")
            return None


# Instance globale
lonab_adapter = LonabAdapter()
