// The first-steps guide said inside the home conversation.
import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockGuide: any = null;
const mockRefetch = jest.fn(async () => ({ data: { assistantGuide: mockGuide } }));
const mockRecord = jest.fn(async (_options: { variables: { step: string; event: string; answer?: string; detail?: string } }) => ({}));
const mockRequestTrail = jest.fn();
const mockTopUpDecline = jest.fn();
let mockSawPrice = false;
let mockSkip: boolean | undefined;

let mockLoading = false;
jest.mock('@apollo/client', () => ({
  useQuery: (_query: unknown, options: { skip: boolean }) => {
    mockSkip = options.skip;
    const answered = !options.skip && !mockLoading;
    return { data: answered ? { assistantGuide: mockGuide } : undefined, loading: !options.skip && mockLoading, refetch: mockRefetch };
  },
  useMutation: () => [mockRecord],
}));
jest.mock('../api', () => ({ GET_ASSISTANT_GUIDE: 'guide', RECORD_ASSISTANT_GUIDE_EVENT: 'record' }));
jest.mock('../guidePointer', () => ({
  requestGuideTrail: (request: unknown) => mockRequestTrail(request),
  subscribeGuideRefresh: () => () => {},
}));
jest.mock('../guideTopUpDecline', () => ({ GUIDE_TOP_UP_STEP: 'top_up', requestTopUpDecline: () => mockTopUpDecline() }));
jest.mock('../../services/topUpExit', () => ({ sawTopUpPriceThisRun: () => mockSawPrice }));

import { useHomeGuide, type HomeGuide } from '../useHomeGuide';

let guide!: HomeGuide;
const Probe = ({ enabled = true, account = 'personal_0' }: { enabled?: boolean; account?: string }) => {
  guide = useHomeGuide(enabled, account);
  return null;
};
// The step counts as shown once Inicio has been looked at for a moment.
const settle = () => act(async () => { jest.advanceTimersByTime(1000); });
async function mount(props: { enabled?: boolean; account?: string } = {}) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe {...props} />); });
  await settle();
  return tree;
}
const events = () => mockRecord.mock.calls.map(([options]) => {
  const { step, event, answer, detail } = options.variables;
  return [step, event, answer, detail].filter((v) => v !== undefined).join(':');
});
const TRAIL = [{ route: 'Home', text: 'Toca Recibir.', pointer: 'home_receive' },
  { route: 'Receive', text: 'Toca aquí para crear tu recarga.', pointer: 'recharge_now' }];
const TOP_UP = {
  step: 'top_up', stage: 'top_up', text: 'Ya puedes recargar. ¿Empezamos?', presentation: 'bubble',
  chips: [
    { label: 'Sí, ir a Recargar', kind: 'navigate', answer: '', trail: TRAIL },
    { label: 'Ahora no', kind: 'dismiss', answer: '', trail: [] },
    { label: 'Algo nuevo', kind: 'future_kind', answer: '', trail: [] },
  ],
};
const OPENING = {
  step: 'opening', stage: 'opening', text: 'Hola, Ana. ¿Para qué te gustaría usar Confío?', presentation: 'full',
  chips: [{ label: 'Ahorrar', kind: 'probe', answer: 'savings', trail: [] }, { label: 'Ahora no', kind: 'dismiss', answer: '', trail: [] }],
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  mockGuide = null;
  mockSawPrice = false;
  mockLoading = false;
});
afterEach(() => {
  jest.clearAllTimers();
  jest.useRealTimers();
});

it('is drawn at once, and counts as shown only once Inicio has been looked at for a moment', async () => {
  mockGuide = TOP_UP;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  // No swap from the greeting a moment later: the step is there from the first paint.
  expect(guide.guide?.step).toBe('top_up');
  expect(events()).toEqual([]);
  await act(async () => { jest.advanceTimersByTime(300); });
  // Gone before the moment was up: a screen crossed on the way elsewhere is not a step someone was shown.
  await act(async () => { tree.update(<Probe enabled={false} />); });
  await settle();
  expect(guide.guide).toBeNull();
  expect(events()).toEqual([]);
  // Back on Inicio: it is still the step to say, and now it counts.
  await act(async () => { tree.update(<Probe />); });
  expect(guide.guide?.step).toBe('top_up');
  await settle();
  expect(events()).toEqual(['top_up:shown:conversation']);
  await act(async () => tree.unmount());
});

it('asks nothing while it is not the conversation on screen', async () => {
  mockGuide = TOP_UP;
  const tree = await mount({ enabled: false });
  expect(mockSkip).toBe(true);
  expect(guide.guide).toBeNull();
  expect(events()).toEqual([]);
  await act(async () => tree.unmount());
});

it('says the step once, with only the chips this build can act on', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  expect(guide.guide?.text).toBe('Ya puedes recargar. ¿Empezamos?');
  expect(guide.guide?.chips.map((c) => c.label)).toEqual(['Sí, ir a Recargar', 'Ahora no']);
  // `conversation` tells these from the old card's in the funnel.
  expect(events()).toEqual(['top_up:shown:conversation']);
  // Re-rendering (another poll with the same answer) does not count it again.
  await act(async () => { tree.update(<Probe />); });
  await settle();
  expect(events()).toEqual(['top_up:shown:conversation']);
  await act(async () => tree.unmount());
});

it('a chip that leads somewhere hands its trail to the walk engine', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  await act(async () => { guide.press(guide.guide!.chips[0]); });
  expect(guide.guide).toBeNull();
  expect(events()).toEqual(['top_up:shown:conversation', 'top_up:accepted:']);
  expect(mockRequestTrail).toHaveBeenCalledWith({ step: 'top_up', detail: '', stops: TRAIL });
  // Done for this session: it does not come back on its own.
  await act(async () => { tree.update(<Probe />); });
  await settle();
  expect(guide.guide).toBeNull();
  await act(async () => tree.unmount());
});

it('a tap before the moment was up still counts the step as shown, once', async () => {
  mockGuide = TOP_UP;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  await act(async () => { guide.press(guide.guide!.chips[1]); });
  await settle();
  expect(events()).toEqual(['top_up:shown:conversation', 'top_up:dismissed']);
  expect(guide.guide).toBeNull();
  await act(async () => tree.unmount());
});

it('"Ahora no" dismisses, and asks why only for a top-up declined before any price was seen', async () => {
  mockGuide = TOP_UP;
  let tree = await mount();
  await act(async () => { guide.press(guide.guide!.chips[1]); });
  expect(guide.guide).toBeNull();
  expect(events()).toEqual(['top_up:shown:conversation', 'top_up:dismissed']);
  expect(mockTopUpDecline).toHaveBeenCalledTimes(1);
  expect(mockRequestTrail).not.toHaveBeenCalled();
  await act(async () => tree.unmount());

  mockSawPrice = true;
  tree = await mount();
  await act(async () => { guide.press(guide.guide!.chips[1]); });
  expect(mockTopUpDecline).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it('an answer to the opening question brings the next step', async () => {
  mockGuide = OPENING;
  const tree = await mount();
  expect(guide.guide?.step).toBe('opening');
  mockGuide = TOP_UP;
  await act(async () => { guide.press(guide.guide!.chips[0]); });
  expect(mockRecord.mock.calls[1][0].variables).toMatchObject({ step: 'opening', event: 'accepted', answer: 'savings' });
  expect(guide.pending).toBe(false);
  expect(guide.guide?.step).toBe('top_up');
  await settle();
  expect(events()).toEqual(['opening:shown:conversation', 'opening:accepted:savings', 'top_up:shown:conversation']);
  await act(async () => tree.unmount());
});

it('written instead of tapped: the chips stay under that reply, and only the first answer keeps to the step', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  expect(guide.replied).toBe(false);
  const reply = guide.beginReply();
  expect(reply?.step).toBe('top_up');
  // A failed send leaves the step as it was.
  await act(async () => { reply?.finish(false); });
  expect(guide.replied).toBe(false);
  await act(async () => { guide.beginReply()?.finish(true); });
  // Not decided by writing: the step and its chips are still there to tap.
  expect(guide.guide?.step).toBe('top_up');
  expect(guide.replied).toBe(true);
  expect(events()).toEqual(['top_up:shown:conversation', 'top_up:replied']);
  await act(async () => { guide.press(guide.guide!.chips[0]); });
  expect(mockRequestTrail).toHaveBeenCalledTimes(1);
  expect(guide.guide).toBeNull();
  await act(async () => tree.unmount());
});

it('with the next message the conversation has moved on: the step leaves, undecided', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  await act(async () => { guide.beginReply()?.finish(true); });
  let second: ReturnType<HomeGuide['beginReply']> = null;
  await act(async () => { second = guide.beginReply(); });
  // Not steered, and no chips left under an answer about something else.
  expect(second).toBeNull();
  expect(guide.guide).toBeNull();
  // Neither accepted nor refused: free to come back another day.
  expect(events()).toEqual(['top_up:shown:conversation', 'top_up:replied']);
  await act(async () => { tree.update(<Probe />); });
  await settle();
  expect(guide.guide).toBeNull();
  await act(async () => tree.unmount());
});

it('a greeting never closes the opening question: it stays to be answered with a tap', async () => {
  mockGuide = OPENING;
  const tree = await mount();
  await act(async () => { guide.beginReply()?.finish(true); });
  expect(events()).toEqual(['opening:shown:conversation', 'opening:replied']);
  expect(guide.guide?.step).toBe('opening');
  expect(guide.replied).toBe(true);
  expect(mockRefetch).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('when the server names a different step, it replaces the one on screen', async () => {
  // "Ya puedes recargar" is showing; the person tops up from the menu and comes back.
  mockGuide = TOP_UP;
  const tree = await mount();
  expect(guide.guide?.step).toBe('top_up');
  await act(async () => { guide.beginReply()?.finish(true); });
  mockGuide = { step: 'send', stage: 'first_action', text: '¿Te muestro cómo enviarle a alguien?', presentation: 'bubble', chips: [] };
  await act(async () => { tree.update(<Probe />); });
  expect(guide.guide?.step).toBe('send');
  // A new step starts fresh: its sentence is said, not only its chips.
  expect(guide.replied).toBe(false);
  await settle();
  expect(events()).toEqual(['top_up:shown:conversation', 'top_up:replied', 'send:shown:conversation']);
  // A resting step answers null: that never removes what is on screen.
  mockGuide = null;
  await act(async () => { tree.update(<Probe />); });
  expect(guide.guide?.step).toBe('send');
  await act(async () => tree.unmount());
});

it('is not drawn while the team has the thread or another screen is in front, and waits', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  await act(async () => { tree.update(<Probe enabled={false} />); });
  expect(guide.guide).toBeNull();
  expect(guide.beginReply()).toBeNull();
  await act(async () => { tree.update(<Probe />); });
  expect(guide.guide?.step).toBe('top_up');
  await settle();
  expect(events()).toEqual(['top_up:shown:conversation']);
  await act(async () => tree.unmount());
});

it('a step never crosses an account switch', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  expect(guide.guide?.step).toBe('top_up');
  await act(async () => { tree.update(<Probe account="business_1_0" enabled={false} />); });
  expect(guide.guide).toBeNull();
  await act(async () => tree.unmount());
});

it('says whether the server has answered, so an empty thread does not greet and then swap', async () => {
  mockGuide = TOP_UP;
  mockLoading = true;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  expect(guide.settled).toBe(false);
  expect(guide.guide).toBeNull();
  mockLoading = false;
  await act(async () => { tree.update(<Probe />); });
  expect(guide.settled).toBe(true);
  expect(guide.guide?.step).toBe('top_up');
  // Nothing to wait for where the guide does not apply.
  await act(async () => { tree.update(<Probe enabled={false} />); });
  expect(guide.settled).toBe(true);
  await act(async () => tree.unmount());
});

it('a step counted once may be said again (verify, in review, verify again), without counting it twice', async () => {
  const VERIFY = { step: 'verify', stage: 'verify', text: 'Primero verifica tu identidad.', presentation: 'bubble', chips: [] };
  const VERIFYING = { step: 'verifying', stage: 'verifying', text: 'Tu verificación sigue en revisión.', presentation: 'bubble', chips: [] };
  mockGuide = VERIFY;
  const tree = await mount();
  mockGuide = VERIFYING;
  await act(async () => { tree.update(<Probe />); });
  await settle();
  expect(guide.guide?.step).toBe('verifying');
  // The review came back declined: the server asks to verify again.
  mockGuide = VERIFY;
  await act(async () => { tree.update(<Probe />); });
  await settle();
  expect(guide.guide?.step).toBe('verify');
  expect(events()).toEqual(['verify:shown:conversation', 'verifying:shown:conversation']);
  await act(async () => tree.unmount());
});

it('an answer that did not reach the server brings the question back instead of losing it', async () => {
  mockGuide = OPENING;
  const tree = await mount();
  // The refetch still names the opening question: the accept was not saved.
  await act(async () => { guide.press(guide.guide!.chips[0]); });
  expect(guide.pending).toBe(false);
  expect(guide.guide?.step).toBe('opening');
  await act(async () => tree.unmount());
});

it('what was left is left for the day, not for as long as the app stays alive', async () => {
  mockGuide = TOP_UP;
  const tree = await mount();
  await act(async () => { guide.press(guide.guide!.chips[1]); });
  await act(async () => { tree.update(<Probe />); });
  expect(guide.guide).toBeNull();
  // The next day, with the app never closed, the server offers it again.
  jest.setSystemTime(new Date(Date.now() + 26 * 3600 * 1000));
  await act(async () => { tree.update(<Probe />); });
  expect(guide.guide?.step).toBe('top_up');
  await act(async () => tree.unmount());
});

// ── The first conversation: meet the assistant, then say it in your own words ──
const MEET = {
  step: 'meet', stage: 'meet', text: 'Hola, Ana. Soy tu asistente en Confío.', presentation: 'bubble',
  chips: [
    { label: 'Elegir cómo te ves', kind: 'pet', answer: '', trail: [] },
    { label: 'Seguir así', kind: 'skip', answer: '', trail: [] },
  ],
};
const WORDS = {
  step: 'opening_words', stage: 'opening', text: 'Cuéntame con tus palabras: ¿para qué te gustaría usar Confío?',
  presentation: 'bubble',
  chips: [
    { label: '¿Qué es Confío?', kind: 'ask', answer: '', trail: [] },
    { label: 'No sé todavía', kind: 'probe', answer: 'other', trail: [] },
  ],
};

it('meeting the assistant: choosing its look or keeping it both settle the step and bring the next one', async () => {
  mockGuide = MEET;
  let tree = await mount();
  expect(guide.guide?.chips.map((c) => c.kind)).toEqual(['pet', 'skip']);
  mockGuide = WORDS;
  await act(async () => { guide.press(MEET.chips[0] as any); });
  expect(events()).toContain('meet:accepted:');   // no answer goes with it
  expect(guide.guide?.step).toBe('opening_words');
  await act(async () => tree.unmount());

  mockRecord.mockClear();
  mockGuide = MEET;
  tree = await mount({ account: 'personal_1' });
  mockGuide = WORDS;
  await act(async () => { guide.press(MEET.chips[1] as any); });
  expect(events()).toContain('meet:dismissed');
  // Not left for the day: the question comes right after.
  expect(guide.guide?.step).toBe('opening_words');
  await act(async () => tree.unmount());
});

it('a question chip decides nothing: the step and its chips stay for the conversation to answer', async () => {
  mockGuide = WORDS;
  const tree = await mount();
  mockRecord.mockClear();
  await act(async () => { guide.press(WORDS.chips[0] as any); });
  expect(guide.guide?.step).toBe('opening_words');
  expect(guide.pending).toBe(false);
  expect(events()).toEqual([]);
  await act(async () => tree.unmount());
});
