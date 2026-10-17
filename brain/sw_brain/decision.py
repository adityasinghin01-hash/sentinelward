"""Approved first-match policy; numeric confidence and trust are uncalibrated."""
from sw_common import make_verdict

# Plain names so an UNSURE verdict says which check held it back.
CHECK_NAMES={'M1':'Sensor check','M2':'Emergency check','M3':'Body-match check','M4':'Replay check','M5':'Network check','M6':'Drift check'}
OFFLINE_REASON='Monitor offline for at least 3 seconds; last values retained; data trust 0'
OFFLINE_TRUST_REASON='Monitor offline for at least 3 seconds: data trust 0'
HELD_OFFLINE_REASON='Monitor offline for at least 3 seconds: data trust 0; earlier tampering evidence held'
HELD_EMERGENCY_PREFIX='Emergency held until a bedside check: '
HELD_REASON='Earlier tampering evidence held until 30 s of clean live data'


def _helpers(results):
    values={m:r['score'] for m,r in results.items()}
    applicable=lambda m: not results[m].get('extra',{}).get('not_applicable',False)
    eligible=lambda m: applicable(m) and values[m] is not None and results[m].get('extra',{}).get('eligible',True)
    positive=lambda m: eligible(m) and values[m]>=.8
    return values,applicable,eligible,positive


def tamper_evidence(results):
    """Live tampering evidence in this window as (reason, confidence), else None."""
    values,_,_,positive=_helpers(results)
    # Only a verified content-preserving transport event gets this exception.
    # M3 disagreement can predate a flood; it is not proof that dropped copies
    # changed the waveform. Conflicts, stale replays and combined impersonation
    # still reach M4's independent-evidence rule above the clinical branches.
    copies_only=results['M4'].get('extra',{}).get('duplicate_only',False)
    m4=positive('M4') and results['M4'].get('extra',{}).get('independent_evidence',False)
    if not (m4 or (not copies_only and positive('M3') and positive('M5')) or (not copies_only and positive('M6') and positive('M5'))):
        return None
    model='M4' if m4 else ('M3' if positive('M3') else 'M6')
    confidence=values[model] if model=='M4' else min(values[model],values['M5'])
    return results[model]['reason'],float(confidence)


def decide(bed_id,window_start,now_ms,results,*,alarm=False,offline=False,last_trusted_ts=None,patient_not_ok=False,confirmed_low_pressure=False,tamper_hold=None,emergency_hold=None):
    """tamper_hold: (reason, confidence) of tampering established earlier on this bed and still
    latched by the service; it applies only when this window has no live tampering evidence.
    emergency_hold: reason of an emergency seen on this bed while tampering was latched; it is
    held (never downgraded) until a bedside patient_ok or the latch is released."""
    values,applicable,eligible,positive=_helpers(results)
    clean=lambda m: not applicable(m) or (eligible(m) and values[m]<.5)
    trust=1-max([values[m] for m in ('M3','M4','M5') if eligible(m)] or [0.])
    emergency=alarm or patient_not_ok or confirmed_low_pressure or emergency_hold is not None or (eligible('M2') and results['M2'].get('extra',{}).get('positive',positive('M2')))
    copies_only=results['M4'].get('extra',{}).get('duplicate_only',False)
    evidence=tamper_evidence(results)
    held=evidence is None and tamper_hold is not None
    if held: evidence=tamper_hold
    tampering=evidence is not None
    physiology=all(clean(m) for m in ('M1','M2','M3')) and not offline
    all_clean=all(clean(m) for m in values)
    reasons=[]
    if emergency:
        verdict='BOTH' if tampering else 'EMERGENCY'
        model_emergency=eligible('M2') and results['M2'].get('extra',{}).get('positive',positive('M2'))
        confidence=values['M2'] if model_emergency and not (alarm or patient_not_ok or confirmed_low_pressure) else 1.
        reasons.append('Monitor alarm remains active' if alarm else ('Bedside nurse reports patient NOT OK' if patient_not_ok else ('Low arterial pressure confirmed by cuff' if confirmed_low_pressure else (results['M2']['reason'] if model_emergency else HELD_EMERGENCY_PREFIX+emergency_hold))))
        if tampering: reasons.append(evidence[0])
    elif tampering: verdict='TAMPERING'; confidence=evidence[1]; reasons=[evidence[0]]
    elif positive('M6'): verdict='DRIFTING'; confidence=values['M6']; reasons=[results['M6']['reason']]
    elif positive('M1') and not positive('M2') and (eligible('M2') or (not applicable('M2') and eligible('M3'))) and all(eligible(m) and values[m]<.5 for m in ('M4','M5')) and (not positive('M3') or results['M1'].get('extra',{}).get('channels',{}).get('ppg',{}).get('score',1)<.5): verdict='LOOSE_SENSOR'; confidence=values['M1']; reasons=[results['M1']['reason']]
    elif positive('M5') and (physiology or (copies_only and not offline)): verdict='DEVICE_ATTACK'; confidence=values['M5']; reasons=[results['M5']['reason']]
    elif offline: verdict='UNSURE'; confidence=1.; reasons=[OFFLINE_REASON]
    elif not all_clean:
        # Inconclusive checks (a score) first, then checks still waiting for data.
        blocking=sorted((m for m in values if not clean(m)),key=lambda m:(not eligible(m),m))
        verdict='UNSURE'; confidence=.5; reasons=[f"{CHECK_NAMES.get(m,m)}: {results[m]['reason']}" for m in blocking] or ['Some checks are unavailable, warming up or inconclusive']
    else: verdict='NORMAL'; confidence=1-max([values[m] for m in values if eligible(m)] or [0.]); reasons=['All applicable live checks are clear']
    if held:
        # Latched tampering: the monitor has not yet shown 30 s of clean live data.
        trust=0.
        reasons.append(HELD_OFFLINE_REASON if offline else HELD_REASON)
    elif offline:
        # A silent monitor cannot be trusted: no eligible check is not evidence of integrity.
        trust=0.
        if verdict!='UNSURE': reasons.append(OFFLINE_TRUST_REASON)
    if verdict=='NORMAL': last_trusted_ts=None
    return make_verdict(bed_id=bed_id,ts=now_ms,window_start=window_start,verdict=verdict,confidence=float(confidence),trust=float(trust),last_trusted_ts=last_trusted_ts,reasons=[s[:120] for s in reasons[:3]],scores=values)
