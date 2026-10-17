import {useEffect, useState, useCallback, useRef} from 'react';
import {api, write} from './api';
import {useWard} from './store';

export function useNow() {
  const [now, set] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => set(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

export function useResource<T>(path: string | null, interval = 6000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const revision = useWard(s => s.revision);
  const lastPath = useRef<string | null | undefined>(undefined);
  const currentPath = useRef(path);
  currentPath.current = path;
  const mounted = useRef(false);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);

  // Interval, revision and manual reloads share one sequence. An older response can
  // never replace newer data, even if a transport ignores the abort signal.
  const reload = useCallback(async () => {
    if (!path || !mounted.current) return;
    const request = ++sequence.current;
    controller.current?.abort();
    const pending = new AbortController();
    controller.current = pending;
    const current = () => mounted.current && !pending.signal.aborted &&
      request === sequence.current && path === currentPath.current;
    try {
      const result = await api<T>(path, {signal: pending.signal});
      if (current()) {setData(result); setError('');}
    } catch (e) {
      if (current()) setError((e as Error).message);
    } finally {
      if (current()) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    mounted.current = true;
    if (lastPath.current !== path) {
      lastPath.current = path;
      setData(null);
      setLoading(Boolean(path));
      setError('');
    }
    void reload();
    const timer = path && interval ? setInterval(() => void reload(), interval) : undefined;
    return () => {
      mounted.current = false;
      ++sequence.current;
      controller.current?.abort();
      clearInterval(timer);
    };
  }, [path, interval, revision, reload]);
  return {data, error, loading, reload};
}

export function useCommand() {
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  const run = async (path: string, body: unknown = {}, method = 'POST') => {
    if (pending) return false;
    setPending(true);
    setFeedback('');
    try {
      const receipt = await write(path, body, method);
      setFailed(false);
      setFeedback(receipt.request_id ? 'Request accepted · awaiting agent confirmation.' : 'Saved · recorded in the audit log.');
      useWard.getState().bump();
      void useWard.getState().refresh();
      return true;
    } catch (e) {
      setFailed(true);
      setFeedback((e as Error).message);
      return false;
    } finally {
      setPending(false);
    }
  };
  return {pending, feedback, failed, run};
}
