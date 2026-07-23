"""
HYPERION V9 — Firebase Manager
CRUD complet sur les 6 collections Firestore.
Fallback JSON local si Firebase est KO.
"""
import base64
import json
import os
from typing import Optional, Dict, List
from utils.logger import get_logger
from utils.helpers import today_str, now_iso, generate_doc_id

logger = get_logger(__name__)

BACKUP_DIR = "./backup"

# Champs obligatoires d'un service account Firebase valide, utilisés pour
# donner un diagnostic clair au lieu du message générique du SDK.
REQUIRED_SA_FIELDS = ["type", "project_id", "private_key", "client_email"]


class FirebaseManager:
    """
    Gère toutes les opérations Firestore.
    Initialisation lazy — Firebase n'est connecté qu'au premier appel.
    """

    def __init__(self):
        self._db    = None
        self._ready = False

    def _load_credentials_dict(self) -> Optional[dict]:
        """
        Charge et valide FIREBASE_CREDENTIALS.

        Accepte deux formats :
          1. Le JSON du service account tel quel (comportement d'origine).
          2. Le même JSON encodé en base64 (recommandé pour GitHub Actions :
             évite que les retours à la ligne du champ "private_key" soient
             corrompus lors de la saisie/copie du secret).

        Le message d'erreur "Certificate must contain a 'type' field..."
        du run précédent indique que json.loads() a réussi à parser un
        dict, mais qu'il lui manque les clés attendues d'un service
        account — typiquement un JSON tronqué ou mal collé dans le secret
        GitHub. Cette fonction le détecte explicitement au lieu de laisser
        le SDK Firebase lever une erreur peu informative.
        """
        raw = os.getenv("FIREBASE_CREDENTIALS")
        if not raw:
            logger.warning("[FIREBASE] FIREBASE_CREDENTIALS non configuré")
            return None

        raw = raw.strip()
        # Un secret parfois collé avec des guillemets englobants en trop
        if raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1].strip()
        if raw.startswith('"') and raw.endswith('"') and raw.count('"') == 2:
            raw = raw[1:-1].strip()

        cred_dict = None

        # Tentative 1 : JSON direct
        try:
            cred_dict = json.loads(raw)
        except json.JSONDecodeError:
            cred_dict = None

        # Tentative 2 : base64(JSON) — recommandé pour éviter les soucis de
        # multi-lignes dans les secrets GitHub Actions
        if cred_dict is None:
            try:
                decoded = base64.b64decode(raw).decode("utf-8")
                cred_dict = json.loads(decoded)
                logger.info("[FIREBASE] Secret décodé depuis base64")
            except Exception:
                cred_dict = None

        if cred_dict is None:
            logger.error(
                "[FIREBASE] FIREBASE_CREDENTIALS n'est ni un JSON valide ni un "
                "base64(JSON) valide — vérifier le contenu du secret GitHub."
            )
            return None

        if not isinstance(cred_dict, dict):
            logger.error(
                f"[FIREBASE] FIREBASE_CREDENTIALS décodé en {type(cred_dict).__name__}, "
                f"pas en objet JSON — secret probablement double-encodé."
            )
            return None

        missing = [f for f in REQUIRED_SA_FIELDS if f not in cred_dict]
        if missing:
            present = list(cred_dict.keys())
            logger.error(
                f"[FIREBASE] Champs manquants dans le service account : {missing}. "
                f"Champs présents : {present}. Le secret est probablement tronqué "
                f"ou incomplet — recopier le fichier JSON complet téléchargé "
                f"depuis la console Firebase (idéalement encodé en base64)."
            )
            return None

        return cred_dict

    def _init(self):
        """Initialise Firebase (lazy — une seule fois)."""
        if self._ready:
            return True
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            cred_dict = self._load_credentials_dict()
            if cred_dict is None:
                return False

            # Éviter la double initialisation
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_dict)
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
