import {cleanup, fireEvent, renderHook} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {useUnsavedChanges} from './useUnsavedChanges';
afterEach(() => {cleanup(); vi.restoreAllMocks(); document.body.innerHTML = '';});
it('warns on browser exit only while changes are unsaved', () => {
  const {rerender} = renderHook(({dirty}) => useUnsavedChanges(dirty), {initialProps: {dirty: true}});
  const exit = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(exit);
  expect(exit.defaultPrevented).toBe(true);
  rerender({dirty: false});
  const savedExit = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(savedExit);
  expect(savedExit.defaultPrevented).toBe(false);
});
it('keeps edits when leaving via a route link is cancelled; permits confirmed exits', () => {
  renderHook(() => useUnsavedChanges(true));
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const link = document.createElement('a'); link.href = '/ward'; document.body.append(link);
  // Avoid jsdom navigation; its return value still tells us whether the guard cancelled.
  link.addEventListener('click', event => event.preventDefault());
  fireEvent.click(link);
  expect(confirm).toHaveBeenCalledWith('Leave without saving your report edits?');
  confirm.mockReturnValue(true);
  const bubble = vi.fn(); link.addEventListener('click', bubble);
  fireEvent.click(link);
  expect(bubble).toHaveBeenCalledTimes(1);
});
