import type {Action, Device} from './types';

/** The flag also covers pending/failed containment. Only a successful hub audit
 * sentence from the current isolation period proves the cut-off completed.
 * The public action API does not expose the producer's result field. */
export function hasConfirmedCutOff(actions: Action[], device: Pick<Device, 'device_id' | 'isolated' | 'isolated_since'>): boolean {
  if (!device.isolated) return false;
  const recent = actions.filter(a => a.device_id === device.device_id && a.occurred_at >= (device.isolated_since ?? 0))
    .sort((a, b) => b.occurred_at - a.occurred_at);
  for (const action of recent) {
    if (action.action_code === 'enable_client' && !/FAILED|DRY RUN/i.test(action.action)) return false;
    if (action.action_code === 'disable_client' && action.action.startsWith(`Cut off ${device.device_id} at the hub`)) return true;
  }
  return false;
}
