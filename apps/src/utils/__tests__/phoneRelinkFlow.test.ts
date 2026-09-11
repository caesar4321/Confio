import { createPhoneRelinkFlow } from '../phoneRelinkFlow';

const preview = { token: 'proof', accounts: [{ email: 'old@example.com', username: 'old' }] };
const setup = () => ({
  verify: jest.fn().mockResolvedValue({ success: false, relinkConfirmation: preview }),
  confirm: jest.fn().mockResolvedValue({ success: true }),
  ask: jest.fn().mockResolvedValue(true),
  retry: jest.fn().mockResolvedValue(false),
  isActive: jest.fn().mockReturnValue(true),
  reset: jest.fn(),
});

test('declining a transport retry keeps the token but requires renewed consent', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.confirm.mockRejectedValueOnce(new Error('response lost'));
  expect(await flow.run(deps)).toBeNull();
  expect(deps.retry).toHaveBeenCalledWith(preview);
  expect(await flow.run(deps)).toEqual({ success: true });
  expect(deps.verify).toHaveBeenCalledTimes(1);
  expect(deps.ask.mock.calls).toEqual([[preview], [preview]]);
  expect(deps.confirm.mock.calls).toEqual([['proof'], ['proof']]);
  expect(deps.reset).not.toHaveBeenCalled();
});

test('accepting a transport retry resubmits the approved token without asking again', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.confirm.mockRejectedValueOnce(new Error('response lost'));
  deps.retry.mockResolvedValueOnce(true);
  expect(await flow.run(deps)).toEqual({ success: true });
  expect(deps.ask).toHaveBeenCalledTimes(1);
  expect(deps.confirm.mock.calls).toEqual([['proof'], ['proof']]);
});

test('retryable server failures retain proof, including a missing response payload', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.confirm.mockResolvedValueOnce({ success: false, retryable: true, error: 'retry' })
    .mockResolvedValueOnce(undefined);
  expect(await flow.run(deps)).toMatchObject({ retryable: true });
  expect(await flow.run(deps)).toMatchObject({ retryable: true });
  expect(await flow.run(deps)).toEqual({ success: true });
  expect(deps.verify).toHaveBeenCalledTimes(1);
  expect(deps.ask).toHaveBeenCalledTimes(1);
});

test('changed ownership requires new consent before using the replacement token', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  const changed = { token: 'changed', accounts: [{ email: 'new@example.com', username: 'new' }] };
  deps.confirm.mockResolvedValueOnce({ success: false, relinkConfirmation: changed });
  expect(await flow.run(deps)).toEqual({ success: true });
  expect(deps.ask.mock.calls).toEqual([[preview], [changed]]);
  expect(deps.confirm.mock.calls).toEqual([['proof'], ['changed']]);
});

test('declining changed ownership resets without submitting its token', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.confirm.mockResolvedValueOnce({ relinkConfirmation: { ...preview, token: 'changed' } });
  deps.ask.mockResolvedValueOnce(true).mockResolvedValueOnce(false);
  expect(await flow.run(deps)).toBeNull();
  expect(deps.confirm).toHaveBeenCalledTimes(1);
  expect(deps.reset).toHaveBeenCalledTimes(1);
  await flow.run(deps);
  expect(deps.verify).toHaveBeenCalledTimes(2);
});

test('expired confirmation resets the code flow and surfaces the server error', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.confirm.mockResolvedValueOnce({ success: false, retryable: false, error: 'Verify again' });
  expect(await flow.run(deps)).toMatchObject({ error: 'Verify again' });
  expect(deps.reset).toHaveBeenCalledTimes(1);
  await flow.run(deps);
  expect(deps.verify).toHaveBeenCalledTimes(2);
});

test('initial cancellation and explicit abandonment clear pending proof', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.ask.mockResolvedValueOnce(false);
  await flow.run(deps);
  expect(deps.confirm).not.toHaveBeenCalled();
  expect(deps.reset).toHaveBeenCalledTimes(1);
  deps.confirm.mockRejectedValueOnce(new Error('offline'));
  await flow.run(deps);
  flow.clear();
  await flow.run(deps);
  expect(deps.verify).toHaveBeenCalledTimes(3);
});

test('declining renewed consent after a declined retry abandons the token', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.confirm.mockRejectedValueOnce(new Error('offline'));
  await flow.run(deps);
  deps.ask.mockResolvedValueOnce(false);
  expect(await flow.run(deps)).toBeNull();
  expect(deps.confirm).toHaveBeenCalledTimes(1);
  expect(deps.reset).toHaveBeenCalledTimes(1);
  await flow.run(deps);
  expect(deps.verify).toHaveBeenCalledTimes(2);
});

test('unmounting while consent is open prevents confirmation', async () => {
  const flow = createPhoneRelinkFlow();
  const deps = setup();
  deps.ask.mockImplementation(async () => {
    deps.isActive.mockReturnValue(false);
    return true;
  });
  expect(await flow.run(deps)).toBeNull();
  expect(deps.confirm).not.toHaveBeenCalled();
});
