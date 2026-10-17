import '@testing-library/jest-dom/vitest';
// jsdom has no ResizeObserver or canvas; the charts only need them to exist.
class NoopResizeObserver { observe() {} unobserve() {} disconnect() {} }
globalThis.ResizeObserver ??= NoopResizeObserver as unknown as typeof ResizeObserver;
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext'];
