import {describe, expect, it} from 'vitest';
import {reportText} from './reportText';

describe('readable report prose', () => {
  it('turns embedded agent commands into the same sentences as the action log', () => {
    const raw = '02:19:40 A2 set_bed_untrusted: Bed B10 marked UNTRUSTED (TAMPERING (conf 0.98)); device stays connected until the attack holds 20 s (at once on BOTH)\n02:20:05 A2 disable_client: Cut off MON-10 at the hub after TAMPERING (conf 0.98, held 25 s); session wiped';
    expect(reportText(raw, 'B10', 'MON-10')).toBe('02:19:40 Network agent: Marked readings as not trusted. Monitor may be hacked.\n02:20:05 Network agent: Cut off MON-10 at the hub. Monitor may be hacked.');
  });
  it('names evidence in words and preserves the complete fingerprint', () => {
    const hash = 'a'.repeat(64);
    expect(reportText(`messages.jsonl · SHA-256 ${hash}`, 'B10', 'MON-10')).toBe(`Signal record · SHA-256 ${hash}`);
  });
});
