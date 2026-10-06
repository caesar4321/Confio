import { isSystemPickerOpen, resetSystemPickerForTests, SYSTEM_PICKER_MAX_MS, withSystemPicker } from '../systemPickerGuard';

describe('systemPicker resume-lock exemption', () => {
  let now = 1_000_000;
  beforeEach(() => {
    resetSystemPickerForTests();
    now = 1_000_000;
    jest.spyOn(Date, 'now').mockImplementation(() => now);
  });
  afterEach(() => jest.restoreAllMocks());

  it('covers the time the picker is open and a short settle after it closes', async () => {
    let finish!: () => void;
    const picking = withSystemPicker(() => new Promise<void>((resolve) => { finish = resolve; }));
    now += 15_000; // browsing photos for 15 s (the reported case)
    expect(isSystemPickerOpen()).toBe(true);
    finish();
    await picking;
    now += 1_000;
    expect(isSystemPickerOpen()).toBe(true); // AppState 'active' lands just after
    now += 5_000;
    expect(isSystemPickerOpen()).toBe(false);
  });

  it('never exempts a phone left in the picker past the cap', async () => {
    let finish!: () => void;
    const picking = withSystemPicker(() => new Promise<void>((resolve) => { finish = resolve; }));
    now += SYSTEM_PICKER_MAX_MS + 1;
    expect(isSystemPickerOpen()).toBe(false);
    finish();
    await picking;
    expect(isSystemPickerOpen()).toBe(false);
  });

  it('closes the exemption even when the picker fails', async () => {
    await expect(withSystemPicker(() => Promise.reject(new Error('denied')))).rejects.toThrow('denied');
    now += 5_000;
    expect(isSystemPickerOpen()).toBe(false);
  });
});
