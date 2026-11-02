import assert from "node:assert/strict";
import { test } from "node:test";
import { createTaskPolling } from "../src/task-polling.js";

function clock() {
  let next = 0;
  const scheduled = new Map();
  return {
    scheduled,
    setTimer(fn, delay) {
      scheduled.set(++next, { fn, delay });
      return next;
    },
    clearTimer(id) {
      scheduled.delete(id);
    },
    fire() {
      const [id, timer] = scheduled.entries().next().value;
      scheduled.delete(id);
      return timer.fn();
    },
  };
}

test("轮询每次完成后等待 2 秒，不重叠请求，重复启动不增开计时器", async () => {
  const time = clock();
  let count = 0;
  let resolve;
  const polling = createTaskPolling({
    ...time,
    shouldPoll: () => true,
    refresh: () => {
      count++;
      return new Promise((done) => {
        resolve = done;
      });
    },
  });
  polling.start();
  polling.start();
  assert.equal(time.scheduled.size, 1);
  assert.equal([...time.scheduled.values()][0].delay, 2000);
  const tick = time.fire();
  assert.equal(count, 1);
  assert.equal(time.scheduled.size, 0);
  resolve();
  await tick;
  assert.equal(time.scheduled.size, 1);
  polling.stop();
});

test("隐藏页面或 API 未就绪时不发请求，恢复后可以继续轮询", async () => {
  const time = clock();
  let visible = false,
    available = true,
    count = 0;
  const polling = createTaskPolling({
    ...time,
    shouldPoll: () => visible && available,
    refresh: async () => {
      count++;
    },
  });
  polling.start();
  await time.fire();
  assert.equal(count, 0);
  visible = true;
  available = false;
  await time.fire();
  assert.equal(count, 0);
  available = true;
  await time.fire();
  assert.equal(count, 1);
  polling.stop();
});

test("停止轮询移除计时器，正在返回的旧 tick 不能重新启动轮询", async () => {
  const time = clock();
  let resolve;
  const polling = createTaskPolling({
    ...time,
    shouldPoll: () => true,
    refresh: () =>
      new Promise((done) => {
        resolve = done;
      }),
  });
  polling.start();
  const tick = time.fire();
  polling.stop();
  resolve();
  await tick;
  assert.equal(time.scheduled.size, 0);
  polling.start();
  assert.equal(time.scheduled.size, 1);
  polling.stop();
  assert.equal(time.scheduled.size, 0);
});

test("隐藏再显示后，旧 tick 完成也不能重复创建新一代计时器", async () => {
  const time = clock();
  let resolve;
  const polling = createTaskPolling({
    ...time,
    shouldPoll: () => true,
    refresh: () =>
      new Promise((done) => {
        resolve = done;
      }),
  });
  polling.start();
  const oldTick = time.fire();
  polling.stop();
  polling.start();
  resolve();
  await oldTick;
  assert.equal(time.scheduled.size, 1);
  polling.stop();
});
