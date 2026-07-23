from typing import Optional
from domain.schemas import InternalConsensus, TopPrediction

class MetaFusionEngine:
    @staticmethod
    def fuse(internal: InternalConsensus, external: Optional[dict]) -> TopPrediction:
        """
        E2 - Méta-fusion
        Combine le consensus interne avec les données externes pour ajuster la confiance.
        """
        # Le classement final est dicté par le consensus interne
        classement = internal.consensus_borda
        
        # Calcul de la confiance (étoiles)
        confiance_val = internal.confiance_interne
        if external:
            # Logique d'ajustement si données externes présentes
            pass
            
        stars = "⭐⭐⭐" if confiance_val >= 0.80 else "⭐⭐" if confiance_val >= 0.60 else "⭐"
        signal = "✅ Confirmé" if confiance_val >= 0.75 else "🟡 Prudence"
        
        return TopPrediction(
            course_id=internal.course_id,
            classement_final=classement,
            confiance_etoiles=stars,
            signal=signal
        )
