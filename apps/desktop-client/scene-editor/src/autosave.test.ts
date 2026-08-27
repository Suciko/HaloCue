import { afterEach, describe, expect, it, vi } from "vitest";

import { AutosaveCoordinator } from "./autosave";

afterEach(() => vi.useRealTimers());

describe("autosave coordinator", () => {
  it("persists only the latest revision in a burst", () => {
    vi.useFakeTimers();
    const save = vi.fn();
    const publish = vi.fn();
    const coordinator = new AutosaveCoordinator(save, publish);

    expect(coordinator.request("first", 1)).toEqual({
      status: "pending",
      savedRevision: 0,
      pendingRevision: 1,
      error: null,
    });
    coordinator.request("latest", 2);
    vi.advanceTimersByTime(449);
    expect(save).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("latest");
    expect(publish).toHaveBeenLastCalledWith({
      status: "saved",
      savedRevision: 2,
      pendingRevision: null,
      error: null,
    });
  });

  it("flushes a pending revision synchronously", () => {
    vi.useFakeTimers();
    const save = vi.fn();
    const coordinator = new AutosaveCoordinator(save, vi.fn());

    coordinator.request("now", 1);
    coordinator.flush();

    expect(save).toHaveBeenCalledWith("now");
    expect(coordinator.currentState().savedRevision).toBe(1);
    vi.runAllTimers();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("keeps the latest snapshot retryable after persistence fails", () => {
    vi.useFakeTimers();
    const save = vi.fn()
      .mockImplementationOnce(() => { throw new Error("quota"); })
      .mockImplementationOnce(() => undefined);
    const publish = vi.fn();
    const coordinator = new AutosaveCoordinator(save, publish);

    coordinator.request("recoverable", 3);
    coordinator.flush();
    expect(coordinator.currentState()).toEqual({
      status: "failed",
      savedRevision: 0,
      pendingRevision: 3,
      error: "quota",
    });

    coordinator.retry();
    expect(coordinator.currentState().status).toBe("pending");
    vi.advanceTimersByTime(450);
    expect(save).toHaveBeenLastCalledWith("recoverable");
    expect(coordinator.currentState()).toEqual({
      status: "saved",
      savedRevision: 3,
      pendingRevision: null,
      error: null,
    });
  });
});
