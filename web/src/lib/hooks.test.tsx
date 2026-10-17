import {act, cleanup, renderHook, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {useResource} from './hooks';

afterEach(() => {cleanup(); vi.unstubAllGlobals();});
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(done => {resolve = done;});
  return {promise, resolve};
}
it('keeps the newest reload even if an aborted older fetch still resolves', async () => {
  const first = deferred(), second = deferred();
  const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  vi.stubGlobal('fetch', fetcher);
  const {result} = renderHook(() => useResource<{value: string}>('/api/example', 0));
  let reload!: Promise<void>;
  act(() => {reload = result.current.reload();});
  await act(async () => {second.resolve(new Response('{"value":"new"}')); await reload;});
  expect(result.current.data?.value).toBe('new');
  await act(async () => {first.resolve(new Response('{"value":"old"}')); await first.promise;});
  expect(result.current.data?.value).toBe('new');
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
});
it('clears old data on route changes and aborts pending work on unmount', async () => {
  const old = deferred(), next = deferred();
  const fetcher = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  vi.stubGlobal('fetch', fetcher);
  const {result, rerender, unmount} = renderHook(({path}) => useResource<{value: string}>(path, 0), {initialProps: {path: '/api/old'}});
  rerender({path: '/api/new'});
  await act(async () => {old.resolve(new Response('{"value":"old"}')); await old.promise;});
  expect(result.current.data).toBeNull();
  await act(async () => {next.resolve(new Response('{"value":"new"}')); await next.promise;});
  await waitFor(() => expect(result.current.data?.value).toBe('new'));
  unmount();
  expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true);
});
