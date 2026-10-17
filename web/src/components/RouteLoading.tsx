/** A quiet, viewport-sized placeholder; the station header stays mounted on navigation. */
export function RouteLoading({fullPage = false}: {fullPage?: boolean}) {
  const message = <div className={`route-loading${fullPage ? ' route-loading-full' : ''}`} role="status">Loading screen…</div>;
  return fullPage ? <main id="main">{message}</main> : message;
}
