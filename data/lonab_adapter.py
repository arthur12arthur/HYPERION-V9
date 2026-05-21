"""
HYPERION V9 — LONAB Adapter (Agent B - Étape 1)
Identifie la course LONAB du jour via cascade :
  1. Scraping HTML lonab.bf
  2. Extraction PDF pdfplumber
  3. Gemini Vision (dernier recours)
  4. Fallback : course PMU de remplacement
"""
import os
import re
import requests
import pdfplumber
from io import BytesIO
from typing import Optional, Tuple
from bs4 import BeautifulSoup

from domain.schemas import Course, Runner, ProgramDocument
from utils.logger import get_logger
from utils.config import config
from utils.helpers import today_str, now_iso, safe_json_loads
from utils.validators import filter_valid_runners, parse_forme

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
TIMEOUT = config.sources.get("scraping", {}).get("timeout_seconds", 15)


class LonabAdapter:
    """
    Extrait la course officielle LONAB du jour.
    Cascade de 4 méthodes — le pipeline ne s'arrête jamais.
    """

    def __init__(self):
        self.lonab_url = config.lonab_url
        self.monitor   = None  # injecté par l'orchestrateur

    def set_monitor(self, monitor):
        self.monitor = monitor

    def _log(self, step: str, status: str, message: str = ""):
        logger.info(f"[LONAB] {step}: {status} {message}".strip())
        if self.monitor:
            self.monitor.log(f"LONAB_{step}", status, message)

    # ──────────────────────────────────────────────────────────────
    # MÉTHODE PRINCIPALE
    # ──────────────────────────────────────────────────────────────
    def get_lonab_course(self, date_str: str = None) -> Tuple[Optional[Course], str]:
        """
        Retourne (course_lonab, methode_utilisee).
        course_lonab peut être None si toutes les méthodes échouent.
        """
        if date_str is None:
            date_str = today_str()

        # Tentative 1 : Scraping HTML
        course = self._try_html_scraping(date_str)
        if course:
            self._log("HTML", "OK", f"Course identifiée : {course.nom}")
            return course, "HTML_SCRAPING"

        # Tentative 2 : PDF pdfplumber
        course = self._try_pdf_plumber(date_str)
        if course:
            self._log("PDF_PLUMBER", "OK", f"Course identifiée : {course.nom}")
            return course, "PDF_PLUMBER"

        # Tentative 3 : Gemini Vision
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

    # ──────────────────────────────────────────────────────────────
    # TENTATIVE 1 — SCRAPING HTML
    # ──────────────────────────────────────────────────────────────
    def _try_html_scraping(self, date_str: str) -> Optional[Course]:
        """Scrape la page programme de lonab.bf"""
        try:
            urls_to_try = [
                f"{self.lonab_url}/programme",
                f"{self.lonab_url}/programme-du-jour",
                f"{self.lonab_url}",
            ]

            for url in urls_to_try:
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")
                    course = self._parse_lonab_html(soup, date_str)
                    if course:
                        return course

                except requests.RequestException:
                    continue

        except Exception as e:
            self._log("HTML", "FAIL", str(e)[:100])

        return None

    def _parse_lonab_html(self, soup: BeautifulSoup, date_str: str) -> Optional[Course]:
        """
        Parse la page HTML LONAB pour extraire la course du jour.
        Structure approximative — à ajuster selon la vraie structure lonab.bf
        """
        try:
            # Chercher les éléments contenant les informations de course
            # Patterns courants sur les sites hippiques africains
            course_blocks = (
                soup.find_all("div", class_=re.compile(r"course|race|programme", re.I)) or
                soup.find_all("table", class_=re.compile(r"course|partant|programme", re.I)) or
                soup.find_all("section", class_=re.compile(r"course|programme", re.I))
            )

            if not course_blocks:
                logger.debug("LONAB HTML: aucun bloc course trouvé")
                return None

            # Chercher hippodrome et nom de course
            hippodrome = self._extract_text_pattern(
                soup, r"(Vincennes|Cagnes|Longchamp|Auteuil|Chantilly|Deauville|Saint-Cloud|Pau|Lyon)"
            )
            nom_course = self._extract_text_pattern(
                soup, r"(Prix|Course|Réunion)\s+[\w\s\-\']{3,50}"
            )
            heure = self._extract_text_pattern(soup, r"\d{1,2}[h:]\d{2}")

            if not hippodrome and not nom_course:
                return None

            # Extraire les partants depuis les tableaux
            partants = self._extract_runners_from_html(soup, date_str)

            if len(partants) < 3:
                logger.debug(f"LONAB HTML: seulement {len(partants)} partants trouvés")
                return None

            return Course(
                course_id  = "R1C1_LONAB",
                nom        = nom_course or "Course LONAB",
                date       = date_str,
                heure      = heure,
                hippodrome = hippodrome,
                partants   = partants,
                is_lonab   = True,
                source     = "LONAB_HTML"
            )

        except Exception as e:
            logger.warning(f"LONAB HTML parse error: {e}")
            return None

    def _extract_text_pattern(self, soup: BeautifulSoup, pattern: str) -> Optional[str]:
        """Cherche un pattern regex dans le texte de la page."""
        text = soup.get_text(" ", strip=True)
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(0).strip() if match else None

    def _extract_runners_from_html(self, soup: BeautifulSoup, date_str: str) -> list:
        """Extrait les partants depuis les tableaux HTML."""
        runners = []

        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            texts = [c.get_text(strip=True) for c in cells]

            # Chercher une ligne avec un numéro de partant
            numero_str = texts[0] if texts else ""
            if not numero_str.isdigit():
                continue

            try:
                runner = Runner(
                    numero           = int(numero_str),
                    nom              = texts[1] if len(texts) > 1 else f"CHEVAL_{numero_str}",
                    poids            = float(texts[3]) if len(texts) > 3 and texts[3].replace(".", "").isdigit() else 58.0,
                    cote_officielle  = float(texts[-1]) if texts[-1].replace(".", "").isdigit() else 0.0,
                    forme_brute      = texts[4] if len(texts) > 4 else None,
                    source           = "LONAB_HTML"
                )
                runners.append(runner)
            except Exception:
                continue

        return runners

    # ──────────────────────────────────────────────────────────────
    # TENTATIVE 2 — PDF PDFPLUMBER
    # ──────────────────────────────────────────────────────────────
    def _try_pdf_plumber(self, date_str: str) -> Optional[Course]:
        """Télécharge et parse le PDF du journal hippique LONAB."""
        try:
            pdf_urls = [
                f"{self.lonab_url}/programme/{date_str}.pdf",
                f"{self.lonab_url}/journal/{date_str}.pdf",
                f"{self.lonab_url}/programme.pdf",
            ]

            for pdf_url in pdf_urls:
                try:
                    resp = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT)
                    if resp.status_code != 200:
                        continue
                    if "application/pdf" not in resp.headers.get("Content-Type", ""):
                        continue

                    course = self._parse_pdf_content(resp.content, date_str)
                    if course:
                        return course

                except requests.RequestException:
                    continue

        except Exception as e:
            self._log("PDF_PLUMBER", "FAIL", str(e)[:100])

        return None

    def _parse_pdf_content(self, pdf_bytes: bytes, date_str: str) -> Optional[Course]:
        """Parse un PDF avec pdfplumber pour extraire la course."""
        try:
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += page.extract_text() or ""

                if not full_text.strip():
                    logger.debug("PDF vide ou scanné — pdfplumber ne peut pas extraire")
                    return None

                return self._parse_text_content(full_text, date_str, source="LONAB_PDF")

        except Exception as e:
            logger.warning(f"pdfplumber parse error: {e}")
            return None

    def _parse_text_content(self, text: str, date_str: str, source: str) -> Optional[Course]:
        """
        Parse du texte brut (PDF ou HTML to text) pour extraire une course.
        Patterns génériques adaptés aux journaux hippiques français.
        """
        lines = text.split("\n")

        # Chercher hippodrome
        hippodromes_fr = [
            "Vincennes", "Cagnes", "Longchamp", "Auteuil", "Chantilly",
            "Deauville", "Saint-Cloud", "Pau", "Lyon", "Marseille",
            "Toulouse", "Bordeaux", "Nantes", "Strasbourg"
        ]
        hippodrome = None
        for hp in hippodromes_fr:
            if hp.lower() in text.lower():
                hippodrome = hp
                break

        # Chercher les partants (lignes avec numéro + nom + cote)
        runners = []
        runner_pattern = re.compile(
            r"^(\d{1,2})\s+([A-Z][A-Z\s\'\-]{2,30})\s+.*?(\d+[\.,]\d+)\s*$"
        )

        for line in lines:
            match = runner_pattern.match(line.strip())
            if match:
                try:
                    numero = int(match.group(1))
                    nom    = match.group(2).strip()
                    cote   = float(match.group(3).replace(",", "."))

                    # Extraire poids si présent
                    poids_match = re.search(r"(\d{2,3}[\.,]\d)\s*kg", line)
                    poids = float(poids_match.group(1).replace(",", ".")) if poids_match else 58.0

                    runners.append(Runner(
                        numero          = numero,
                        nom             = nom,
                        poids           = poids,
                        cote_officielle = cote,
                        source          = source
                    ))
                except Exception:
                    continue

        if len(runners) < 3:
            return None

        # Chercher nom de course
        nom_match = re.search(r"(Prix|Course|Réunion)\s+([\w\s\-\']{3,40})", text, re.IGNORECASE)
        nom_course = nom_match.group(0).strip() if nom_match else "Course LONAB"

        # Chercher heure
        heure_match = re.search(r"\d{1,2}[h:]\d{2}", text)
        heure = heure_match.group(0) if heure_match else None

        return Course(
            course_id  = "R1C1_LONAB",
            nom        = nom_course,
            date       = date_str,
            heure      = heure,
            hippodrome = hippodrome,
            partants   = runners,
            is_lonab   = True,
            source     = source
        )

    # ──────────────────────────────────────────────────────────────
    # TENTATIVE 3 — GEMINI VISION (DERNIER RECOURS)
    # ──────────────────────────────────────────────────────────────
    def _try_gemini_vision(self, date_str: str) -> Optional[Course]:
        """Utilise Gemini Vision pour lire le PDF si pdfplumber échoue."""
        try:
            from utils.quota_manager import quota_manager

            if not quota_manager.can_use(1):
                self._log("GEMINI_VISION", "SKIP", "Quota épuisé")
                return None

            # Télécharger le PDF
            pdf_url = f"{self.lonab_url}/programme.pdf"
            resp = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return None

            import base64
            pdf_b64 = base64.b64encode(resp.content).decode("utf-8")

            prompt = self._build_vision_prompt(date_str)

            # Appel Gemini Vision avec le PDF en base64
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
        from utils.config import config
        base_prompt = config.load_prompt("extraction")
        return f"{base_prompt}\nDate attendue : {date_str}"

    def _build_course_from_gemini(self, data: dict, date_str: str) -> Optional[Course]:
        """Construit une Course depuis la réponse JSON de Gemini."""
        try:
            courses_data = data.get("courses", [])
            if not courses_data:
                return None

            c_data   = courses_data[0]
            partants = []

            for p in c_data.get("partants", []):
                try:
                    forme_brute = p.get("forme_brute")
                    runner = Runner(
                        numero          = int(p.get("numero", 0)),
                        nom             = str(p.get("nom", "")).strip(),
                        age             = p.get("age"),
                        sexe            = p.get("sexe"),
                        poids           = float(p.get("poids", 58.0)),
                        corde           = p.get("corde"),
                        forme_brute     = forme_brute,
                        forme_parsed    = parse_forme(forme_brute) if forme_brute else [],
                        gains_totaux    = p.get("gains_totaux"),
                        jockey          = p.get("jockey"),
                        entraineur      = p.get("entraineur"),
                        cote_officielle = float(p.get("cote_officielle", 0.0)),
                        source          = "LONAB_GEMINI_VISION"
                    )
                    partants.append(runner)
                except Exception:
                    continue

            if len(partants) < 3:
                return None

            return Course(
                course_id  = c_data.get("course_id", "R1C1_LONAB"),
                nom        = c_data.get("nom", "Course LONAB"),
                date       = date_str,
                heure      = c_data.get("heure"),
                hippodrome = data.get("hippodrome") or c_data.get("hippodrome"),
                type_course= c_data.get("type_course"),
                distance   = c_data.get("distance"),
                conditions = c_data.get("conditions"),
                partants   = partants,
                is_lonab   = True,
                source     = "LONAB_GEMINI_VISION"
            )
        except Exception as e:
            logger.warning(f"Gemini build course error: {e}")
            return None


# Instance globale
lonab_adapter = LonabAdapter()
