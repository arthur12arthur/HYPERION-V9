"""
HYPERION V9 — PMU Adapter
Scraping PMU.fr : partants, cotes, sélection des 10 courses du jour.
Zéro appel Gemini — scraping pur.
Gère les fallback URLs en cas d'indisponibilité.
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

# En-têtes "navigateur mobile" : l'ancien User-Agent desktop générique est
# plus facilement identifié/bloqué comme trafic de bot que celui d'un
# navigateur mobile réel.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Referer": "https://www.pmu.fr/turf/",
}
TIMEOUT  = config.sources.get("pmu", {}).get("timeout_seconds", 20)
DELAY    = config.sources.get("scraping", {}).get("delay_between_requests", 1.5)
RETRY_MAX = config.sources.get("pmu", {}).get("retry_max", 3)
RETRY_DELAYS = config.sources.get("scraping", {}).get("retry_delays", [2, 5, 10])
PMU_BASE = config.sources.get("pmu", {}).get("url", "https://www.pmu.fr")
PMU_FALLBACKS = config.sources.get("pmu", {}).get("fallback_urls", [])

# API JSON non officielle mais publique et documentée depuis des années
# (utilisée par de nombreux outils tiers), en dernier recours quand
# pmu.fr lui-même est inaccessible depuis l'IP du runner GitHub Actions.
# Le numéro de "client" dans l'URL a bougé au fil du temps (1, 7, 61...) et
# une version invalide répond parfois par un 200 contenant un message
# d'erreur JSON (une simple chaîne) plutôt qu'un objet — d'où la validation
# de type stricte plus bas. On essaie plusieurs versions en cascade.
OFFLINE_API_CLIENT_VERSIONS = ["61", "7", "1", "3"]
OFFLINE_API_HOST = "https://offline.turfinfo.api.pmu.fr/rest/client"


class PMUAdapter:
    """
    Scrape PMU.fr pour obtenir :
    1. Le programme complet du jour (liste des courses)
    2. Les partants + cotes d'une course spécifique

    Implémente une cascade de fallback URLs en cas d'indisponibilité,
    plus une API JSON non-officielle en tout dernier recours.
    """

    def __init__(self):
        self.base_urls = [PMU_BASE] + PMU_FALLBACKS
        self.current_url_index = 0
        self.monitor  = None
        logger.info(f"[PMU] URLs configurées : {self.base_urls}")

    def set_monitor(self, monitor):
        self.monitor = monitor

    def _log(self, step: str, status: str, msg: str = ""):
        logger.info(f"[PMU] {step}: {status} {msg}".strip())
        if self.monitor:
            self.monitor.log(f"PMU_{step}", status, msg)

    def _get_next_url(self) -> str:
        """Retourne l'URL actuelle et prépare la rotation."""
        url = self.base_urls[self.current_url_index % len(self.base_urls)]
        self.current_url_index += 1
        return url

    def _make_request(self, url: str, max_retries: int = None) -> Optional[requests.Response]:
        """
        Effectue une requête HTTP avec retry exponentiel.
        """
        if max_retries is None:
            max_retries = RETRY_MAX

        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code == 200:
                    return resp

                logger.debug(f"PMU request status {resp.status_code} pour {url}")

                # Attendre avant retry
                if attempt < max_retries - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.debug(f"Retry dans {delay}s...")
                    time.sleep(delay)

            except requests.Timeout:
                self._log("TIMEOUT", f"Tentative {attempt + 1}/{max_retries}", url)
                if attempt < max_retries - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    time.sleep(delay)

            except requests.ConnectionError as e:
                self._log("CONNECTION_ERROR", f"Tentative {attempt + 1}/{max_retries}", str(e)[:60])
                if attempt < max_retries - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    time.sleep(delay)

            except Exception as e:
                logger.debug(f"Request error: {e}")
                if attempt < max_retries - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    time.sleep(delay)

        return None

    # ──────────────────────────────────────────────────────────────
    # PROGRAMME DU JOUR — LISTE DES COURSES
    # ──────────────────────────────────────────────────────────────
    def get_daily_program(self, date_str: str = None) -> List[Course]:
        """
        Récupère toutes les courses disponibles sur PMU.fr pour la date donnée.
        Retourne une liste de Course (sans partants détaillés — juste l'index).
        Implémente cascades de fallback URLs, puis l'API JSON publique.
        """
        if date_str is None:
            date_str = today_str()

        # Format date PMU : YYYY-MM-DD → YYYYMMDD ou DD-MM-YYYY selon l'URL
        date_pmu = date_str.replace("-", "")  # 20250115

        # Essayer chaque URL de base avec ses variantes
        for base_url in self.base_urls:
            urls_to_try = [
                f"{base_url}/turf/jour/{date_str}",
                f"{base_url}/turf/programme/{date_str}",
                f"{base_url}/turf/{date_pmu}",
            ]

            for url in urls_to_try:
                try:
                    resp = self._make_request(url, max_retries=2)
                    if resp:
                        courses = self._parse_program_page(resp.text, date_str)
                        if courses:
                            self._log("PROGRAMME", "OK", f"{len(courses)} courses trouvées via {base_url}")
                            return courses

                except Exception as e:
                    self._log("PROGRAMME", "RETRY", str(e)[:60])
                    continue

        # Fallback 1 : API JSON PMU "interne" (souvent hébergée sous pmu.fr même)
        for base_url in self.base_urls:
            courses = self._try_pmu_api(date_str, base_url)
            if courses:
                return courses

        # Fallback 2 : API JSON publique offline.turfinfo.api.pmu.fr
        # (domaine différent de pmu.fr — utile si c'est pmu.fr précisément
        # qui est bloqué pour l'IP du runner, pas le reste d'internet)
        courses = self._try_offline_api(date_str)
        if courses:
            return courses

        self._log("PROGRAMME", "FAIL", "PMU.fr et tous les fallbacks inaccessibles")
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
        partants_url = f"{self.base_urls[0]}{link['href']}" if link and link.get("href") else None

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

    def _try_pmu_api(self, date_str: str, base_url: str = None) -> List[Course]:
        """Essaie l'API JSON non-officielle hébergée sous pmu.fr"""
        if base_url is None:
            base_url = self.base_urls[0]

        try:
            # PMU expose parfois des données JSON
            date_pmu = date_str.replace("-", "")
            url = f"{base_url}/rest/client/1/programme/{date_pmu}"
            resp = self._make_request(url, max_retries=2)

            if not resp:
                return []

            data = resp.json()
            return self._parse_offline_program_json(data, date_str, source="PMU_API_JSON")

        except Exception as e:
            logger.debug(f"PMU API JSON failed: {e}")
            return []

    def _try_offline_api(self, date_str: str) -> List[Course]:
        """
        Essaie l'API JSON publique offline.turfinfo.api.pmu.fr, hébergée
        sur un domaine différent de pmu.fr. Format de date attendu : DDMMYYYY.
        Teste plusieurs versions de "client" dans l'URL, car une version
        invalide répond parfois 200 avec un simple message d'erreur JSON
        (une chaîne, pas un objet) plutôt qu'une vraie 4xx.
        """
        year, month, day = date_str.split("-")
        date_pmu = f"{day}{month}{year}"  # DDMMYYYY

        for version in OFFLINE_API_CLIENT_VERSIONS:
            try:
                url = f"{OFFLINE_API_HOST}/{version}/programme/{date_pmu}"
                resp = self._make_request(url, max_retries=2)
                if not resp:
                    continue

                data = resp.json()
                if not isinstance(data, dict):
                    self._log(
                        "OFFLINE_API", "SKIP",
                        f"client/{version} a répondu un {type(data).__name__} "
                        f"au lieu d'un objet JSON : {str(data)[:80]}"
                    )
                    continue

                courses = self._parse_offline_program_json(data, date_str, source="PMU_OFFLINE_API")
                if courses:
                    self._log("OFFLINE_API", "OK", f"{len(courses)} courses via client/{version}")
                    return courses

            except Exception as e:
                self._log("OFFLINE_API", "RETRY", f"client/{version}: {str(e)[:80]}")
                continue

        self._log("OFFLINE_API", "FAIL", "offline.turfinfo.api.pmu.fr inaccessible (toutes versions testées)")
        return []

    def _parse_offline_program_json(self, data: dict, date_str: str, source: str) -> List[Course]:
        """Parse commun pour les deux variantes de l'API JSON PMU (même structure)."""
        courses = []
        programme = data.get("programme")
        if not isinstance(programme, dict):
            return []
        reunions = programme.get("reunions", [])
        if not isinstance(reunions, list):
            return []

        for reunion in reunions:
            if not isinstance(reunion, dict):
                continue
            hippodrome = (reunion.get("hippodrome") or {}).get("libelleLong", "")
            for course_data in reunion.get("courses", []):
                if not isinstance(course_data, dict):
                    continue
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
                    source      = source
                ))

        return courses

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

        # Méthode 2 : API JSON partants (pmu.fr)
        runners = self._fetch_runners_api(course)
        if runners:
            self._log("RUNNERS_API", "OK", f"{course.course_id}: {len(runners)} partants")
            return runners

        # Méthode 3 : API JSON publique offline.turfinfo.api.pmu.fr
        runners = self._fetch_runners_offline_api(course)
        if runners:
            self._log("RUNNERS_OFFLINE_API", "OK", f"{course.course_id}: {len(runners)} partants")
            return runners

        self._log("RUNNERS", "FAIL", f"{course.course_id}: aucun partant trouvé")
        return []

    def _scrape_runners_html(self, course: Course) -> List[Runner]:
        """Scrape la page partants PMU.fr avec fallbacks"""
        try:
            # Construire l'URL des partants
            date_pmu = course.date.replace("-", "")
            hippodrome_slug = (course.hippodrome or "").lower().replace(" ", "-").replace("'", "")

            for base_url in self.base_urls:
                urls = [
                    f"{base_url}/turf/{course.date}/{hippodrome_slug}/{course.course_id.lower()}/partants",
                    f"{base_url}/turf/partants/{date_pmu}/{course.course_id}",
                    f"{base_url}/turf/{date_pmu}/partants/{course.course_id}",
                ]

                for url in urls:
                    try:
                        resp = self._make_request(url, max_retries=2)
                        if resp:
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
        """Essaie l'API JSON PMU (hébergée sous pmu.fr) pour les partants."""
        try:
            date_pmu = course.date.replace("-", "")
            rc_match = re.search(r"R(\d+)C(\d+)", course.course_id)
            if not rc_match:
                return []

            r_num = rc_match.group(1)
            c_num = rc_match.group(2)

            for base_url in self.base_urls:
                url = f"{base_url}/rest/client/1/programme/{date_pmu}/R{r_num}/C{c_num}/partants"
                resp = self._make_request(url, max_retries=2)

                if not resp:
                    continue

                data = resp.json()
                runners = self._parse_offline_runners_json(data)
                if runners:
                    return runners

        except Exception as e:
            logger.debug(f"PMU runners API error: {e}")

        return []

    def _fetch_runners_offline_api(self, course: Course) -> List[Runner]:
        """
        Essaie l'API JSON publique offline.turfinfo.api.pmu.fr pour les
        partants — dernier recours, domaine différent de pmu.fr.
        Teste les mêmes versions de "client" que _try_offline_api.
        """
        rc_match = re.search(r"R(\d+)C(\d+)", course.course_id)
        if not rc_match:
            return []

        r_num = rc_match.group(1)
        c_num = rc_match.group(2)

        year, month, day = course.date.split("-")
        date_pmu = f"{day}{month}{year}"  # DDMMYYYY

        for version in OFFLINE_API_CLIENT_VERSIONS:
            try:
                url = f"{OFFLINE_API_HOST}/{version}/programme/{date_pmu}/R{r_num}/C{c_num}/participants"
                resp = self._make_request(url, max_retries=2)
                if not resp:
                    continue

                data = resp.json()
                if not isinstance(data, dict):
                    continue

                runners = self._parse_offline_runners_json(data)
                if runners:
                    return runners

            except Exception as e:
                logger.debug(f"PMU offline API runners error (client/{version}): {e}")
                continue

        return []

    def _parse_offline_runners_json(self, data: dict) -> List[Runner]:
        """Parse commun pour les réponses JSON 'participants' (mêmes clés sur les deux APIs)."""
        runners = []
        participants = data.get("participants", data.get("partants", []))
        if not isinstance(participants, list):
            return []

        for partant in participants:
            if not isinstance(partant, dict):
                continue
            cheval = partant.get("cheval", partant)
            if not isinstance(cheval, dict):
                cheval = {}
            try:
                forme_brute = cheval.get("formeDetail", "")
                runner = Runner(
                    numero          = int(partant.get("numPmu", 0)),
                    nom             = str(cheval.get("nom", partant.get("nom", ""))).upper().strip(),
                    age             = cheval.get("age"),
                    sexe            = cheval.get("sexe"),
                    poids           = float(partant.get("poidsJockey", 58.0)),
                    corde           = partant.get("placeCorde"),
                    forme_brute     = forme_brute,
                    forme_parsed    = parse_forme(forme_brute) if forme_brute else [],
                    gains_totaux    = cheval.get("gainsCarriere"),
                    jockey          = (partant.get("jockey") or {}).get("nom"),
                    entraineur      = (partant.get("entraineur") or {}).get("nom"),
                    cote_officielle = float(partant.get("cotePmu", partant.get("dernierRapportDirect", {}).get("rapport", 0.0))
                                            if isinstance(partant.get("dernierRapportDirect"), dict) else partant.get("cotePmu", 0.0)),
                    source          = "PMU_API_JSON"
                )
                runners.append(runner)
            except Exception:
                continue

        return runners

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
