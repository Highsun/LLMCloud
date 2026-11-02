// The same scheduler is used by TasksPanel and tested with an isolated clock.
export function createTaskPolling({
  shouldPoll,
  refresh,
  delay = 2000,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) {
  let timer = null;
  let running = false;
  let generation = 0;

  function schedule(current) {
    timer = setTimer(async () => {
      timer = null;
      if (!running || current !== generation) return;
      try {
        if (shouldPoll()) await refresh();
      } finally {
        // An old tick cannot restart the timer after hide/unmount/restart.
        if (running && current === generation) schedule(current);
      }
    }, delay);
  }

  return {
    start() {
      if (running) return;
      running = true;
      schedule(++generation);
    },
    stop() {
      running = false;
      ++generation;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
  };
}
