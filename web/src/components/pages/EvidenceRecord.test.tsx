import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {Fingerprint} from './EvidenceRecord';

afterEach(() => {cleanup(); vi.unstubAllGlobals();});
describe('evidence fingerprints', () => {
  it('shows and copies all 64 characters and resets feedback for a new fingerprint', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', {clipboard: {writeText}});
    const hash = 'abcdef0123456789'.repeat(4);
    const view = render(<Fingerprint value={hash} name="Signal record" />);
    expect(screen.getByText(hash)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Copy SHA-256 for Signal record'}));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(hash));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    view.rerender(<Fingerprint value={'1'.repeat(64)} name="Signal record" />);
    expect(screen.getByText('Copy')).toBeInTheDocument();
  });
});
