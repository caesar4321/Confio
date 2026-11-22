import { onMailConnectResult, receiveMailConnectLink, takeMailConnectResult } from '../connectLink';
import { ASSISTANT_MAIL_ENABLED } from '../flag';

beforeEach(() => {
  takeMailConnectResult();
});

it('ships off', () => {
  expect(ASSISTANT_MAIL_ENABLED).toBe(false);
});

it('takes the code and state once', () => {
  const heard = jest.fn();
  const stop = onMailConnectResult(heard);
  expect(receiveMailConnectLink('confio://gmail-connect?state=s1&code=4%2F0Ab&scope=x')).toBe(true);
  stop();
  expect(heard).toHaveBeenCalledTimes(1);
  expect(takeMailConnectResult()).toEqual({ code: '4/0Ab', state: 's1' });
  expect(takeMailConnectResult()).toBeNull();
});

it('reports a refusal', () => {
  receiveMailConnectLink('confio://gmail-connect?error=access_denied&state=s1');
  expect(takeMailConnectResult()).toEqual({ denied: true, state: 's1' });
});

it.each(['confio://pay?code=a&state=b', 'https://evil.example/gmail-connect?code=a&state=b', 'confio://gmail-connectx?code=a&state=b'])(
  'ignores %s',
  (url) => {
    expect(receiveMailConnectLink(url)).toBe(false);
    expect(takeMailConnectResult()).toBeNull();
  },
);
