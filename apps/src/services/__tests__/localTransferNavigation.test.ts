import {localTransferRoute} from '../localTransferNavigation';

const id = 'f311c949-8876-4b53-b3f6-0d5faaf7a97a';
it.each([id, `confio://local-transfer/${id}`])('opens the same parent receipt from %s', value => {
  expect(localTransferRoute(value)).toEqual({screen: 'LocalTransferStatus', params: {journeyId: id}});
});
it.each([null, {}, '', 'confio://send/'+id, 'https://evil.test/'+id, id+'/extra'])('rejects unrelated links %s', value => {
  expect(localTransferRoute(value)).toBeNull();
});
