"""
HYPERION V9 — PMU Adapter
Scraping PMU.fr : partants, cotes, sélection des 10 courses du jour.
Zéro appel Gemini — scraping pur.
"""
import re
import time
import requests
from typing import List, Optional, Dict
from bs4 import BeautifulSoup
from datetime import date

from domain.schemas import Course, Runner, ProgramDocument
from utils.logger import get_logger
from utils.config import config
from utils.helpers import today_str
from utils.validators import filter_valid_runners, parse_forme

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT  = config.sources.get("scraping", {}).get("timeout_seconds", 15)
DELAY    = config.sources.get("scraping", {}).get("delay_between_requests", 1.5)
PMU_BASE = config.pmu_base_url  # https://www.pmu.fr


class PMUAdapter:
    """
    Scrape PMU.fr pour obtenir :
    1. Le programme complet du jour (liste des courses)
    2. Les partants + cotes d'une course spécifique
    """

    def __init__(self):
        self.base_url = PMU_BASE
        self.monitor  = None

    def set_monitor(self, monitor):
        self.monitor = monitor

    def _log(self, step: str, status: str, msg: str = ""):
        logger.info(f"[PMU] {step}: {status} {msg}".strip())
        if self.monitor:
            self.monitor.log(f"PMU_{step}", status, msg)

    # ──────────────────────────────────────────────────────────────
    # PROGRAMME DU JOUR — LISTE DES COURSES
    # ──────────────────────────────────────────────────────────────
    def get_daily_program(self, date_str: str = None) -> List[Course]:
        """
        Récupère toutes les courses disponibles sur PMU.fr pour la date donnée.
        Retourne une liste de Course (sans partants détaillés — juste l'index).
        """
        if date_str is None:
            date_str = today_str()

        # Format date PMU : YYYY-MM-DD → YYYYMMDD ou DD-MM-YYYY selon l'URL
        date_pmu = date_str.replace("-", "")  # 20250115

        urls_to_try = [
            f"{self.base_url}/turf/jour/{date_str}",
            f"{self.base_url}/turf/programme/{date_str}",
            f"{self.base_url}/turf/{date_pmu}",
        ]

        for url in urls_to_try:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    continue

                courses = self._parse_program_page(resp.text, date_str)
                if courses:
                    self._log("PROGRAMME", "OK", f"{len(courses)} courses trouvées")
                    return courses

            except requests.RequestException as e:
                self._log("PROGRAMME", "RETRY", str(e)[:60])
                continue

        # Fallback : API JSON PMU (souvent disponible)
        courses = self._try_pmu_api(date_str)
        if courses:
            return courses

        self._log("PROGRAMME", "FAIL", "PMU.fr inaccessible")
        return []

    def _parse_program_page(self, html: str, date_str: str) -> List[Course]:
        """Parse la page programme PMU pour extraire les courses."""
        courses = []
        soup = BeautifulSoup(html, "lxml")

        # Chercher les blocs de course (structure PMU.fr)
        course_blocks = (
            soup.find_all("div", class_=re.compile(r"course|race-card|reunion", re.I)) or
            soup.find_all("article", class_=re.compile(r"course|race", re.I)) or
            soup.find_all("li",  class_=re.compile(r"course|race", re.I))
        )

        for i, block in enumerate(course_blocks[:15], 1):
            try:
                course = self._extract_course_from_block(block, date_str, i)
                if course:
                    courses.append(course)
            except Exception as e:
                logger.debug(f"Course block {i} parse error: {e}")
                continue

        return courses

    def _extract_course_from_block(self, block, date_str: str, index: int) -> Optional[Course]:
        """Extrait les infos d'un bloc HTML de course."""
        text = block.get_text(" ", strip=True)

        # Hippodrome
        hippodromes = [
            "Vincennes", "Cagnes", "Longchamp", "Auteuil", "Chantilly",
            "Deauville", "Saint-Cloud", "Pau", "Lyon", "Marseille",
            "Toulouse", "Bordeaux", "Nantes", "Strasbourg", "Vichy",
            "Compiegne", "Fontainebleau", "Le Croise-Laroche"
        ]
        hippodrome = next((h for h in hippodromes if h.lower() in text.lower()), None)
        if not hippodrome:
            return None

        # Heure
        heure_match = re.search(r"(\d{1,2})[h:](\d{2})", text)
        heure = heure_match.group(0) if heure_match else None

        # Numéro et nom de course
        course_id_match = re.search(r"R(\d)C(\d)", text)
        course_id = course_id_match.group(0) if course_id_match else f"R1C{index}"

        nom_match = re.search(r"(Prix|Course|Conditions)\s+([\w\s\-\']{3,40})", text, re.I)
        nom = nom_match.group(0).strip() if nom_match else f"Course {index} — {hippodrome}"

        # Distance
        dist_match = re.search(r"(\d{3,4})\s*m", text)
        distance = int(dist_match.group(1)) if dist_match else None

        # Lien vers la page partants
        link = block.find("a", href=re.compile(r"/turf/|/partants/"))
        partants_url = f"{self.base_url}{link['href']}" if link and link.get("href") else None

        return Course(
            course_id   = course_id,
            nom         = nom,
            date        = date_str,
            heure       = heure,
            hippodrome  = hippodrome,
            distance    = distance,
            partants    = [],  # chargés séparément
            source      = "PMU_PROGRAMME",
            is_lonab    = False
        )

    def _try_pmu_api(self, date_str: str) -> List[Course]:
        """Essaie l'API JSON non-officielle de PMU.fr"""
        try:
            # PMU expose parfois des données JSON
            date_pmu = date_str.replace("-", "")
            url = f"{self.base_url}/rest/client/1/programme/{date_pmu}"
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)

            if resp.status_code != 200:
                return []

            data = resp.json()
            courses = []

            reunions = data.get("programme", {}).get("reunions", [])
            for reunion in reunions:
                hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "")
                for course_data in reunion.get("courses", []):
                    course_id = f"R{reunion.get('numOrdre', 1)}C{course_data.get('numOrdre', 1)}"
                    courses.append(Course(
                        course_id   = course_id,
                        nom         = course_data.get("libelle", f"Course {course_id}"),
                        date        = date_str,
                        heure       = course_data.get("heureDepart", ""),
                        hippodrome  = hippodrome,
                        distance    = course_data.get("distance"),
                        type_course = course_data.get("discipline", {}).get("libelle"),
                        partants    = [],
                        source      = "PMU_API_JSON"
                    ))

            if courses:
                self._log("API_JSON", "OK", f"{len(courses)} courses via API")
            return courses

        except Exception as e:
            logger.debug(f"PMU API JSON failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────
    # PARTANTS D'UNE COURSE SPÉCIFIQUE
    # ──────────────────────────────────────────────────────────────
    def get_runners(self, course: Course) -> List[Runner]:
        """
        Enrichit une course avec ses partants complets depuis PMU.fr.
        Retourne la liste des Runner (vide si échec).
        """
        time.sleep(DELAY)  # respecter le serveur

        runners = []

        # Méthode 1 : URL directe partants
        runners = self._scrape_runners_html(course)
        if runners:
            self._log("RUNNERS", "OK", f"{course.course_id}: {len(runners)} partants")
            return runners

        # Méthode 2 : API JSON partants
        runners = self._fetch_runners_api(course)
        if runners:
            self._log("RUNNERS_API", "OK", f"{course.course_id}: {len(runners)} partants")
            return runners

        self._log("RUNNERS", "FAIL", f"{course.course_id}: aucun partant trouvé")
        return []

    def _scrape_runners_html(self, course: Course) -> List[Runner]:
        """Scrape la page partants PMU.fr"""
        try:
            # Construire l'URL des partants
            date_pmu = course.date.replace("-", "")
            hippodrome_slug = (course.hippodrome or "").lower().replace(" ", "-").replace("'", "")

            urls = [
                f"{self.base_url}/turf/{course.date}/{hippodrome_slug}/{course.course_id.lower()}/partants",
                f"{self.base_url}/turf/partants/{date_pmu}/{course.course_id}",
                f"{self.base_url}/turf/{date_pmu}/partants/{course.course_id}",
            ]

            for url in urls:
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                    if resp.status_code != 200:
                        continue

                    runners = self._parse_runners_table(resp.text, course)
                    if runners:
                        return runners

                except requests.RequestException:
                    continue

        except Exception as e:
            logger.debug(f"PMU runners HTML error: {e}")

        return []

    def _parse_runners_table(self, html: str, course: Course) -> List[Runner]:
        """Parse un tableau HTML de partants PMU."""
        runners = []
        soup = BeautifulSoup(html, "lxml")

        # Trouver le tableau des partants
        tables = soup.find_all("table")
        rows = []

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) > 3:
                break

        for row in rows[1:]:  # skip header
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            texts = [c.get_text(strip=True) for c in cells]

            try:
                # Structure typique PMU : Num | Nom | Jockey | Poids | Cote
                numero_str = re.search(r"\d+", texts[0])
                if not numero_str:
                    continue

                numero = int(numero_str.group())
                nom    = texts[1].upper().strip() if len(texts) > 1 else f"CHEVAL_{numero}"

                # Cote : chercher dans les dernières colonnes
                cote = 0.0
                for t in reversed(texts):
                    cote_match = re.search(r"(\d+[\.,]\d+)", t)
                    if cote_match:
                        cote = float(cote_match.group(1).replace(",", "."))
                        break

                # Poids
                poids = 58.0
                for t in texts:
                    poids_match = re.search(r"^(\d{2,3}[\.,]\d)$", t)
                    if poids_match:
                        poids = float(poids_match.group(1).replace(",", "."))
                        break

                # Jockey (souvent en majuscules 2+ mots)
                jockey = None
                for t in texts[2:5]:
                    if re.match(r"^[A-Z][A-Z\s\.\-]{3,}$", t):
                        jockey = t
                        break

                runner = Runner(
                    numero          = numero,
                    nom             = nom,
                    poids           = poids,
                    cote_officielle = cote,
                    jockey          = jockey,
                    source          = "PMU_HTML"
                )
                runners.append(runner)

            except Exception:
                continue

        return runners

    def _fetch_runners_api(self, course: Course) -> List[Runner]:
        """Essaie l'API JSON PMU pour les partants."""
        try:
            date_pmu = course.date.replace("-", "")
            # Extraire R et C depuis course_id
            rc_match = re.search(r"R(\d+)C(\d+)", course.course_id)
            if not rc_match:
                return []

            r_num = rc_match.group(1)
            c_num = rc_match.group(2)

            url = f"{self.base_url}/rest/client/1/programme/{date_pmu}/R{r_num}/C{c_num}/partants"
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)

            if resp.status_code != 200:
                return []

            data = resp.json()
            runners = []

            for partant in data.get("partants", []):
                cheval = partant.get("cheval", {})
                try:
                    forme_brute = cheval.get("formeDetail", "")
                    runner = Runner(
                        numero          = int(partant.get("numPmu", 0)),
                        nom             = cheval.get("nom", "").upper().strip(),
                        age             = cheval.get("age"),
                        sexe            = cheval.get("sexe"),
                        poids           = float(partant.get("poidsJockey", 58.0)),
                        corde           = partant.get("placeCorde"),
                        forme_brute     = forme_brute,
                        forme_parsed    = parse_forme(forme_brute),
                        gains_totaux    = cheval.get("gainsCarriere"),
                        jockey          = partant.get("jockey", {}).get("nom"),
                        entraineur      = partant.get("entraineur", {}).get("nom"),
                        cote_officielle = float(partant.get("cotePmu", 0.0)),
                        source          = "PMU_API_JSON"
                    )
                    runners.append(runner)
                except Exception:
                    continue

            return runners

        except Exception as e:
            logger.debug(f"PMU runners API error: {e}")
            return []

    # ──────────────────────────────────────────────────────────────
    # SÉLECTION DES 10 COURSES DU JOUR
    # ──────────────────────────────────────────────────────────────
    def select_daily_courses(
        self,
        lonab_course: Optional[Course],
        max_courses: int = 10
    ) -> List[Course]:
        """
        Sélectionne les 10 courses à analyser :
        - Position 1 : course LONAB (ou remplacement si indisponible)
        - Positions 2-10 : courses PMU triées par nb partants (plus riches en données)
        """
        date_str = today_str()
        pmu_program = self.get_daily_program(date_str)

        selected = []

        # Position 1 : LONAB
        if lonab_course:
            selected.append(lonab_course)
            lonab_id = lonab_course.course_id
        else:
            # LONAB inaccessible : première course PMU comme remplacement
            if pmu_program:
                replacement = pmu_program[0]
                replacement.is_lonab_replacement = True
                selected.append(replacement)
                lonab_id = replacement.course_id
                logger.warning(f"LONAB absent — remplacé par {replacement.nom}")
            else:
                lonab_id = None

        # Positions 2-N : autres courses PMU
        pmu_others = [
            c for c in pmu_program
            if c.course_id != lonab_id
        ]

        # Enrichir avec partants pour trier par nombre de partants
        enriched = []
        for course in pmu_others[:max_courses + 2]:  # quelques extras au cas où
            runners = self.get_runners(course)
            if runners:
                course.partants = runners
                course.nb_partants = len(runners)
                enriched.append(course)

        # Trier par nombre de partants décroissant (plus de données = meilleure analyse)
        enriched.sort(key=lambda c: len(c.partants), reverse=True)
        selected.extend(enriched[:max_courses - len(selected)])

        # Enrichir aussi la course LONAB si ses partants ne sont pas encore chargés
        if selected and len(selected[0].partants) == 0:
            runners = self.get_runners(selected[0])
            if runners:
                selected[0].partants = runners

        logger.info(f"Sélection finale : {len(selected)} courses — "
                    f"LONAB={'✅' if lonab_course else '⚠️ remplacée'}")
        return selected


# Instance globale
pmu_adapter = PMUAdapter()
