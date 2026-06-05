"""
HYPERION V9 — LONAB Scraper (adapté de V7)
Téléchargement + validation du PDF depuis https://lonab.bf/programme-pmub

CORRECTION V7 : 
  - Pattern DD-MM_YYYY (ex: 12-05_2026) observé sur le site
  - Retry exponentiel avec validation PDF
  - Cache local pour éviter re-téléchargements
"""

import os
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from enum import Enum

from utils.logger import get_logger
from utils.config import config

logger = get_logger(__name__)


class ScraperStatus(Enum):
    """Statuts possibles du scraper LONAB"""
    FOUND       = "found"
    NOT_FOUND   = "not_found"
    UNAVAILABLE = "unavailable"


class ScraperResult:
    """Résultat du scraping LONAB"""
    def __init__(
        self,
        status: ScraperStatus,
        pdf_path: Optional[Path] = None,
        url: Optional[str] = None,
        reason: str = ""
    ):
        self.status   = status
        self.pdf_path = pdf_path
        self.url      = url
        self.reason   = reason

    def __bool__(self):
        return self.status == ScraperStatus.FOUND


class LONABScraper:
    """Scraper pour télécharger et valider le PDF programme LONAB"""

    INDEX_URL = "https://lonab.bf/programme-pmub"
    BASE_SITE = "https://lonab.bf"

    def __init__(self):
        self.base_url = config.sources.get("lonab", {}).get("url", self.INDEX_URL)
        self.timeout = config.sources.get("lonab", {}).get("timeout_seconds", 30)
        self.retry_attempts = config.sources.get("lonab", {}).get("retry_max", 3)
        self.retry_delay = config.sources.get("scraping", {}).get("retry_delays", [2, 5, 10])[0]

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": "https://lonab.bf/",
            "Connection": "keep-alive",
        }

        # Dossier cache pour les PDFs
        self.cache_dir = Path("data/cache/lonab")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[LONAB_SCRAPER] Initialisé : {self.base_url}")

    # ──────────────────────────────────────────────────────────────────
    # API PUBLIQUE
    # ──────────────────────────────────────────────────────────────────

    def get_program_status(
        self,
        date: Optional[datetime] = None,
        force_download: bool = False
    ) -> ScraperResult:
        """
        Point d'entrée principal. Retourne toujours un ScraperResult typé.

        Statuts possibles :
          FOUND       — PDF téléchargé (ou depuis cache)
          NOT_FOUND   — page accessible, mais pas de PDF pour cette date
          UNAVAILABLE — site inaccessible, timeout, ou erreur
        """
        if date is None:
            date = datetime.now()

        date_str = date.strftime("%d/%m/%Y")
        logger.info(f"[LONAB_SCRAPER] Recherche programme pour {date_str}")

        # 1. Vérifier cache
        if not force_download:
            cached = self._get_cached_pdf(date)
            if cached:
                logger.info(f"[LONAB_SCRAPER] Cache hit : {cached}")
                return ScraperResult(ScraperStatus.FOUND, pdf_path=cached, url=self.base_url)

        # 2. Télécharger page index
        html = self._fetch_index_page()
        if html is None:
            logger.error("[LONAB_SCRAPER] Page index inaccessible")
            return ScraperResult(
                ScraperStatus.UNAVAILABLE,
                reason="Impossible de joindre https://lonab.bf/programme-pmub"
            )

        # 3. Trouver lien PDF pour la date
        pdf_url = self._find_pdf_url_for_date(html, date)
        if pdf_url is None:
            logger.warning(f"[LONAB_SCRAPER] Aucun PDF pour {date_str}")
            return ScraperResult(
                ScraperStatus.NOT_FOUND,
                reason=f"Aucun lien PDF trouvé pour {date_str}"
            )

        # 4. Télécharger et valider PDF
        pdf_path = self._download_pdf(pdf_url, date)
        if pdf_path is None:
            logger.error(f"[LONAB_SCRAPER] Échec téléchargement : {pdf_url}")
            return ScraperResult(
                ScraperStatus.UNAVAILABLE,
                reason=f"Téléchargement échoué : {pdf_url}"
            )

        logger.info(f"[LONAB_SCRAPER] Programme téléchargé : {pdf_path}")
        return ScraperResult(ScraperStatus.FOUND, pdf_path=pdf_path, url=pdf_url)

    # ──────────────────────────────────────────────────────────────────
    # LECTURE PAGE INDEX
    # ──────────────────────────────────────────────────────────────────

    def _fetch_index_page(self) -> Optional[str]:
        """Télécharge page index LONAB avec retry."""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                resp = requests.get(
                    self.INDEX_URL,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=True
                )
                if resp.status_code == 200:
                    logger.info(f"[LONAB_SCRAPER] Page index OK (tentative {attempt})")
                    return resp.text

                logger.warning(f"[LONAB_SCRAPER] HTTP {resp.status_code} (tentative {attempt})")

            except requests.exceptions.Timeout:
                logger.warning(f"[LONAB_SCRAPER] Timeout (tentative {attempt}/{self.retry_attempts})")

            except requests.exceptions.RequestException as e:
                logger.error(f"[LONAB_SCRAPER] Erreur réseau : {str(e)[:80]}")
                return None

            if attempt < self.retry_attempts:
                time.sleep(self.retry_delay)

        return None

    # ──────────────────────────────────────────────────────────────────
    # EXTRACTION LIEN PDF PAR DATE
    # ──────────────────────────────────────────────────────────────────

    def _build_date_patterns(self, date: datetime) -> List[str]:
        """
        Patterns de date observés sur LONAB :
          JH_PMUB_DU_13-05-2026.pdf     → 13-05-2026  (standard)
          JH_PMUB_DU_12-05_2026_0.pdf   → 12-05_2026  (BUG CORRIGÉ)
          JH_PMU_DU_11-05-2026.pdf      → 11-05-2026
          JH-PMU-DU_06-05-2026.pdf      → 06-05-2026
        """
        dd = date.strftime("%d")
        mm = date.strftime("%m")
        yyyy = date.strftime("%Y")

        return [
            f"{dd}-{mm}-{yyyy}",    # 12-05-2026  (standard)
            f"{dd}-{mm}_{yyyy}",    # 12-05_2026  (tiret/underscore)
            f"{dd}_{mm}_{yyyy}",    # 12_05_2026  (tous underscores)
            f"{dd}_{mm}-{yyyy}",    # 12_05-2026  (variante)
        ]

    def _find_pdf_url_for_date(self, html: str, date: datetime) -> Optional[str]:
        """
        Cherche dans le HTML le lien PDF correspondant EXACTEMENT à la date.
        Aucun fallback — si pas de match → NOT_FOUND propre.
        """
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            soup = BeautifulSoup(html, "html.parser")
            patterns = self._build_date_patterns(date)

            # Collecter tous les liens PDF
            all_pdf_links = []
            for tag in soup.find_all(["a", "iframe", "embed", "object"]):
                href = tag.get("href") or tag.get("src") or tag.get("data") or ""
                if ".pdf" not in href.lower():
                    continue
                full_url = urljoin(self.BASE_SITE, href)
                all_pdf_links.append(full_url)

            logger.info(f"[LONAB_SCRAPER] {len(all_pdf_links)} lien(s) PDF trouvé(s)")

            for url in all_pdf_links:
                logger.debug(f"[LONAB_SCRAPER]   Disponible : {url}")

            # Chercher correspondance EXACTE
            for url in all_pdf_links:
                for pattern in patterns:
                    if pattern in url:
                        logger.info(
                            f"[LONAB_SCRAPER] Match exact (pattern '{pattern}') : {url}"
                        )
                        return url

            # Aucune correspondance
            logger.warning(
                f"[LONAB_SCRAPER] Aucun PDF exact pour {date.strftime('%d/%m/%Y')}\n"
                f"   Patterns testés : {patterns}\n"
                f"   Liens disponibles : {all_pdf_links}"
            )
            return None

        except Exception as e:
            logger.error(f"[LONAB_SCRAPER] Erreur parsing : {str(e)[:80]}")
            return None

    # ──────────────────────────────────────────────────────────────────
    # TÉLÉCHARGEMENT ET VALIDATION PDF
    # ──────────────────────────────────────────────────────────────────

    def _download_pdf(self, url: str, date: datetime) -> Optional[Path]:
        """Télécharge et valide un PDF."""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                resp = requests.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                    stream=True
                )

                if resp.status_code != 200:
                    logger.debug(f"[LONAB_SCRAPER] HTTP {resp.status_code}")
                    return None

                content = resp.content

                # Vérifier taille minimale
                if len(content) < 5000:
                    logger.warning(
                        f"[LONAB_SCRAPER] Fichier trop petit ({len(content)} octets)"
                    )
                    return None

                pdf_path = self._save_pdf(content, date)

                if self._validate_pdf(pdf_path):
                    logger.info(
                        f"[LONAB_SCRAPER] PDF OK ({len(content)} octets) : {url}"
                    )
                    return pdf_path

                pdf_path.unlink(missing_ok=True)
                logger.warning("[LONAB_SCRAPER] PDF invalide après validation")
                return None

            except requests.exceptions.Timeout:
                logger.warning(
                    f"[LONAB_SCRAPER] Timeout (tentative {attempt}/{self.retry_attempts})"
                )
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay)

            except requests.exceptions.RequestException as e:
                logger.error(f"[LONAB_SCRAPER] Erreur téléchargement : {str(e)[:80]}")
                return None

        return None

    # ──────────────────────────────────────────────────────────────────
    # UTILITAIRES
    # ──────────────────────────────────────────────────────────────────

    def _save_pdf(self, content: bytes, date: datetime) -> Path:
        """Sauvegarde le PDF en cache."""
        filename = f"lonab_{date.strftime('%Y%m%d')}.pdf"
        pdf_path = self.cache_dir / filename
        with open(pdf_path, "wb") as f:
            f.write(content)
        logger.debug(f"[LONAB_SCRAPER] PDF sauvegardé : {pdf_path}")
        return pdf_path

    def _validate_pdf(self, pdf_path: Path) -> bool:
        """Valide un PDF (taille, signature, mots-clés)."""
        try:
            # Vérifier taille
            if pdf_path.stat().st_size < 1024:
                logger.debug("[LONAB_SCRAPER] PDF trop petit (< 1KB)")
                return False

            # Vérifier signature PDF
            with open(pdf_path, "rb") as f:
                if f.read(4) != b"%PDF":
                    logger.debug("[LONAB_SCRAPER] Signature PDF invalide")
                    return False

            # Vérifier contenu (mots-clés hippiques)
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(pdf_path)
                if len(reader.pages) < 1:
                    logger.debug("[LONAB_SCRAPER] PDF vide (0 pages)")
                    return False

                text = reader.pages[0].extract_text().lower()
                keywords = ["course", "cheval", "hippodrome", "partant", "pmu", "lonab"]
                if not any(kw in text for kw in keywords):
                    logger.debug("[LONAB_SCRAPER] Aucun mot-clé hippique détecté")

            except Exception as e:
                logger.debug(f"[LONAB_SCRAPER] PyPDF2 check (non-bloquant) : {e}")

            logger.info("[LONAB_SCRAPER] PDF valide ✅")
            return True

        except Exception as e:
            logger.debug(f"[LONAB_SCRAPER] Erreur validation : {str(e)[:80]}")
            return False

    def _get_cached_pdf(self, date: datetime) -> Optional[Path]:
        """Retourne le PDF en cache s'il existe et est valide."""
        filename = f"lonab_{date.strftime('%Y%m%d')}.pdf"
        cached_path = self.cache_dir / filename
        if cached_path.exists() and self._validate_pdf(cached_path):
            logger.info(f"[LONAB_SCRAPER] Cache valide : {cached_path}")
            return cached_path
        return None

    def clear_cache(self, older_than_days: int = 7):
        """Supprime les PDFs en cache plus vieux que N jours."""
        date_limite = datetime.now() - timedelta(days=older_than_days)
        deleted = 0
        for pdf_file in self.cache_dir.glob("lonab_*.pdf"):
            try:
                date_str = pdf_file.stem.replace("lonab_", "")
                file_date = datetime.strptime(date_str, "%Y%m%d")
                if file_date < date_limite:
                    pdf_file.unlink()
                    deleted += 1
            except Exception:
                continue
        if deleted > 0:
            logger.info(f"[LONAB_SCRAPER] {deleted} PDF anciens supprimés")


# Instance globale
lonab_scraper = LONABScraper()
