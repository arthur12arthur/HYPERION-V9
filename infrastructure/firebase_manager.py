"""
HYPERION V9 — Firebase Manager
CRUD complet sur les 6 collections Firestore.
Fallback JSON local si Firebase est KO.
"""
import json
import os
from typing import Optional, Dict, List
from utils.logger import get_logger
from utils.helpers import today_str, now_iso, generate_doc_id

logger = get_logger(__name__)

BACKUP_DIR = "./backup"


class FirebaseManager:
    """
    Gère toutes les opérations Firestore.
    Initialisation lazy — Firebase n'est connecté qu'au premier appel.
    """

    def __init__(self):
        self._db    = None
        self._ready = False

    def _init(self):
        """Initialise Firebase (lazy — une seule fois)."""
        if self._ready:
            return True
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            # Credentials depuis variable d'environnement (JSON string)
            cred_json = os.getenv("FIREBASE_CREDENTIALS")
            if not cred_json:
                logger.warning("[FIREBASE] FIREBASE_CREDENTIALS non configuré")
                return False

            # Éviter la double initialisation
            if not firebase_admin._apps:
                cred = credentials.Certificate(json.loads(cred_json))
                firebase_admin.initialize_app(cred)

            self._db    = firestore.client()
            self._ready = True
            logger.info("[FIREBASE] Connexion établie ✅")
            return True

        except Exception as e:
            logger.error(f"[FIREBASE] Init failed: {e}")
            return False

    # ──────────────────────────────────────────────────────────────
    # PRÉDICTIONS
    # ──────────────────────────────────────────────────────────────
    def save_prediction(self, date_str: str, course_id: str, data: dict):
        """Sauvegarde une prédiction."""
        doc_id = generate_doc_id(date_str, course_id)
        self._set("predictions", doc_id, {
            **data,
            "date"      : date_str,
            "course_id" : course_id,
            "timestamp" : now_iso()
        })

    def get_predictions_for_date(self, date_str: str) -> Dict[str, dict]:
        """Retourne toutes les prédictions d'une date."""
        if not self._init():
            return self._load_backup("predictions", date_str)

        try:
            docs = (
                self._db.collection("predictions")
                .where("date", "==", date_str)
                .stream()
            )
            return {doc.id.split("_", 1)[-1]: doc.to_dict() for doc in docs}
        except Exception as e:
            logger.error(f"[FIREBASE] get_predictions error: {e}")
            return self._load_backup("predictions", date_str)

    # ──────────────────────────────────────────────────────────────
    # RÉSULTATS
    # ──────────────────────────────────────────────────────────────
    def save_results(self, date_str: str, results: Dict[str, dict]):
        """Sauvegarde les résultats officiels du soir."""
        for course_id, result in results.items():
            doc_id = generate_doc_id(date_str, course_id)
            self._set("results", doc_id, {
                **result,
                "date"      : date_str,
                "course_id" : course_id,
                "timestamp" : now_iso()
            })

    # ──────────────────────────────────────────────────────────────
    # ÉVALUATIONS
    # ──────────────────────────────────────────────────────────────
    def save_evaluation(self, date_str: str, eval_report):
        """Sauvegarde le rapport d'évaluation quotidien."""
        data = eval_report.dict() if hasattr(eval_report, "dict") else eval_report
        self._set("evaluations", date_str, {
            **data,
            "timestamp": now_iso()
        })

    def get_day_number(self, date_str: str) -> int:
        """Retourne le numéro du jour dans le test (1-30)."""
        if not self._init():
            return 1
        try:
            docs = list(self._db.collection("evaluations").stream())
            return len(docs) + 1
        except Exception:
            return 1

    # ──────────────────────────────────────────────────────────────
    # SCORES CUMULÉS
    # ──────────────────────────────────────────────────────────────
    def get_running_scores(self) -> Optional[dict]:
        """Récupère les scores cumulés depuis Firebase."""
        if not self._init():
            return None
        try:
            doc = self._db.collection("running_scores").document("global").get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.warning(f"[FIREBASE] get_running_scores error: {e}")
            return None

    def save_running_scores(self, scores: dict):
        """Met à jour les scores cumulés."""
        self._set("running_scores", "global", scores)

    # ──────────────────────────────────────────────────────────────
    # QUOTA GEMINI
    # ──────────────────────────────────────────────────────────────
    def save_quota_status(self, quota: dict):
        """Sauvegarde le statut quota Gemini."""
        self._set("gemini_quota", today_str(), quota)

    # ──────────────────────────────────────────────────────────────
    # PIPELINE RUNS
    # ──────────────────────────────────────────────────────────────
    def save_pipeline_run(self, run_id: str, data: dict):
        """Sauvegarde le log d'un run pipeline."""
        self._set("pipeline_runs", run_id, {
            **data,
            "timestamp": now_iso()
        })

    # ──────────────────────────────────────────────────────────────
    # HADES ANALYSIS
    # ──────────────────────────────────────────────────────────────
    def save_hades_alert(self, date_str: str, course_id: str, hades_data: dict):
        """Sauvegarde une analyse HADES pour corrélation future."""
        doc_id = generate_doc_id(date_str, course_id)
        self._set("hades_analysis", doc_id, {
            **hades_data,
            "date"     : date_str,
            "course_id": course_id,
            "timestamp": now_iso()
        })

    # ──────────────────────────────────────────────────────────────
    # UTILITAIRES
    # ──────────────────────────────────────────────────────────────
    def _set(self, collection: str, doc_id: str, data: dict):
        """Écriture Firestore avec fallback JSON local."""
        # Convertir les objets non-sérialisables
        data = self._sanitize(data)

        # Tentative Firebase
        if self._init():
            try:
                self._db.collection(collection).document(doc_id).set(data)
                logger.debug(f"[FIREBASE] {collection}/{doc_id} sauvegardé")
                return
            except Exception as e:
                logger.warning(f"[FIREBASE] Write error {collection}/{doc_id}: {e}")

        # Fallback JSON local
        self._save_backup(collection, doc_id, data)

    def _save_backup(self, collection: str, doc_id: str, data: dict):
        """Sauvegarde en JSON local si Firebase est KO."""
        try:
            backup_path = os.path.join(BACKUP_DIR, collection)
            os.makedirs(backup_path, exist_ok=True)
            file_path = os.path.join(backup_path, f"{doc_id}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"[FIREBASE] Backup local: {file_path}")
        except Exception as e:
            logger.error(f"[FIREBASE] Backup local failed: {e}")

    def _load_backup(self, collection: str, date_str: str) -> dict:
        """Charge les données depuis le backup local."""
        try:
            backup_path = os.path.join(BACKUP_DIR, collection)
            if not os.path.exists(backup_path):
                return {}

            result = {}
            for filename in os.listdir(backup_path):
                if date_str in filename and filename.endswith(".json"):
                    with open(os.path.join(backup_path, filename)) as f:
                        data = json.load(f)
                    course_id = filename.replace(f"{date_str}_", "").replace(".json", "")
                    result[course_id] = data

            return result
        except Exception as e:
            logger.error(f"[FIREBASE] Load backup failed: {e}")
            return {}

    def _sanitize(self, data) -> dict:
        """Convertit les objets Pydantic et enums en types sérialisables."""
        if hasattr(data, "dict"):
            data = data.dict()
        if isinstance(data, dict):
            return {
                k: self._sanitize(v)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self._sanitize(i) for i in data]
        if hasattr(data, "value"):  # Enum
            return data.value
        return data


# Instance globale
firebase_manager = FirebaseManager()
