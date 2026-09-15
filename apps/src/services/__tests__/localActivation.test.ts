import {Alert} from 'react-native';
import {activateLocalMoney, payLocalActivation} from '../localMoney';
const mockMutate = jest.fn();
const mockSubmit = jest.fn();
jest.mock('../../apollo/client', () => ({apolloClient: {mutate: (...args: any[]) => mockMutate(...args)}}));
jest.mock('../bscSend', () => ({submitPreparedBscSend: (...args: any[]) => mockSubmit(...args), BSC_SEND_ERRORS: {}}));
const payment = {sendId:'bound-payment',calls:[{to:'collector',data:'server-call'}]};
const response = (status:string, prepared:any=null) => ({data:{prepareLocalActivation:{success:true,status,amount:'10.00',payment:prepared}}});
beforeEach(() => jest.clearAllMocks());
afterEach(() => jest.restoreAllMocks());

it('gets fee consent before opening and waits for provider readiness', async () => {
  mockMutate.mockResolvedValueOnce(response('consent_required')).mockResolvedValueOnce(response('provisioning'));
  const alert=jest.spyOn(Alert,'alert').mockImplementation((_title,message,buttons) => {
    expect(message).toContain('Pagarás cuando la cuenta esté lista');
    expect(mockSubmit).not.toHaveBeenCalled();
    buttons?.[1].onPress?.();
  });
  await expect(payLocalActivation('co_breb')).resolves.toBe(true);
  expect(mockMutate.mock.calls[1][0].variables).toEqual({methodId:'co_breb',acceptedFee:'10.00'});
  expect(alert).toHaveBeenCalledTimes(1);
  expect(mockSubmit).not.toHaveBeenCalled();
});

it('declining the fee creates no opening and signs nothing', async () => {
  mockMutate.mockResolvedValue(response('consent_required'));
  jest.spyOn(Alert,'alert').mockImplementation((_title,_message,buttons) => buttons?.[0].onPress?.());
  await expect(payLocalActivation('co_breb')).resolves.toBe(false);
  expect(mockMutate).toHaveBeenCalledTimes(1); expect(mockSubmit).not.toHaveBeenCalled();
});

it('confirms payment only when the account is ready', async () => {
  mockMutate.mockResolvedValue(response('payment_pending',payment));
  jest.spyOn(Alert,'alert').mockImplementation((title,message,buttons) => {
    expect(title).toBe('Tu cuenta está lista');expect(message).toContain('US$10.00');
    expect(mockSubmit).not.toHaveBeenCalled();buttons?.[1].onPress?.();
  });
  await expect(payLocalActivation('co_breb')).resolves.toBe(true);
  expect(mockSubmit).toHaveBeenCalledWith(payment);
});

it('allows the user to leave a ready account unpaid', async () => {
  mockMutate.mockResolvedValue(response('payment_pending',payment));
  jest.spyOn(Alert,'alert').mockImplementation((_title,_message,buttons) => buttons?.[0].onPress?.());
  await expect(payLocalActivation('co_breb')).resolves.toBe(false);expect(mockSubmit).not.toHaveBeenCalled();
});

it.each(['provisioning','payment_pending','active','legacy'])('does not sign again for %s without payment', async status => {
  mockMutate.mockResolvedValue(response(status));const alert=jest.spyOn(Alert,'alert');
  await expect(payLocalActivation('co_breb')).resolves.toBe(true);
  expect(mockSubmit).not.toHaveBeenCalled();expect(alert).not.toHaveBeenCalled();
});

it('failed opening reports no charge and never signs', async () => {
  mockMutate.mockResolvedValue(response('failed'));
  await expect(payLocalActivation('co_breb')).rejects.toThrow('No se realizó ningún cobro');
  expect(mockSubmit).not.toHaveBeenCalled();
});

it('times out opening requests and never approves or signs a late payment response', async () => {
  jest.useFakeTimers();
  let release!: (response: any) => void;
  mockMutate.mockImplementationOnce(() => new Promise(resolve => {release = resolve;}));
  const confirmPayment = jest.fn().mockResolvedValue(true);
  try {
    const opening = payLocalActivation('mx_clabe', {confirmPayment});
    const rejected = expect(opening).rejects.toThrow('tardó demasiado');
    await jest.advanceTimersByTimeAsync(60001);
    await rejected;
    release(response('payment_pending', payment));
    await jest.advanceTimersByTimeAsync(1);
    expect(confirmPayment).not.toHaveBeenCalled();
    expect(mockSubmit).not.toHaveBeenCalled();
  } finally {
    jest.useRealTimers();
  }
});

it('bounds a stalled activation-status check', async () => {
  jest.useFakeTimers();
  mockMutate.mockImplementationOnce(() => new Promise(() => {}));
  try {
    const rejected = expect(activateLocalMoney('mx_clabe')).rejects.toThrow('tardó demasiado');
    await jest.advanceTimersByTimeAsync(60001);
    await rejected;
    expect(mockSubmit).not.toHaveBeenCalled();
  } finally {
    jest.useRealTimers();
  }
});
