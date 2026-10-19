import { applyCodeInput } from '../verificationCodeInput';

const empty = () => ['', '', '', '', '', ''];

describe('applyCodeInput', () => {
  it('fills all six boxes when the whole code is pasted into the first', () => {
    // App Review 2026-10-19: pasting the code inserted only its first digit.
    const { code, focusIndex } = applyCodeInput(empty(), 0, '834271');
    expect(code.join('')).toBe('834271');
    expect(focusIndex).toBe(5);
  });

  it('places a whole code from the first box wherever it was pasted', () => {
    expect(applyCodeInput(empty(), 3, '834271').code.join('')).toBe('834271');
  });

  it('ignores spaces and dashes in a pasted code', () => {
    expect(applyCodeInput(empty(), 0, ' 834-271 ').code.join('')).toBe('834271');
  });

  it('pastes a whole code over a box that already holds a digit', () => {
    const start = ['3', '', '', '', '', ''];
    expect(applyCodeInput(start, 0, '3834271').code.join('')).toBe('834271');
    expect(applyCodeInput(start, 0, '8342713').code.join('')).toBe('834271');
  });

  it('keeps every digit when a paste replaces a selected digit', () => {
    // The old "8" was selected, so the box receives exactly the code.
    const start = ['8', '', '', '', '', ''];
    expect(applyCodeInput(start, 0, '834271').code.join('')).toBe('834271');
  });

  it('spreads a partial paste into a filled box as received', () => {
    // "3" + pasted "83" and a selected "3" replaced by "383" look the same;
    // either way every digit lands, none is read as typing over.
    const { code } = applyCodeInput(['3', '', '', '', '', ''], 0, '383');
    expect(code.slice(0, 3)).toEqual(['3', '8', '3']);
    expect(applyCodeInput(['3', '', '', '', '', ''], 0, '342').code.slice(0, 3)).toEqual(['3', '4', '2']);
  });

  it('spreads a partial paste from the box it landed in', () => {
    const { code, focusIndex } = applyCodeInput(['8', '3', '', '', '', ''], 2, '427');
    expect(code).toEqual(['8', '3', '4', '2', '7', '']);
    expect(focusIndex).toBe(5);
  });

  it('types one digit and moves to the next box', () => {
    const { code, focusIndex } = applyCodeInput(empty(), 0, '8');
    expect(code[0]).toBe('8');
    expect(focusIndex).toBe(1);
  });

  it('replaces a filled box when typing over it', () => {
    const start = ['8', '3', '', '', '', ''];
    expect(applyCodeInput(start, 1, '37').code[1]).toBe('7');
    expect(applyCodeInput(start, 1, '73').code[1]).toBe('7');
  });

  it('clears a box on delete and keeps focus', () => {
    const { code, focusIndex } = applyCodeInput(['8', '3', '', '', '', ''], 1, '');
    expect(code).toEqual(['8', '', '', '', '', '']);
    expect(focusIndex).toBeNull();
  });

  it('keeps focus on the last box after its digit', () => {
    expect(applyCodeInput(['8', '3', '4', '2', '7', ''], 5, '1').focusIndex).toBeNull();
  });
});
