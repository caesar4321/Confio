jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../hooks/usePollWhile', () => ({ usePollWhile: jest.fn() }));
jest.mock('@react-navigation/native', () => ({ useFocusEffect: jest.fn(), useIsFocused: () => true }));
jest.mock('@apollo/client', () => ({ gql: () => '', useApolloClient: jest.fn(), useMutation: jest.fn(), useQuery: jest.fn() }));

import { mentionIdsInText, mentionParts, trailingMentionQuery } from '../CommunityComments';

describe('Comunidad mentions', () => {
  it('finds the @partial being typed at the end only', () => {
    expect(trailingMentionQuery('Hola @Ma')).toBe('Ma');
    expect(trailingMentionQuery('@')).toBe('');
    expect(trailingMentionQuery('Hola @María G')).toBe('María G');
    expect(trailingMentionQuery('correo a@b')).toBeNull();
    expect(trailingMentionQuery('Hola @María G. gracias')).toBeNull();
  });

  it('highlights only the tagged names, longest first', () => {
    expect(mentionParts('@María G. y @María G. Pérez hola', ['María G.'])).toEqual([
      { text: '@María G.', mention: true },
      { text: ' y ', mention: false },
      { text: '@María G.', mention: true },
      { text: ' Pérez hola', mention: false },
    ]);
    expect(mentionParts('sin menciones', [])).toEqual([{ text: 'sin menciones', mention: false }]);
    expect(mentionParts('@Ana P. (hola)', ['Ana P.'])).toEqual([
      { text: '@Ana P.', mention: true },
      { text: ' (hola)', mention: false },
    ]);
  });

  it('notifies only people whose @Name is still in the text', () => {
    const picked = [{ id: '1', name: 'Ana P.' }, { id: '2', name: 'Luis R.' }];
    expect(mentionIdsInText('@Ana P. mira esto', picked)).toEqual(['1']);
    expect(mentionIdsInText('sin nadie', picked)).toEqual([]);
  });

  it('keeps two different people who share a display name', () => {
    const picked = [{ id: '1', name: 'Ana P.' }, { id: '7', name: 'Ana P.' }];
    expect(mentionIdsInText('@Ana P. y @Ana P.', picked)).toEqual(['1', '7']);
  });

  it('deleting one of two same-name mentions keeps only one person', () => {
    const picked = [{ id: '1', name: 'Ana P.' }, { id: '7', name: 'Ana P.' }];
    expect(mentionIdsInText('@Ana P. gracias', picked)).toEqual(['7']);
  });
});
