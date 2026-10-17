"""Approved first-match policy; numeric confidence and trust are uncalibrated."""
from sw_common import make_verdict


def decide(bed_id,window_start,now_ms,results,*,alarm=False,offline=False,last_trusted_ts=None,patient_not_ok=False,confirmed_low_pressure=False):
    values={m:r['score'] for m,r in results.items()}
    applicable=lambda m: not results[m].get('extra',{}).get('not_applicable',False)
    eligible=lambda m: applicable(m) and values[m] is not None and results[m].get('extra',{}).get('eligible',True)
    clean=lambda m: not applicable(m) or (eligible(m) and values[m]<.5)
    positive=lambda m: eligible(m) and values[m]>=.8
    trust=1-max([values[m] for m in ('M3','M4','M5') if eligible(m)] or [0.])
    emergency=alarm or patient_not_ok or confirmed_low_pressure or (eligible('M2') and results['M2'].get('extra',{}).get('positive',positive('M2')))
    tampering=(positive('M4') and results['M4'].get('extra',{}).get('independent_evidence',False)) or (positive('M3') and positive('M5')) or (positive('M6') and positive('M5'))
    tamper_model='M4' if positive('M4') and results['M4'].get('extra',{}).get('independent_evidence',False) else ('M3' if positive('M3') else 'M6')
    tamper_confidence=(values[tamper_model] if tamper_model=='M4' else min(values[tamper_model],values['M5'])) if tampering else None
    physiology=all(clean(m) for m in ('M1','M2','M3')) and not offline
    all_clean=all(clean(m) for m in values)
    reasons=[]
    if emergency:
        verdict='BOTH' if tampering else 'EMERGENCY'
        confidence=1. if alarm or patient_not_ok or confirmed_low_pressure else values['M2']
        reasons.append('Monitor alarm remains active' if alarm else ('Bedside nurse reports patient NOT OK' if patient_not_ok else ('Low arterial pressure confirmed by cuff' if confirmed_low_pressure else results['M2']['reason'])))
        if tampering: reasons.append(results[tamper_model]['reason'])
    elif tampering: verdict='TAMPERING'; confidence=tamper_confidence; reasons=[results[tamper_model]['reason']]
    elif positive('M6'): verdict='DRIFTING'; confidence=values['M6']; reasons=[results['M6']['reason']]
    elif positive('M1') and not positive('M2') and (eligible('M2') or (not applicable('M2') and eligible('M3'))) and all(eligible(m) and values[m]<.5 for m in ('M4','M5')) and (not positive('M3') or results['M1'].get('extra',{}).get('channels',{}).get('ppg',{}).get('score',1)<.5): verdict='LOOSE_SENSOR'; confidence=values['M1']; reasons=[results['M1']['reason']]
    elif positive('M5') and physiology: verdict='DEVICE_ATTACK'; confidence=values['M5']; reasons=[results['M5']['reason']]
    elif offline: verdict='UNSURE'; confidence=1.; reasons=['Monitor offline for at least 3 seconds; last values retained']
    elif not all_clean: verdict='UNSURE'; confidence=.5; reasons=['Some checks are unavailable, warming up or inconclusive']
    else: verdict='NORMAL'; confidence=1-max([values[m] for m in values if eligible(m)] or [0.]); reasons=['All applicable live checks are clear']
    if verdict=='NORMAL': last_trusted_ts=None
    return make_verdict(bed_id=bed_id,ts=now_ms,window_start=window_start,verdict=verdict,confidence=float(confidence),trust=float(trust),last_trusted_ts=last_trusted_ts,reasons=[s[:120] for s in reasons[:3]],scores=values)
