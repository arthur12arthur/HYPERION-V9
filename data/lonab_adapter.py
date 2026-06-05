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
from typing import Optional, Tuple
from datetime import datetime

from domain.schemas import Course, Runner, ProgramDocument
from utils.logger import get_logger
from utils.config import config
from utils.helpers import today_str, now_iso, safe_json_loads
from utils.validators import filter_valid_runners, parse_forme
from data.lonab_scraper import lonab_scraper, ScraperStatus

logger = get_logger(__name__)

TIMEOUT = config.sources.get("lonab", {}).get("timeout_seconds", 20)


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
        course = self._try_pdf_scraper(target_date)
        if course:
            self._log("PDF_SCRAPER", "OK", f"Course identifiée : {course.nom}")
            return course, "PDF_SCRAPER"

        # Tentative 2 : Gemini Vision
        course = self._try_gemini_vision(date_str)
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
    def _try_pdf_scraper(self, target_date: datetime) -> Optional[Course]:
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
            course = self._extract_from_pdf(pdf_path, target_date.strftime("%Y-%m-%d"))
            return course

        except Exception as e:
            self._log("PDF_SCRAPER", "FAIL", str(e)[:100])
            return None

    def _extract_from_pdf(self, pdf_path, date_str: str) -> Optional[Course]:
        """Extrait une course depuis le PDF LONAB."""
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += page.extract_text() or ""

                if not full_text.strip():
                    logger.debug("[LONAB] PDF vide ou scanné")
                    return None

                return self._parse_text_content(full_text, date_str, source="LONAB_PDF")

        except Exception as e:
            logger.warning(f"[LONAB] Erreur extraction PDF : {e}")
            return None

    def _parse_text_content(self, text: str, date_str: str, source: str) -> Optional[Course]:
        """
        Parse du texte brut (PDF) pour extraire une course.
        Patterns génériques adaptés aux journaux hippiques.
        """
        lines = text.split("\n")

        # Chercher hippodrome
        hippodromes_fr = [
            "Vincennes", "Cagnes", "Longchamp", "Auteuil", "Chantilly",
            "Deauville", "Saint-Cloud", "Pau", "Lyon", "Marseille",
            "Toulouse", "Bordeaux", "Nantes", "Strasbourg", "Paris",
            "Enghien", "Compiegne", "Fontainebleau"
        ]
        hippodrome = None
        for hp in hippodromes_fr:
            if hp.lower() in text.lower():
                hippodrome = hp
                break

        if not hippodrome:
            # Essayer extraction depuis les lignes
            for line in lines[:20]:  # premiers 20 lignes
                for hp in hippodromes_fr:
                    if hp.lower() in line.lower():
                        hippodrome = hp
                        break
                if hippodrome:
                    break

        # Chercher les partants (lignes avec numéro + nom + cote)
        runners = []
        runner_pattern = re.compile(
            r"^(\d{1,2})\s+([A-Z][A-Z\s\'\-]{2,40})\s+.*?(\d+[\.,]\d+)\s*$"
        )

        for line in lines:
            match = runner_pattern.match(line.strip())
            if match:
                try:
                    numero = int(match.group(1))
                    nom = match.group(2).strip()
                    cote = float(match.group(3).replace(",", "."))

                    # Extraire poids si présent
                    poids_match = re.search(r"(\d{2,3}[\.,]\d)\s*kg", line)
                    poids = float(poids_match.group(1).replace(",", ".")) if poids_match else 58.0

                    runners.append(Runner(
                        numero=numero,
                        nom=nom,
                        poids=poids,
                        cote_officielle=cote,
                        source=source
                    ))
                except Exception:
                    continue

        if len(runners) < 3:
            logger.debug(f"[LONAB] Seulement {len(runners)} partants trouvés")
            return None

        # Chercher nom de course
        nom_match = re.search(
            r"(Prix|Course|Réunion|Conditions)\s+([\w\s\-\']{3,60})",
            text,
            re.IGNORECASE
        )
        nom_course = nom_match.group(0).strip() if nom_match else "Course LONAB"

        # Chercher heure
        heure_match = re.search(r"\d{1,2}[h:]\d{2}", text)
        heure = heure_match.group(0) if heure_match else None

        # Chercher distance
        distance_match = re.search(r"(\d{3,4})\s*m(?:ètres)?", text)
        distance = int(distance_match.group(1)) if distance_match else None

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

    # ──────────────────────────────────────────────────────────────────
    # TENTATIVE 2 — GEMINI VISION (DERNIER RECOURS)
    # ──────────────────────────────────────────────────────────────────
    def _try_gemini_vision(self, date_str: str) -> Optional[Course]:
        """Utilise Gemini Vision comme dernier recours."""
        try:
            from utils.quota_manager import quota_manager

            if not quota_manager.can_use(1):
                self._log("GEMINI_VISION", "SKIP", "Quota épuisé")
                return None

            # Chercher PDF en cache ou télécharger
            try:
                year, month, day = date_str.split("-")
                target_date = datetime(int(year), int(month), int(day))
            except Exception:
                return None

            scraper_result = self.scraper.get_program_status(target_date)
            if not scraper_result.pdf_path:
                return None

            pdf_path = scraper_result.pdf_path

            import base64
            with open(pdf_path, "rb") as f:
                pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = self._build_vision_prompt(date_str)

            # Appel Gemini Vision
            import google.generativeai as genai
            key = quota_manager.keys[quota_manager.current]["value"]
            genai.configure(api_key=key)

            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content([
                {"mime_type": "application/pdf", "data": pdf_b64},
                prompt
            ])

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
