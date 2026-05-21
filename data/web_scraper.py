"""
HYPERION V9 — Web Scraper (Agent C)
Scrape les pronostics externes : Paris-Turf, Equidia, Zone-Turf.
Zéro appel Gemini — scraping HTML pur.
"""
import re
import time
import requests
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

from domain.schemas import Course, ExternalData, ExternalConsensus, ExternalSource, ExternalQualite
from utils.logger import get_logger
from utils.config import config
from utils.helpers import today_str, now_iso

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}
TIMEOUT = config.sources.get("scraping", {}).get("timeout_seconds", 15)
DELAY   = config.sources.get("scraping", {}).get("delay_between_requests", 1.5)


class WebScraper:
    """
    Collecte les pronostics depuis les sources externes françaises.
    Chaque source a sa propre logique de parsing.
    """

    def __init__(self):
        self.sources = config.sources.get("sources_externes", [])
        self.monitor = None

    def set_monitor(self, monitor):
        self.monitor = monitor

    def _log(self, source: str, status: str, msg: str = ""):
        logger.info(f"[SCRAPER] {source}: {status} {msg}".strip())
        if self.monitor:
            self.monitor.log(f"SCRAPING_{source}", status, msg)

    # ──────────────────────────────────────────────────────────────
    # ENRICHISSEMENT D'UNE COURSE
    # ──────────────────────────────────────────────────────────────
    def enrich_course(self, course: Course) -> ExternalData:
        """
        Collecte les pronostics externes pour une course.
        Retourne ExternalData (vide si toutes sources KO — pas bloquant).
        """
        date_str   = course.date
        aggregation: Dict[str, Dict] = {}
        sources_ok: List[ExternalSource] = []

        for src_config in self.sources:
            time.sleep(DELAY)
            nom       = src_config.get("nom", "")
            confiance = src_config.get("confiance", 0.5)

            try:
                top5 = self._scrape_source(src_config, course)

                if top5:
                    sources_ok.append(ExternalSource(
                        nom=nom, confiance=confiance, type="web"
                    ))
                    # Agréger les mentions par numéro
                    for rank, numero in enumerate(top5, 1):
                        key = str(numero)
                        if key not in aggregation:
                            aggregation[key] = {"mentions": 0, "ranks": [], "sentiment_avg": 0.7}
                        aggregation[key]["mentions"] += 1
                        aggregation[key]["ranks"].append(rank)

                    self._log(nom, "OK", f"top5={top5}")
                else:
                    self._log(nom, "NO_DATA")

            except Exception as e:
                self._log(nom, "FAIL", str(e)[:80])

        # Qualité globale selon nombre de sources
        if len(sources_ok) >= 3:
            qualite_score = 0.9
        elif len(sources_ok) == 2:
            qualite_score = 0.7
        elif len(sources_ok) == 1:
            qualite_score = 0.5
        else:
            qualite_score = 0.0

        return ExternalData(
            course_id     = course.course_id,
            nb_sources    = len(sources_ok),
            timestamp     = now_iso(),
            qualite_score = qualite_score,
            sources       = sources_ok,
            aggregation   = aggregation
        )

    def _scrape_source(self, src_config: dict, course: Course) -> List[int]:
        """Dispatche vers le scraper spécifique selon la source."""
        nom = src_config.get("nom", "").lower().replace("-", "").replace(" ", "")

        if "paristurf" in nom:
            return self._scrape_paris_turf(src_config, course)
        elif "equidia" in nom:
            return self._scrape_equidia(src_config, course)
        elif "zoneturf" in nom:
            return self._scrape_zone_turf(src_config, course)
        else:
            return self._scrape_generic(src_config, course)

    # ──────────────────────────────────────────────────────────────
    # PARIS-TURF
    # ──────────────────────────────────────────────────────────────
    def _scrape_paris_turf(self, src_config: dict, course: Course) -> List[int]:
        """Scrape les pronostics Paris-Turf."""
        try:
            hippodrome_slug = (course.hippodrome or "").lower().replace(" ", "-")
            date_slug       = course.date.replace("-", "/")

            urls = [
                f"https://www.paris-turf.com/pronostic/{date_slug}/{hippodrome_slug}",
                f"https://www.paris-turf.com/pronostics/{course.date}",
                f"https://www.paris-turf.com/courses/{course.date}",
            ]

            for url in urls:
                html = self._fetch(url)
                if not html:
                    continue

                soup    = BeautifulSoup(html, "lxml")
                numbers = self._extract_numbers_from_pronostic(soup)
                if numbers:
                    return numbers[:5]

        except Exception as e:
            logger.debug(f"Paris-Turf error: {e}")

        return []

    # ──────────────────────────────────────────────────────────────
    # EQUIDIA
    # ──────────────────────────────────────────────────────────────
    def _scrape_equidia(self, src_config: dict, course: Course) -> List[int]:
        """Scrape les pronostics Equidia."""
        try:
            urls = [
                f"https://www.equidia.fr/courses/{course.date}",
                f"https://www.equidia.fr/pronostics/{course.date}",
            ]

            for url in urls:
                html = self._fetch(url)
                if not html:
                    continue

                soup    = BeautifulSoup(html, "lxml")
                numbers = self._extract_numbers_from_pronostic(soup)
                if numbers:
                    return numbers[:5]

        except Exception as e:
            logger.debug(f"Equidia error: {e}")

        return []

    # ──────────────────────────────────────────────────────────────
    # ZONE-TURF
    # ──────────────────────────────────────────────────────────────
    def _scrape_zone_turf(self, src_config: dict, course: Course) -> List[int]:
        """Scrape les pronostics Zone-Turf."""
        try:
            urls = [
                f"https://www.zone-turf.com/pronostic/{course.date}",
                f"https://www.zone-turf.com/courses/{course.date}",
            ]

            for url in urls:
                html = self._fetch(url)
                if not html:
                    continue

                soup    = BeautifulSoup(html, "lxml")
                numbers = self._extract_numbers_from_pronostic(soup)
                if numbers:
                    return numbers[:5]

        except Exception as e:
            logger.debug(f"Zone-Turf error: {e}")

        return []

    # ──────────────────────────────────────────────────────────────
    # SCRAPER GÉNÉRIQUE
    # ──────────────────────────────────────────────────────────────
    def _scrape_generic(self, src_config: dict, course: Course) -> List[int]:
        """Scraper générique pour toute source non spécifique."""
        try:
            url  = src_config.get("url", "")
            path = src_config.get("pronostic_path", "/{date}")
            full_url = url + path.format(date=course.date)

            html = self._fetch(full_url)
            if not html:
                return []

            soup = BeautifulSoup(html, "lxml")
            return self._extract_numbers_from_pronostic(soup)[:5]

        except Exception as e:
            logger.debug(f"Generic scraper error: {e}")
            return []

    # ──────────────────────────────────────────────────────────────
    # EXTRACTION DES NUMÉROS DE PRONOSTIC
    # ──────────────────────────────────────────────────────────────
    def _extract_numbers_from_pronostic(self, soup: BeautifulSoup) -> List[int]:
        """
        Extrait les numéros de chevaux pronostiqués depuis une page HTML.
        Cherche les patterns courants sur les sites de pronostics.
        """
        numbers = []

        # Pattern 1 : éléments avec classe "pronostic", "numero", "partant-num"
        num_elements = (
            soup.find_all(class_=re.compile(r"pronostic|numero|partant.num|cheval.num", re.I)) or
            soup.find_all("span", class_=re.compile(r"num|numero", re.I)) or
            soup.find_all("td",   class_=re.compile(r"num|numero", re.I))
        )

        for el in num_elements[:10]:
            text = el.get_text(strip=True)
            match = re.search(r"^(\d{1,2})$", text)
            if match:
                num = int(match.group(1))
                if 1 <= num <= 20 and num not in numbers:
                    numbers.append(num)

        if len(numbers) >= 3:
            return numbers

        # Pattern 2 : chercher "Sélection : 3 - 7 - 12 - 1 - 5"
        text = soup.get_text(" ", strip=True)
        selection_match = re.search(
            r"(sélection|pronostic|base|tiercé|quarté)\s*[:–-]?\s*([\d\s\-–/,]{3,30})",
            text, re.IGNORECASE
        )
        if selection_match:
            nums_text = selection_match.group(2)
            found = re.findall(r"\b(\d{1,2})\b", nums_text)
            for n in found[:5]:
                num = int(n)
                if 1 <= num <= 20 and num not in numbers:
                    numbers.append(num)

        return numbers[:5]

    # ──────────────────────────────────────────────────────────────
    # BUILD EXTERNAL CONSENSUS
    # ──────────────────────────────────────────────────────────────
    def build_external_consensus(
        self,
        course: Course,
        external_data: ExternalData
    ) -> ExternalConsensus:
        """
        Construit le consensus externe via méthode Borda sur les sources.
        """
        if external_data.nb_sources == 0:
            return ExternalConsensus(
                course_id  = course.course_id,
                qualite    = ExternalQualite.INDISPONIBLE
            )

        # Reconstruire les top5 par source depuis l'agrégation
        # Pour Borda : donner des points selon les mentions et rangs moyens
        all_numeros = set()
        for key in external_data.aggregation:
            try:
                all_numeros.add(int(key))
            except ValueError:
                continue

        if not all_numeros:
            return ExternalConsensus(
                course_id = course.course_id,
                qualite   = ExternalQualite.INDISPONIBLE
            )

        # Score = mentions × (1 / rang_moyen)
        scores: Dict[int, float] = {}
        for key, data in external_data.aggregation.items():
            try:
                num       = int(key)
                mentions  = data.get("mentions", 0)
                ranks     = data.get("ranks", [1])
                avg_rank  = sum(ranks) / len(ranks) if ranks else 5
                scores[num] = mentions / avg_rank
            except (ValueError, ZeroDivisionError):
                continue

        # Trier par score décroissant
        top5 = sorted(scores.keys(), key=lambda n: scores[n], reverse=True)[:5]

        # Normaliser les scores (0-1)
        max_score  = max(scores.values()) if scores else 1
        ext_scores = {
            str(num): round(scores.get(num, 0) / max_score, 3)
            for num in top5
        }

        # Qualité selon nb sources
        if external_data.nb_sources >= 3:
            qualite = ExternalQualite.HAUTE
        elif external_data.nb_sources == 2:
            qualite = ExternalQualite.MOYENNE
        else:
            qualite = ExternalQualite.FAIBLE

        return ExternalConsensus(
            course_id          = course.course_id,
            sources_pronostics = [s.nom for s in external_data.sources],
            top5_external      = top5,
            external_scores    = ext_scores,
            qualite            = qualite
        )

    # ──────────────────────────────────────────────────────────────
    # HTTP FETCH UTILITAIRE
    # ──────────────────────────────────────────────────────────────
    def _fetch(self, url: str) -> Optional[str]:
        """Effectue une requête GET et retourne le HTML ou None."""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            logger.debug(f"HTTP {resp.status_code} — {url}")
            return None
        except requests.RequestException as e:
            logger.debug(f"Fetch error {url}: {e}")
            return None


# Instance globale
web_scraper = WebScraper()
