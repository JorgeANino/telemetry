import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePolledJson } from './usePolledJson';

/**
 * F-006 smoke test: every poll must hand an AbortSignal to fetch, and the
 * hook's cleanup must abort the in-flight request so an unmounted component
 * doesn't keep a connection open forever.
 */
describe('usePolledJson', () => {
  let originalFetch: typeof globalThis.fetch;
  let signals: AbortSignal[];
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    signals = [];
    fetchMock = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.signal) signals.push(init.signal);
        return new Response('{}', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      },
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
  });

  // Lets the immediate `tick()` (called inside the effect) actually fire its
  // fetch and stash a signal before we assert.
  const flushMicrotasks = async () => {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  };

  it('passes an AbortSignal on every fetch and aborts on unmount', async () => {
    const { unmount } = renderHook(() =>
      usePolledJson<Record<string, never>>('/fleet/state'),
    );

    await flushMicrotasks();

    expect(fetchMock).toHaveBeenCalled();
    expect(signals.length).toBeGreaterThanOrEqual(1);
    const firstSignal = signals[0]!;
    expect(firstSignal).toBeInstanceOf(AbortSignal);
    expect(firstSignal.aborted).toBe(false);

    act(() => {
      unmount();
    });

    expect(firstSignal.aborted).toBe(true);
  });

  it('aborts the previous tick before starting a new one', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const { unmount } = renderHook(() =>
      usePolledJson<Record<string, never>>('/zones/counts'),
    );

    // Let the initial tick fire.
    await flushMicrotasks();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Advance past POLL_MS (2000) so setInterval fires the next tick.
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await flushMicrotasks();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    // First request must have been aborted before the second fired —
    // either via the per-tick controller swap or the POLL_MS timeout.
    expect(signals[0]!.aborted).toBe(true);
    expect(signals[1]!.aborted).toBe(false);

    act(() => {
      unmount();
    });
  });
});
