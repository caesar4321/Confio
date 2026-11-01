import { measureGuideAnchor, setGuidePointer } from '../guidePointer';
import { loopLength } from '../GuidePencil';

jest.mock('react-native-svg', () => ({ __esModule: true, default: 'Svg', Path: 'Path' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

describe('guide pointer', () => {
  afterEach(() => setGuidePointer(null));

  it('draws nothing for a button this build does not have', async () => {
    await expect(measureGuideAnchor('a_button_from_the_future')).resolves.toBeNull();
  });

  it('sizes the pencil loop by the button', () => {
    expect(loopLength(320, 80)).toBeGreaterThan(loopLength(120, 40));
  });
});
