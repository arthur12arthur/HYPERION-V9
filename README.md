# HYPERION AI STUDIO — BLUEPRINT V9.4 FINAL
**Version :** 2.4 Final | **Statut :** Opérationnel | **Marché :** LONAB / Burkina Faso
**Stack :** Python · Gemini Flash · Firebase · GitHub Actions · Telegram
**Quota Gemini : 2 clés × 24 = 48 RPD | Utilisation réelle : 2-3 appels/jour**
**Courses analysées : 10/jour | Test : 300 prédictions sur 30 jours**

---

## SECTION 0 — RAPPEL FONDAMENTAL

LONAB = opérateur de paris agréé au Burkina Faso.
Sélectionne 1 course française (PMU) par jour pour le marché local.
Publie le journal hippique officiel chaque matin.
Les parieurs burkinabè misent via LONAB sur cette course française.

**Règle absolue :** La course LONAB du jour figure TOUJOURS parmi les 10 courses
analysées — position 1. Si LONAB est inaccessible, une course PMU la remplace
et l'Agent I alerte immédiatement. Le pipeline ne s'arrête jamais pour LONAB.

---

## SECTION 1 — BUDGET GEMINI V9.4

### Deux clés, rotation automatique

```
Clé 1 (PRINCIPALE)   → utilisée en priorité absolue
Clé 2 (RÉSERVE)      → bascule automatique si Clé 1 KO ou épuisée
Budget total          → 48 requêtes/jour
Utilisation réelle    → 2-3 appels/jour
Réserve effective     → 45-46 appels (erreurs, retries, imprévus)
```

### Système de rotation

```python
class GeminiKeyRotator:
    """
    Gestionnaire de rotation automatique des clés Gemini.
    Transparent pour tous les agents — ils appellent call_gemini()
    sans savoir quelle clé est active.
    """

    def __init__(self):
        self.keys = [
            {"id": "KEY1", "value": os.getenv("GEMINI_API_KEY_1"), "calls": 0, "active": True},
            {"id": "KEY2", "value": os.getenv("GEMINI_API_KEY_2"), "calls": 0, "active": True},
        ]
        self.current = 0  # index clé active

    def call_gemini(self, prompt: str, **kwargs) -> str:
        """
        Appel Gemini avec rotation automatique.
        Essaie la clé active, bascule si nécessaire.
        """
        for attempt in range(len(self.keys)):
            key = self.keys[self.current]

            if not key["active"]:
                self._switch_key("Clé désactivée")
                continue

            try:
                response = self._do_call(key["value"], prompt, **kwargs)
                key["calls"] += 1
                self._save_usage_to_firebase()
                return response

            except QuotaExceededError:
                monitor.alert(f"⚠️ {key['id']} quota épuisé → bascule")
                key["active"] = False
                self._switch_key("Quota épuisé")

            except APIError as e:
                monitor.alert(f"⚠️ {key['id']} erreur API: {e} → bascule")
                self._switch_key("Erreur API")

        # Les deux clés KO → mode template statique
        monitor.alert_telegram(
            "🔴 Les deux clés Gemini sont KO\n"
            "Mode template statique activé\n"
            "Rapports narratifs désactivés temporairement"
        )
        raise AllKeysExhaustedError()

    def _switch_key(self, reason: str):
        previous = self.keys[self.current]["id"]
        self.current = (self.current + 1) % len(self.keys)
        next_key = self.keys[self.current]["id"]
        monitor.log("KEY_ROTATION", f"{previous} → {next_key} ({reason})")
        monitor.alert_telegram(
            f"🔄 Rotation clé Gemini\n"
            f"Clé précédente : {previous} ({reason})\n"
            f"Clé active : {next_key}"
        )

    def reset_daily(self):
        """Appelé chaque jour à minuit — reset du quota."""
        for key in self.keys:
            key["calls"] = 0
            key["active"] = True
        monitor.log("QUOTA_RESET", "Les deux clés réinitialisées")
```

### Tableau de bord quota Firebase

```json
{
  "date": "2025-01-15",
  "key1": {
    "calls_used": 2,
    "calls_budget": 24,
    "active": true,
    "last_error": null
  },
  "key2": {
    "calls_used": 0,
    "calls_budget": 24,
    "active": true,
    "last_error": null
  },
  "total_calls_used": 2,
  "total_budget": 48,
  "active_key": "KEY1",
  "rotations_today": 0
}
```

### Utilisation Gemini par tâche

```
TÂCHE                          APPELS   MÉTHODE
─────────────────────────────  ──────   ──────────────────────────────
Extraction journal LONAB       0-1      Scraping HTML/PDF en priorité
                                        Gemini Vision si PDF scanné
Enrichissement ×10 courses     0        Scraping pur (PMU.fr, Paris-Turf...)
Résultats officiels soir       0        Scraping pmu.fr/resultats (1 requête)
Rapport narratif batch ×10     1        1 seul prompt pour les 10 courses
Rapport évaluation soir        1        1 prompt synthèse + running score
─────────────────────────────  ──────   ──────────────────────────────
TOTAL NORMAL                   2
TOTAL AVEC PDF SCANNÉ          3
BUDGET DISPONIBLE              48
RÉSERVE                        45-46
```

---

## SECTION 2 — GESTION DES 10 COURSES

### Sélection quotidienne

```
Course 1   → Course officielle LONAB du jour (OBLIGATOIRE)
             Source : lonab.bf — programme officiel
             Si LONAB inaccessible → course PMU de remplacement
             + alerte Agent I immédiate (voir Section 3)

Courses 2-10 → Programme PMU complet du jour
               Sélection automatique par ordre chronologique
               (courses du matin en priorité)
               PMU publie 8 à 12 courses/jour en général
               Si PMU < 9 courses disponibles → analyser toutes
```

### Règle de sélection PMU

```python
def select_daily_courses(lonab_course, pmu_program) -> List[Course]:
    """
    Sélectionne les 10 courses du jour.
    """
    selected = []

    # Position 1 : Course LONAB (obligatoire)
    if lonab_course:
        selected.append(lonab_course)
    else:
        # LONAB inaccessible : remplacement + alerte (voir Section 3)
        replacement = pmu_program[0]
        replacement.is_lonab_replacement = True
        selected.append(replacement)

    # Positions 2-10 : courses PMU restantes
    pmu_others = [c for c in pmu_program if c.course_id != lonab_course.course_id]

    # Priorité : courses avec le plus de partants (données plus riches)
    pmu_sorted = sorted(pmu_others, key=lambda c: len(c.partants), reverse=True)

    selected.extend(pmu_sorted[:9])  # compléter jusqu'à 10

    monitor.log("COURSE_SELECTION", f"{len(selected)} courses sélectionnées")
    return selected[:10]
```

---

## SECTION 3 — FALLBACK LONAB (PIPELINE NE S'ARRÊTE JAMAIS)

```
LONAB inaccessible
      │
      ▼
Agent I → Alerte Telegram immédiate :
  "⚠️ LONAB inaccessible ce matin [DATE]
   Course officielle LONAB non identifiée.
   Remplacée par : [Hippodrome] — [Nom Course] (PMU)
   Le pipeline continue sur 10 courses PMU."
      │
      ▼
Course de remplacement marquée :
  is_lonab = false
  is_lonab_replacement = true
      │
      ▼
Pipeline continue normalement
      │
      ▼
Évaluation du soir :
  Course LONAB marquée "NON DISPONIBLE CE JOUR"
  Non comptabilisée dans le score J/30
  Firebase : lonab_available = false pour ce jour

Seul arrêt possible :
  Si PMU.fr est AUSSI inaccessible en même temps que LONAB
  → Aucune source de données disponible
  → Agent I alerte : "🔴 LONAB + PMU.fr inaccessibles — pipeline suspendu"
  → Retry automatique dans 30 minutes (×3)
  → Si toujours KO après 3 retries → arrêt propre + log
```

---

## SECTION 4 — ARCHITECTURE AGENTIQUE — 9 AGENTS

### Vue globale

```
MATIN (09h00)
══════════════════════════════════════════════════════

[A] Orchestrateur
     │
     ├──▶ [B] Identification LONAB + Extraction
     │         Cascade : HTML → PDF → Gemini Vision
     │         Fallback LONAB → remplacement PMU + alerte
     │
     ├──▶ [C] Enrichissement Externe (×10 courses, scraping pur)
     │
     ├──▶ [D] Moteur Analytique (Python pur, ×10 courses)
     │         D1 : Filtrage & Normalisation
     │         D2 : Scoring 5 critères
     │         D3 : Monte Carlo (10 000 sims × 5 variantes)
     │         D4 : Consensus Borda interne
     │
     ├──▶ [E] Fusion & Décision (Python pur)
     │         E1 : Consensus Borda externe
     │         E2 : Méta-fusion (classement interne + confiance externe)
     │         E3 : Tie-break pairwise
     │
     ├──▶ [F] Risque & Finance (Python pur)
     │         F1 : HADES (mode observation pendant 30 jours)
     │         F2 : EV/Kelly
     │
     ├──▶ [G] Reporting (1 appel Gemini batch pour 10 courses)
     │         Fallback : template statique si Gemini KO
     │
     └──▶ [I] Monitoring & Feedback
               Rapport santé pipeline + alertes temps réel

SOIR (20h00)
══════════════════════════════════════════════════════

[H] Auto-Évaluation (scraping résultats + 1 appel Gemini)
     Résultats officiels → comparaison → score J/30
     Rapport Telegram soir

[I] Monitoring → Bilan complet du cycle journalier
```

---

## SECTION 5 — MOTEUR ANALYTIQUE DÉTAILLÉ (AGENT D)

### D1 — Filtrage & Normalisation

```python
Opérations :
  1. Supprimer non-partants (declared_non_runner = true)
  2. Rejeter Runner avec cote_officielle <= 0
  3. Dédupliquer par numero
  4. Parser forme_brute → forme_parsed ("1a 2a 3a" → [1, 2, 3])
  5. Normaliser poids (référence 58.0 kg)
  6. Valider schéma S003 (mode STRICT)

Entrée  : List[Runner bruts] (S003 non validé)
Sortie  : List[Runner validés] (S003 strict)
```

### D2 — Scoring Multicritères

```
score_global = (
    score_historique  × 0.35  +  # performances passées
    score_forme       × 0.25  +  # tendance récente
    score_terrain     × 0.20  +  # adéquation distance/type
    score_handicap    × 0.10  +  # avantage/désavantage poids
    score_fraicheur   × 0.10     # repos depuis dernière course
)

Entrée  : List[Runner validés] (S003)
Sortie  : List[ScoredRunner] (S004)
```

### D3 — Monte Carlo

```
10 000 simulations × 5 variantes (seeds 42-46)
= 50 000 simulations totales par course

Chaque simulation :
  1. Perturber les poids (bruit gaussien σ=0.15)
  2. Recalculer score_global
  3. Classer les chevaux

Résultat par cheval :
  win_prob   = nb fois 1er / 10 000
  place_prob = nb fois top 2 / 10 000
  top3_prob  = nb fois top 3 / 10 000

Sortie : MonteCarloResult (S005) × 5 variantes
```

### D4 — Consensus Borda Interne

```
Méthode Borda sur les 5 variantes Monte Carlo :
  Position 1 → N-1 points
  Position 2 → N-2 points
  ...

Seuil robustesse : 80%
  robuste = true  → classement fiable
  robuste = false → avertissement dans le rapport

Sortie : InternalConsensus (S006)
```

---

## SECTION 6 — MÉTA-FUSION V9.4 (SYSTÈME DÉFINITIF)

```
PRINCIPE FONDAMENTAL :
  Le CLASSEMENT = consensus interne (Monte Carlo + Borda) UNIQUEMENT
  L'externe MODIFIE UNIQUEMENT le score de confiance (étoiles)
  L'externe ne peut JAMAIS changer l'ordre des chevaux
```

```python
def meta_fusion(internal: InternalConsensus,
                external: ExternalConsensus) -> TopPrediction:

    classement_final = internal.consensus_borda  # IMMUABLE

    for position, numero in enumerate(classement_final[:5], 1):

        mc_result      = get_mc_result(numero)
        confiance_base = mc_result.win_prob

        # Modification de la confiance selon l'externe
        if external.qualite == "INDISPONIBLE":
            confiance_finale = confiance_base
            signal           = "🔵 Analyse interne seule"

        else:
            diff = external.get_rank(numero) - position

            if diff <= 0:
                confiance_finale = min(1.0, confiance_base + 0.10)
                signal           = "✅ Confirmé externe"
            elif diff <= 2:
                confiance_finale = confiance_base - 0.05
                signal           = "🟡 Légère divergence externe"
            else:
                confiance_finale = confiance_base - 0.10
                signal           = "⚠️ Divergence forte externe"

        # Étoiles Telegram
        stars = "⭐⭐⭐" if confiance_finale >= 0.80 else \
                "⭐⭐"  if confiance_finale >= 0.60 else "⭐"
```

---

## SECTION 7 — HADES EN MODE TEST

```
MODE TEST (J1 → J30) :
  ✅ HADES analyse et logge toutes les anomalies
  ✅ HADES affiche ses alertes dans le rapport Telegram
  ❌ HADES ne bloque PAS les recommandations de mise
  ❌ HADES ne modifie PAS le classement

  Toutes les alertes sauvegardées dans Firebase :
  collection hades_analysis → corrélation évaluée à J+30

MODE PRODUCTION (après J+30) :
  Si corrélation alertes ↔ mauvaises prédictions validée
  → HADES bloque les mises (pas les prédictions)
```

---

## SECTION 8 — SYSTÈMES DE SECOURS COMPLETS

### Cascade par composant

```
LONAB inaccessible
  → Course PMU de remplacement + alerte Agent I
  → Jamais d'arrêt pour cause LONAB seul

PMU.fr inaccessible
  → Données journal LONAB seules (suffisantes)
  → ExternalConsensus vide → classement interne seul

Sources externes (Paris-Turf, Equidia...) KO
  → ExternalConsensus vide
  → Confiance neutre (ni augmentée ni réduite)

Gemini Clé 1 épuisée/KO
  → Rotation automatique sur Clé 2 + alerte Telegram

Gemini Clé 2 aussi KO
  → Template statique activé
  → Rapport structuré sans narration

Firebase KO
  → Sauvegarde JSON locale dans GitHub Actions runner
  → Données envoyées sur Telegram comme backup

Telegram KO
  → Retry ×3 (30s, 60s, 90s)
  → Tentative en texte brut (sans MarkdownV2)
  → Log local si tout échoue

Résultats PMU soir indisponibles
  → Retry ×3 à +2h, +4h, +6h
  → Si toujours KO : évaluation reportée au lendemain + alerte

LONAB + PMU.fr inaccessibles simultanément
  → Seul cas d'arrêt réel du pipeline
  → Retry ×3 toutes les 30 minutes
  → Alerte Telegram : "🔴 Sources indisponibles — pipeline suspendu"
```

---

## SECTION 9 — AGENT I — MONITORING & FEEDBACK

### Rapport santé Telegram (après chaque pipeline)

```
🔧 *HYPERION V9 — Santé Pipeline*
📅 [DATE] | 🕘 [HEURE]
━━━━━━━━━━━━━━━━━━━━━━━
📌 Sources
  LONAB      : ✅ OK / ⚠️ Remplacée / ❌ KO
  PMU.fr     : ✅ OK / ❌ KO
  Paris-Turf : ✅ / ❌ | Equidia : ✅ / ❌

📊 Pipeline
  Extraction   : ✅ 10 courses identifiées
  Scoring      : ✅ 10/10 courses traitées
  Monte Carlo  : ✅ 500 000 sims | [X]s
  Fusion       : ✅ Top5 générés
  HADES        : 🟡 2 alertes jaunes loggées
  EV/Kelly     : ✅ 7 value bets détectés
  Rapport      : ✅ Envoyé (Clé Gemini 1)

🔑 Quota Gemini
  Clé 1 : 2/24 | Clé 2 : 0/24 | Total : 2/48

⏱ Durée totale : 3min 12s
━━━━━━━━━━━━━━━━━━━━━━━
```

---

## SECTION 10 — AGENT H — AUTO-ÉVALUATION (20h00)

### Message soir Telegram

```
📊 *ÉVALUATION J[N]/30* — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━
✅ *RÉSULTATS OFFICIELS*

⭐ Course LONAB :
  Prédit #1 : [NOM] → ✅ CORRECT / ❌ Réel: [NOM]
  Top3 : [X]/3 corrects

📌 Autres courses (9) :
  Top1 correct : [N]/9
  Top3 correct : [N]/27

━━━━━━━━━━━━━━━━━━━━━━━
📈 *SCORE DU JOUR*
  Top1 : [N]/10 ([X]%)
  Top3 : [N]/30 ([X]%)

🎯 *SCORE CUMULÉ J[N]/30*
  Top1 global : [X]%
  Top3 global : [X]%
  Tendance : 📈 / 📉
  LONAB précision : [X]%
━━━━━━━━━━━━━━━━━━━━━━━
```

---

## SECTION 11 — FIREBASE — 5 COLLECTIONS

```
predictions/     → prédictions du matin (10 par jour)
results/         → résultats officiels du soir
evaluations/     → scores quotidiens J1→J30
pipeline_runs/   → logs techniques de chaque run
gemini_quota/    → suivi quota clés 1 et 2
hades_analysis/  → alertes HADES + corrélation à J+30
```

---

## SECTION 12 — GITHUB SECRETS REQUIS

```
GEMINI_API_KEY_1        → Clé Gemini principale
GEMINI_API_KEY_2        → Clé Gemini de réserve
FIREBASE_CREDENTIALS    → JSON credentials Firebase
TELEGRAM_BOT_TOKEN      → Token bot Telegram
TELEGRAM_CHAT_ID        → ID du canal/chat
```

---

## SECTION 13 — ARBORESCENCE PROJET FINALE

```
hyperion-v9/
│
├── config/
│   ├── app.yaml               # timezone Africa/Ouagadougou, 10 courses
│   ├── scoring.yaml           # poids 5 critères
│   ├── sources.yaml           # LONAB + 4 sources PMU
│   ├── gemini.yaml            # 2 clés, quota 48 RPD, modèle flash
│   ├── hades.yaml             # seuils, mode_test: true
│   ├── finance.yaml           # kelly 0.25, cap 5%
│   └── prompts/
│       ├── extraction.txt
│       ├── reporting_batch.txt   # batch 10 courses
│       └── evaluation.txt
│
├── domain/
│   └── schemas.py             # S001–S033
│
├── utils/
│   ├── config.py
│   ├── logger.py
│   ├── validators.py
│   ├── helpers.py
│   └── quota_manager.py       # GeminiKeyRotator — rotation 2 clés
│
├── data/
│   ├── lonab_adapter.py       # HTML → PDF → Gemini + fallback PMU
│   ├── pmu_adapter.py         # partants + cotes PMU.fr
│   ├── web_scraper.py         # Paris-Turf, Equidia, Zone-Turf
│   ├── results_fetcher.py     # 1 requête → tous résultats du jour
│   ├── fusion_engine.py
│   └── data_merger.py
│
├── analytics/
│   ├── d1_normalizer.py
│   ├── d2_scorer.py
│   ├── d3_monte_carlo.py      # 50 000 sims par course
│   ├── d4_consensus.py        # Borda interne
│   ├── e1_ext_consensus.py    # Borda externe
│   ├── e2_meta_fusion.py      # classement interne + confiance externe
│   └── e3_tiebreak.py
│
├── risk/
│   ├── f1_hades.py            # mode_test=true
│   ├── f2_ev_kelly.py
│   └── risk_manager.py
│
├── output/
│   ├── report_generator.py    # batch 10 courses = 1 appel Gemini
│   ├── static_template.py     # fallback sans Gemini
│   ├── telegram_bot.py        # retry ×3 + texte brut fallback
│   └── evaluation_report.py
│
├── monitoring/
│   ├── pipeline_monitor.py
│   ├── health_reporter.py
│   └── alert_sender.py
│
├── evaluation/
│   ├── auto_evaluator.py
│   ├── score_tracker.py
│   └── daily_report.py
│
├── orchestration/
│   ├── pipeline.py
│   ├── orchestrator.py
│   ├── state_machine.py
│   └── run_manager.py
│
├── infrastructure/
│   ├── firebase_manager.py
│   ├── cache.py
│   └── storage.py
│
├── backup/
│   ├── predictions/           # JSON si Firebase KO
│   ├── results/
│   └── logs/
│
├── tests/
│   ├── test_d2_scorer.py
│   ├── test_d3_monte_carlo.py
│   ├── test_e2_meta_fusion.py
│   ├── test_f1_hades.py
│   ├── test_fallbacks.py
│   ├── test_key_rotation.py   # tests rotation clés Gemini
│   └── test_pipeline_integration.py
│
├── scripts/
│   ├── run_morning.py         # entrée 09h00
│   └── run_evening.py         # entrée 20h00
│
├── .github/
│   └── workflows/
│       ├── morning_pipeline.yml    # cron '0 9 * * *'
│       └── evening_evaluation.yml  # cron '0 20 * * *'
│
└── requirements.txt
```

---

## SECTION 14 — PLAN DE CONSTRUCTION 8 PHASES

```
Phase 1 — Socle + Quota Manager    (J1-J2)
  config, logger, validators
  GeminiKeyRotator (rotation 2 clés)
  Firebase + backup local
  Telegram bot + retry
  GitHub repo + 5 secrets configurés

Phase 2 — Domain models            (J3-J4)
  schemas.py S001–S033
  Tests de validation

Phase 3 — Extraction cascade       (J5-J6)
  lonab_adapter (HTML→PDF→Gemini + fallback PMU)
  pmu_adapter (scraping 10 courses)
  web_scraper, results_fetcher

Phase 4 — Cœur analytique          (J7-J10)
  d1 → d2 → d3 → d4 → e1 → e2 → e3
  Tests unitaires pour chaque module

Phase 5 — Risque & Finance         (J11-J12)
  f1_hades (mode_test=true)
  f2_ev_kelly, risk_manager

Phase 6 — Output & Delivery        (J13-J14)
  report_generator (batch 10 courses)
  static_template, telegram_bot

Phase 7 — Monitoring + Évaluation  (J15-J17)
  Agent I complet
  Agent H complet
  Rapport soir Telegram

Phase 8 — Orchestration + Launch   (J18-J21)
  pipeline, state_machine, orchestrator
  Tests d'intégration complets
  GitHub Actions activé (morning + evening)
  ✅ LANCEMENT TEST 30 JOURS
  300 prédictions × scoring automatique
```

---

## SECTION 15 — MÉTRIQUES DE SUCCÈS À J+30

```
Seuil minimum acceptable :
  Top1 correct ≥ 25%   (mieux que le hasard sur ~10 partants)
  Top3 correct ≥ 55%
  LONAB Top1  ≥ 30%   (course principale — seuil plus exigeant)

Seuil bon système :
  Top1 correct ≥ 35%
  Top3 correct ≥ 65%

Seuil excellent :
  Top1 correct ≥ 45%
  Top3 correct ≥ 75%

Analyse complémentaire à J+30 :
  Corrélation HADES alertes ↔ erreurs prédiction
  Valeur ajoutée réelle du consensus externe
  Hippodromes/types de course les mieux prédits
  Décision : ouvrir au marché / ajuster / continuer le test
```

---

## SECTION 16 — DISCLAIMER OBLIGATOIRE

> À inclure dans chaque rapport Telegram et system prompt Agent F.

```
⚠️ HYPERION AI STUDIO est un outil d'analyse statistique et de probabilités.
Il ne garantit en aucun cas un gain financier.
Les paris hippiques comportent des risques financiers.
Jouer comporte des risques — contactez le service d'assistance
aux joueurs de votre pays en cas de besoin.
```

---

*HYPERION AI STUDIO V9.4 FINAL*
*9 Agents | 33 Schémas | 2-3 appels Gemini/jour | 48 RPD disponibles*
*10 courses/jour | 300 prédictions test | Stack 100% Gratuit*
*Gemini Flash × 2 clés · Firebase Firestore · GitHub Actions · Telegram*
