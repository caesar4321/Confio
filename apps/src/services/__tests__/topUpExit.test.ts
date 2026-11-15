import {
  TOP_UP_EXIT_REASONS,
  isLimitRefusal,
  requestTopUpExitQuestion,
  resetTopUpExitQuestionForTests,
  shuffledExitReasons,
  subscribeTopUpExitQuestion,
} from '../topUpExit';

const memoryStore = () => {
  let day = '';
  return { read: async () => day, write: async (next: string) => { day = next; } };
};

describe('topUpExit', () => {
  it('shuffles every answer but keeps "other" last', () => {
    let seed = 0.9;
    const random = () => { seed = (seed * 7.13) % 1; return seed; };
    for (let i = 0; i < 20; i += 1) {
      const order = shuffledExitReasons(random).map(([id]) => id);
      expect([...order].sort()).toEqual(TOP_UP_EXIT_REASONS.map(([id]) => id).sort());
      expect(order[order.length - 1]).toBe('other');
    }
  });

  it('asks at most once a day, only with a host mounted, and remembers across restarts', async () => {
    const store = memoryStore();
    resetTopUpExitQuestionForTests(store);
    const day = new Date(2026, 10, 15, 10);
    expect(await requestTopUpExitQuestion(day)).toBe(false); // no host yet: the day is not spent
    const host = jest.fn();
    const unsubscribe = subscribeTopUpExitQuestion(host);
    expect(await requestTopUpExitQuestion(day)).toBe(true);
    expect(await requestTopUpExitQuestion(new Date(2026, 10, 15, 23))).toBe(false);

    resetTopUpExitQuestionForTests(store); // an app restart: memory gone, the stored day stays
    subscribeTopUpExitQuestion(host);
    expect(await requestTopUpExitQuestion(new Date(2026, 10, 15, 23))).toBe(false);
    expect(await requestTopUpExitQuestion(new Date(2026, 10, 16, 9))).toBe(true);
    expect(host).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it('does not spend the day when the host goes away before the next tick (logout)', async () => {
    resetTopUpExitQuestionForTests(memoryStore());
    const host = jest.fn();
    const unsubscribe = subscribeTopUpExitQuestion(host);
    const asked = requestTopUpExitQuestion(new Date(2026, 10, 15, 10));
    unsubscribe();
    expect(await asked).toBe(false);
    subscribeTopUpExitQuestion(host);
    expect(await requestTopUpExitQuestion(new Date(2026, 10, 15, 11))).toBe(true);
  });

  it('decides from the day read when the screen opened, without waiting on the store again', async () => {
    let slow = false;
    resetTopUpExitQuestionForTests({
      read: () => (slow ? new Promise<string>(() => {}) : Promise.resolve('')), // after the preload: never answers
      write: async () => {},
    });
    const { preloadTopUpExitDay } = jest.requireActual('../topUpExit');
    await preloadTopUpExitDay();
    slow = true;
    subscribeTopUpExitQuestion(jest.fn());
    expect(await requestTopUpExitQuestion(new Date(2026, 10, 15, 10))).toBe(true);
  });

  it('knows a min/max refusal from any other error', () => {
    expect(isLimitRefusal('El monto mínimo para esta recarga es $1.25.')).toBe(true);
    expect(isLimitRefusal('El monto máximo por QR es $2000.')).toBe(true);
    expect(isLimitRefusal('Ingresa al menos 350 BOB. El monto es menor al mínimo permitido')).toBe(true);
    expect(isLimitRefusal('No pudimos conectar.')).toBe(false);
    expect(isLimitRefusal(undefined)).toBe(false);
  });
});
