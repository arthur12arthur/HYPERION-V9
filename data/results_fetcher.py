"""
HYPERION V9 — Results Fetcher (Agent H - Étape 1)
Récupère les résultats officiels PMU du soir.
1 seule requête HTTP pour toutes les courses du jour.
Zéro appel Gemini.
"""
import re
import time
import requests
from typing import Dict, List, Optional
from bs4 import BeautifulSoup

from utils.logger import get_logger
from utils.config import config
from utils.helpers import today_str, now_iso

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}
TIMEOUT  = config.sources.get("scraping", {}).get("timeout_seconds", 15)
PMU_BASE = config.pmu_base_url


class ResultsFetcher:
    """
    Récupère les résultats officiels des courses pour l'évaluation du soir.
    Structure retournée : {course_id: {"winner": int, "top3": [...], "top5": [...]}}
    """

    def __init__(self):
        self.monitor = None
        self.backup_sources = config.sources.get("resultats_backup", [])

    def set_monitor(self, monitor):
        self.monitor = monitor

    def _log(self, step: str, status: str, msg: str = ""):
        logger.info(f"[RESULTS] {step}: {status} {msg}".strip())
        if self.monitor:
            self.monitor.log(f"RESULTS_{step}", status, msg)

    # ──────────────────────────────────────────────────────────────
    # MÉTHODE PRINCIPALE
    # ──────────────────────────────────────────────────────────────
    def fetch_all_results(
        self,
        date_str: str,
        course_ids: List[str],
        max_retries: int = 3
    ) -> Dict[str, dict]:
        """
        Récupère tous les résultats du jour en une seule passe.
        Retries automatiques si résultats pas encore disponibles.

        Returns:
            {
                "R1C1": {"winner": 3, "top3": [3,12,7], "top5": [3,12,7,5,1]},
                "R1C2": {...},
                ...
            }
        """
        for attempt in range(max_retries):
            results = self._try_fetch_results(date_str, course_ids)

            if results and len(results) > 0:
                self._log("FETCH", "OK",
                         f"{len(results)} résultats sur {len(course_ids)} courses")
                return results

            if attempt < max_retries - 1:
                wait = 7200  # 2h entre chaque retry
                self._log("RETRY", f"Tentative {attempt+1}/{max_retries}",
                         f"retry dans {wait//3600}h")
                if self.monitor:
                    self.monitor.alert_telegram(
                        f"⏳ Résultats PMU non disponibles — "
                        f"retry {attempt+2}/{max_retries} dans {wait//3600}h"
                    )
                time.sleep(wait)

        # Tous les retries épuisés
        self._log("FETCH", "FAILED", "Résultats non disponibles après retries")
        if self.monitor:
            self.monitor.alert_telegram(
                "⚠️ Résultats officiels introuvables\\.\n"
                "Évaluation J reportée à demain\\."
            )
        return {}

    def _try_fetch_results(
        self,
        date_str: str,
        course_ids: List[str]
    ) -> Dict[str, dict]:
        """Tente de récupérer les résultats depuis toutes les sources disponibles."""

        # Source 1 : PMU.fr page résultats globale
        results = self._fetch_from_pmu(date_str, course_ids)
        if results:
            return results

        # Source 2 : API JSON PMU
        results = self._fetch_from_pmu_api(date_str, course_ids)
        if results:
            return results

        # Sources backup (Equidia, Paris-Turf)
        for backup_url_template in self.backup_sources:
            url = backup_url_template.format(date=date_str)
            results = self._fetch_from_backup(url, course_ids)
            if results:
                return results

        return {}

    # ──────────────────────────────────────────────────────────────
    # SOURCE 1 — PMU.fr PAGE RÉSULTATS
    # ──────────────────────────────────────────────────────────────
    def _fetch_from_pmu(
        self,
        date_str: str,
        course_ids: List[str]
    ) -> Dict[str, dict]:
        """Scrape la page résultats PMU.fr"""
        try:
            date_pmu = date_str.replace("-", "")
            urls = [
                f"{PMU_BASE}/turf/{date_str}/resultats",
                f"{PMU_BASE}/turf/resultats/{date_str}",
                f"{PMU_BASE}/resultats/{date_pmu}",
            ]

            for url in urls:
                html = self._fetch(url)
                if not html:
                    continue

                results = self._parse_results_page(html, course_ids, date_str)
                if results:
                    self._log("PMU_HTML", "OK", f"URL: {url}")
                    return results

        except Exception as e:
            self._log("PMU_HTML", "FAIL", str(e)[:80])

        return {}

    def _parse_results_page(
        self,
        html: str,
        course_ids: List[str],
        date_str: str
    ) -> Dict[str, dict]:
        """Parse la page HTML des résultats PMU."""
        results = {}
        soup = BeautifulSoup(html, "lxml")

        # Chercher les blocs résultats par course
        result_blocks = (
            soup.find_all("div", class_=re.compile(r"result|arrivee|ordre.arrivee", re.I)) or
            soup.find_all("section", class_=re.compile(r"result|arrivee", re.I)) or
            soup.find_all("table", class_=re.compile(r"result|arrivee", re.I))
        )

        for block in result_blocks:
            text = block.get_text(" ", strip=True)

            # Identifier la course (R1C1, R1C2...)
            course_id_match = re.search(r"R(\d+)C(\d+)", text)
            if not course_id_match:
                continue
            course_id = course_id_match.group(0)

            # Extraire l'ordre d'arrivée
            arrival = self._extract_arrival_order(block)
            if arrival:
                results[course_id] = {
                    "winner"    : arrival[0] if arrival else None,
                    "top3"      : arrival[:3],
                    "top5"      : arrival[:5],
                    "full_order": arrival,
                    "source"    : "PMU_HTML",
                    "timestamp" : now_iso()
                }

        return results

    def _extract_arrival_order(self, block) -> List[int]:
        """Extrait l'ordre d'arrivée depuis un bloc HTML."""
        numbers = []

        # Pattern 1 : numéros dans des éléments dédiés
        num_elements = block.find_all(
            class_=re.compile(r"numero|partant.num|arrivee.num|ordre", re.I)
        )
        for el in num_elements:
            text = el.get_text(strip=True)
            if text.isdigit():
                num = int(text)
                if 1 <= num <= 20 and num not in numbers:
                    numbers.append(num)

        if len(numbers) >= 3:
            return numbers

        # Pattern 2 : chercher séquence de numéros dans le texte
        text = block.get_text(" ", strip=True)
        arrivee_match = re.search(
            r"(arrivée?|ordre|résultat)\s*[:–-]?\s*([\d\s\-–/,]{3,30})",
            text, re.IGNORECASE
        )
        if arrivee_match:
            nums_text = arrivee_match.group(2)
            found = re.findall(r"\b(\d{1,2})\b", nums_text)
            for n in found[:7]:
                num = int(n)
                if 1 <= num <= 20 and num not in numbers:
                    numbers.append(num)

        return numbers[:7]

    # ──────────────────────────────────────────────────────────────
    # SOURCE 2 — API JSON PMU
    # ──────────────────────────────────────────────────────────────
    def _fetch_from_pmu_api(
        self,
        date_str: str,
        course_ids: List[str]
    ) -> Dict[str, dict]:
        """Utilise l'API REST non-officielle de PMU."""
        results = {}
        date_pmu = date_str.replace("-", "")

        try:
            # Récupérer le programme pour avoir les réunions
            prog_url = f"{PMU_BASE}/rest/client/1/programme/{date_pmu}"
            prog_resp = requests.get(prog_url, headers=HEADERS, timeout=TIMEOUT)

            if prog_resp.status_code != 200:
                return {}

            prog_data = prog_resp.json()
            reunions  = prog_data.get("programme", {}).get("reunions", [])

            for reunion in reunions:
                r_num = reunion.get("numOrdre", 1)
                for course in reunion.get("courses", []):
                    c_num     = course.get("numOrdre", 1)
                    course_id = f"R{r_num}C{c_num}"

                    if course_id not in course_ids and course_ids:
                        continue

                    # Récupérer les résultats de cette course
                    result_url = (
                        f"{PMU_BASE}/rest/client/1/programme/{date_pmu}"
                        f"/R{r_num}/C{c_num}/rapports-definitifs"
                    )
                    try:
                        r_resp = requests.get(result_url, headers=HEADERS, timeout=TIMEOUT)
                        if r_resp.status_code != 200:
                            continue

                        r_data  = r_resp.json()
                        arrival = self._extract_arrival_from_api(r_data)

                        if arrival:
                            results[course_id] = {
                                "winner"    : arrival[0],
                                "top3"      : arrival[:3],
                                "top5"      : arrival[:5],
                                "full_order": arrival,
                                "source"    : "PMU_API",
                                "timestamp" : now_iso()
                            }

                    except Exception:
                        continue

            if results:
                self._log("PMU_API", "OK", f"{len(results)} résultats")

        except Exception as e:
            self._log("PMU_API", "FAIL", str(e)[:80])

        return results

    def _extract_arrival_from_api(self, data: dict) -> List[int]:
        """Extrait l'ordre d'arrivée depuis la réponse API PMU."""
        arrival = []

        # Chemin typique dans l'API PMU
        combinaisons = (
            data.get("rapportsDefinitifs", {}).get("rapports", []) or
            data.get("arrivee", []) or
            data.get("ordreArrivee", [])
        )

        for item in combinaisons[:7]:
            if isinstance(item, dict):
                num = item.get("numPmu") or item.get("numero")
            elif isinstance(item, int):
                num = item
            else:
                continue

            if num and 1 <= num <= 20 and num not in arrival:
                arrival.append(int(num))

        return arrival

    # ──────────────────────────────────────────────────────────────
    # SOURCES BACKUP
    # ──────────────────────────────────────────────────────────────
    def _fetch_from_backup(
        self,
        url: str,
        course_ids: List[str]
    ) -> Dict[str, dict]:
        """Scrape une source backup (Equidia, Paris-Turf)."""
        try:
            html = self._fetch(url)
            if not html:
                return {}

            soup    = BeautifulSoup(html, "lxml")
            results = {}

            # Pattern générique pour les pages résultats
            result_blocks = soup.find_all(
                class_=re.compile(r"result|arrivee|ordre", re.I)
            )

            for block in result_blocks:
                text = block.get_text(" ", strip=True)
                course_id_match = re.search(r"R(\d+)C(\d+)", text)
                if not course_id_match:
                    continue

                course_id = course_id_match.group(0)
                arrival   = self._extract_arrival_order(block)

                if arrival:
                    results[course_id] = {
                        "winner"    : arrival[0],
                        "top3"      : arrival[:3],
                        "top5"      : arrival[:5],
                        "full_order": arrival,
                        "source"    : url.split("/")[2],
                        "timestamp" : now_iso()
                    }

            if results:
                self._log("BACKUP", "OK", f"{url.split('/')[2]}: {len(results)} résultats")
            return results

        except Exception as e:
            logger.debug(f"Backup source error {url}: {e}")
            return {}

    # ──────────────────────────────────────────────────────────────
    # UTILITAIRE HTTP
    # ──────────────────────────────────────────────────────────────
    def _fetch(self, url: str) -> Optional[str]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            return resp.text if resp.status_code == 200 else None
        except requests.RequestException as e:
            logger.debug(f"Fetch error {url}: {e}")
            return None


# Instance globale
results_fetcher = ResultsFetcher()
