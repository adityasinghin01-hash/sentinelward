import {humanText} from '../ui';

/** Presentation only: the complete received text remains in each record's Details. */
export function plainEvidence(text: string): string {
  return humanText(text)
    .replace(/\bBOTH\b/g, 'emergency on an attacked monitor')
    .replace(/\b(?:TAMPERING|DEVICE_ATTACK)\b/g, 'suspected monitor tampering')
    .replace(/\bEMERGENCY\b/g, 'emergency')
    .replace(/\bUNSURE\b/g, 'check by hand')
    .replace(/\bNORMAL\b/g, 'normal')
    .replace(/\bUNTRUSTED\b/g, 'not trusted')
    .replace(/\bLOOSE_SENSOR\b/g, 'loose sensor')
    .replace(/\bDRIFTING\b/g, 'sensor drift')
    .replace(/\bM[1-6]\b/g, code => ({M1:'sensor check',M2:'emergency check',M3:'body check',M4:'replay check',M5:'network check',M6:'drift check'}[code] ?? code))
    .replace(/\bS\d+\s*·?\s*/g, '')
    .replace(/\b(?:rp|tk|cmd)_[a-z0-9]+\b/gi, 'record')
    .replace(/\bconf(?:idence)?\s+[01](?:\.\d+)?\s*,?\s*/gi, '')
    .replace(/\btelegram\b/gi, 'notification')
    .replace(/\s*->\s*/g, ' → ');
}
