"""
Ascolta - voice call cost estimation.

maintainer, 20/08: "next step" dopo la demo - costi per chiamata, poi
aggregati in dashboard, propedeutico allo script di chiamate di prova
che vuole fare su Comune di Exampleville per capire quanto costa davvero
l'uso reale.

Tariffe pubbliche confermate (non supposte) - fonti in ogni costante
sotto. Solo xai_sip_direct e' coperto per ora: e' l'unico voice_engine
con dati di utilizzo (usage.billable_audio_seconds) gia' verificati
live contro l'API vera (vedi db_migrations/versions/
524f1b231172_*.py). openai_realtime/altri motori non hanno ancora
questo pezzo - meglio "N/D" che un numero inventato.
"""

from typing import Optional

# grok-voice-latest = alias di grok-voice-think-fast-2.0 dal 5/8/2026
# (fonte: bleap.finance/en-us/blog/all-about-grok-voice-think-fast-2-0),
# $0.08/min audio (fonte: docs.x.ai/docs/models). + $0.01/min quando il
# numero chiamante e' provisionato direttamente tramite xAI (non tramite
# un gateway SIP esterno come Zadarma) - fonte: aipricing.guru/xai-pricing.
# Le tool call (search_knowledge_base, calcom, ecc.) si fatturano a parte
# e non sono incluse qui - non abbiamo ancora dati di utilizzo per quelle.
XAI_VOICE_USD_PER_MINUTE = 0.08
XAI_TELEPHONY_SURCHARGE_USD_PER_MINUTE = 0.01


def estimate_xai_call_cost_usd(billable_audio_seconds: Optional[int]) -> Optional[float]:
    """
    Costo di una chiamata xai_sip_direct dai secondi audio fatturabili
    accumulati (somma di usage.billable_audio_seconds su ogni
    response.done della chiamata, vedi runtime_workers/
    realtime_service.py::run_call). None se non abbiamo il dato (es.
    chiamata mai arrivata a generare una risposta).
    """
    if billable_audio_seconds is None:
        return None
    minutes = billable_audio_seconds / 60
    rate = XAI_VOICE_USD_PER_MINUTE + XAI_TELEPHONY_SURCHARGE_USD_PER_MINUTE
    return round(minutes * rate, 4)
