/**
 * Moving a phone number between accounts is consequential, so the prompt must
 * name both accounts in full, say that funds stay behind, bind every answer to
 * the prompt it was rendered for, and lock itself while the change commits.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Modal, Text } from 'react-native';

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('react-native-vector-icons/MaterialCommunityIcons', () => 'Icon');

import { PhoneRelinkModal } from '../PhoneRelinkModal';
import type { PhoneRelinkPrompt } from '../../hooks/usePhoneRelinkPrompt';

const confirmation = { token: 'signed-token', accounts: [{ email: 'previous@example.com', username: 'previous' }] };

const makePrompt = (overrides: Partial<PhoneRelinkPrompt> = {}): PhoneRelinkPrompt => ({
  id: 7,
  confirmation,
  phase: 'ask',
  replaced: false,
  ...overrides,
});

type ModalProps = React.ComponentProps<typeof PhoneRelinkModal>;

const element = (props: Partial<Omit<ModalProps, 'onAnswer'>> & Pick<ModalProps, 'onAnswer'>) => (
  <PhoneRelinkModal
    prompt={makePrompt()}
    phoneLabel="+58 4121234567"
    currentAccount={{ email: 'current@example.com', username: 'current' }}
    {...props}
  />
);

const render = (props: Partial<Omit<ModalProps, 'onAnswer'>> = {}) => {
  const onAnswer = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(element({ onAnswer, ...props }));
  });
  return { tree, onAnswer };
};

const button = (tree: renderer.ReactTestRenderer, label: string) => {
  const [match] = tree.root.findAll(
    node => node.props.accessibilityLabel === label && typeof node.props.onPress === 'function',
  );
  expect(match).toBeDefined();
  return match;
};

const press = (tree: renderer.ReactTestRenderer, label: string) => {
  const target = button(tree, label);
  act(() => target.props.onPress());
};

const text = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());

describe('PhoneRelinkModal', () => {
  it('names the number, both accounts, and that funds stay behind', () => {
    const { tree } = render();
    expect(text(tree)).toContain('+58 4121234567');
    expect(text(tree)).toContain('previous@example.com');
    expect(text(tree)).toContain('@previous');
    expect(text(tree)).toContain('current@example.com');
    expect(text(tree)).toContain('Los fondos y el historial se quedan en la cuenta anterior.');
  });

  it('never truncates account identifiers', () => {
    const { tree } = render();
    const identifiers = tree.root.findAllByType(Text).filter(
      node => ['previous@example.com', '@previous'].includes(node.props.children),
    );
    expect(identifiers).toHaveLength(2);
    identifiers.forEach(node => expect(node.props.numberOfLines).toBeUndefined());
  });

  it('answers with the rendered prompt id', () => {
    const { tree, onAnswer } = render();
    press(tree, 'Confirmar cambio');
    expect(onAnswer).toHaveBeenLastCalledWith(7, true);
    press(tree, 'Cancelar');
    expect(onAnswer).toHaveBeenLastCalledWith(7, false);
  });

  it('a button rendered for an earlier prompt keeps answering for that prompt', () => {
    const { tree, onAnswer } = render();
    const staleOnPress = button(tree, 'Confirmar cambio').props.onPress;
    act(() => {
      tree.update(element({
        onAnswer,
        prompt: makePrompt({ id: 8, replaced: true, confirmation: { token: 'b', accounts: [{ email: 'other@example.com', username: 'other' }] } }),
      }));
    });
    act(() => staleOnPress());
    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenLastCalledWith(7, true);
  });

  it('the Android back gesture cancels while asking', () => {
    const { tree, onAnswer } = render();
    act(() => tree.root.findByType(Modal).props.onRequestClose());
    expect(onAnswer).toHaveBeenCalledWith(7, false);
  });

  it('locks while the approved change is being confirmed', () => {
    const { tree, onAnswer } = render({ prompt: makePrompt({ phase: 'confirming' }) });
    expect(button(tree, 'Confirmar cambio').props.accessibilityState).toMatchObject({ busy: true, disabled: true });
    expect(button(tree, 'Cancelar').props.accessibilityState).toMatchObject({ disabled: true });
    act(() => tree.root.findByType(Modal).props.onRequestClose());
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it('offers a retry in place when confirming failed', () => {
    const { tree, onAnswer } = render({ prompt: makePrompt({ phase: 'retry' }) });
    expect(text(tree)).toContain('No pudimos confirmar el cambio');
    press(tree, 'Reintentar');
    expect(onAnswer).toHaveBeenLastCalledWith(7, true);
    press(tree, 'Cancelar');
    expect(onAnswer).toHaveBeenLastCalledWith(7, false);
  });

  it('warns when the accounts changed after an earlier approval', () => {
    expect(text(render().tree)).not.toContain('cambiaron');
    expect(text(render({ prompt: makePrompt({ replaced: true }) }).tree))
      .toContain('Las cuentas vinculadas a este número cambiaron');
  });

  it('degrades gracefully when account details are missing', () => {
    const { tree } = render({
      prompt: makePrompt({ confirmation: { token: 't', accounts: [{ email: '', username: '' }] } }),
      currentAccount: null,
    });
    expect(text(tree)).toContain('Correo no disponible');
    expect(text(tree)).toContain('La cuenta con la que iniciaste sesión');
  });

  it('renders nothing without a prompt', () => {
    expect(text(render({ prompt: null }).tree)).not.toContain('¿Mover este número a tu cuenta?');
  });
});
