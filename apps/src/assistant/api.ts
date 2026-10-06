// Confio Assistant operations. Kept out of the shared queries/mutations files and
// never merged into another query: an older server rejects only these.
import { gql } from '@apollo/client';

const MESSAGE_FIELDS = `
  id
  role
  body
  createdAt
  senderName
  modality
  actions { type destination target ticker label }
`;

const PROFILE_FIELDS =
  'mascot mascotName mascotColor bubbleHidden bubbleSide bubbleHeight wakeWordEnabled customPetId customPetUrl petCreationsLeft petCreationsPeriod';

const PLAN_FIELDS = `
  isPlus
  productId
  billingToken
  platform
  expiresAt
  autoRenew
  inGrace
  dailyTurns
  remainingTurns
  voiceMinutes
  voiceMinutesLeft
  wakeWordAvailable
  voiceCallsEnabled
  plusSalesEnabled
`;

export const GET_ASSISTANT_PLAN = gql`
  query GetAssistantPlan {
    assistantPlan { ${PLAN_FIELDS} }
  }
`;

export const GET_ASSISTANT_WAKE_WORD = gql`
  query GetAssistantWakeWord {
    assistantWakeWord { accessKey }
  }
`;

export const VERIFY_ASSISTANT_PURCHASE = gql`
  mutation VerifyAssistantPurchase($platform: String!, $signedTransaction: String, $purchaseToken: String) {
    verifyAssistantPurchase(platform: $platform, signedTransaction: $signedTransaction, purchaseToken: $purchaseToken) {
      success
      error
      plan { ${PLAN_FIELDS} }
    }
  }
`;

export const START_ASSISTANT_VOICE = gql`
  mutation StartAssistantVoice($screen: String, $timezone: String) {
    startAssistantVoice(screen: $screen, timezone: $timezone) {
      success
      error
      sessionId
      model
      minutesLeft
    }
  }
`;

export const CONNECT_ASSISTANT_VOICE = gql`
  mutation ConnectAssistantVoice($sessionId: ID!, $offerSdp: String!) {
    connectAssistantVoice(sessionId: $sessionId, offerSdp: $offerSdp) {
      success
      error
      answerSdp
    }
  }
`;

export const RUN_ASSISTANT_VOICE_TOOL = gql`
  mutation RunAssistantVoiceTool($sessionId: ID!, $name: String!, $arguments: String) {
    runAssistantVoiceTool(sessionId: $sessionId, name: $name, arguments: $arguments) {
      output
      handedOff
      keepGoing
    }
  }
`;

export const LOG_ASSISTANT_VOICE = gql`
  mutation LogAssistantVoice(
    $sessionId: ID!
    $transcript: [AssistantTranscriptInput!]
    $usageJson: String
    $ended: Boolean
  ) {
    logAssistantVoice(sessionId: $sessionId, transcript: $transcript, usageJson: $usageJson, ended: $ended) {
      keepGoing
      minutesLeft
    }
  }
`;

export type AssistantPlan = {
  isPlus: boolean;
  productId: string;
  billingToken: string;
  platform?: string | null;
  expiresAt?: string | null;
  autoRenew?: boolean | null;
  inGrace: boolean;
  dailyTurns: number;
  remainingTurns: number;
  voiceMinutes: number;
  voiceMinutesLeft: number;
  wakeWordAvailable: boolean;
  // Launch switches: when off, the app shows no call button / no Assistant+ at all.
  voiceCallsEnabled: boolean;
  plusSalesEnabled: boolean;
};

export const GET_ASSISTANT_THREAD = gql`
  query GetAssistantThread($limit: Int, $beforeId: ID, $contextKey: String) {
    assistantThread(limit: $limit, beforeId: $beforeId, contextKey: $contextKey) {
      messages { ${MESSAGE_FIELDS} }
      hasMore
      mode
      remainingTurns
      enabled
      profile { ${PROFILE_FIELDS} }
    }
  }
`;

export const ASK_ASSISTANT = gql`
  mutation AskAssistant(
    $body: String
    $audioBase64: String
    $audioMimeType: String
    $audioDurationMs: Int
    $screen: String
    $timezone: String
  ) {
    askAssistant(
      body: $body
      audioBase64: $audioBase64
      audioMimeType: $audioMimeType
      audioDurationMs: $audioDurationMs
      screen: $screen
      timezone: $timezone
    ) {
      success
      error
      transcript
      userMessage { ${MESSAGE_FIELDS} }
      reply { ${MESSAGE_FIELDS} }
      actions { type destination target ticker label }
      mode
      remainingTurns
      dataChanged
    }
  }
`;

export const RETURN_TO_ASSISTANT = gql`
  mutation ReturnToAssistant {
    returnToAssistant { success mode }
  }
`;

export const UPDATE_ASSISTANT_PROFILE = gql`
  mutation UpdateAssistantProfile(
    $mascot: String
    $mascotName: String
    $mascotColor: String
    $bubbleSide: String
    $bubbleHeight: Float
    $wakeWordEnabled: Boolean
  ) {
    updateAssistantProfile(
      mascot: $mascot
      mascotName: $mascotName
      mascotColor: $mascotColor
      bubbleSide: $bubbleSide
      bubbleHeight: $bubbleHeight
      wakeWordEnabled: $wakeWordEnabled
    ) {
      success
      profile { ${PROFILE_FIELDS} }
    }
  }
`;

export type AssistantAction = {
  type: string;
  destination?: string | null;
  target?: string | null;
  ticker?: string | null;
  label?: string | null;
};

export type AssistantMessage = {
  id: string;
  role: 'user' | 'assistant' | 'team' | 'system';
  body: string;
  createdAt: string;
  senderName: string;
  modality?: string | null;
  actions: AssistantAction[];
  pending?: boolean;
};

export type AssistantProfile = {
  mascot: string;
  mascotName: string;
  mascotColor: string;
  bubbleHidden: boolean;
  bubbleSide: 'left' | 'right' | string;
  bubbleHeight: number;
  wakeWordEnabled: boolean;
  customPetId?: string | null;
  customPetUrl?: string | null;
  petCreationsLeft: number;
  petCreationsPeriod: 'week' | 'day' | string;
};

export type AssistantPet = { id: string; imageUrl?: string | null; idea: string; source: string };

const PET_FIELDS = 'id imageUrl idea source';

export const GET_ASSISTANT_PETS = gql`
  query GetAssistantPets {
    assistantPets { ${PET_FIELDS} }
  }
`;

export const CREATE_ASSISTANT_PET = gql`
  mutation CreateAssistantPet($idea: String, $photoBase64: String, $photoMimeType: String) {
    createAssistantPet(idea: $idea, photoBase64: $photoBase64, photoMimeType: $photoMimeType) {
      success
      error
      creationsLeft
      pet { ${PET_FIELDS} }
    }
  }
`;

export const USE_ASSISTANT_PET = gql`
  mutation UseAssistantPet($petId: ID) {
    useAssistantPet(petId: $petId) {
      success
      error
      profile { ${PROFILE_FIELDS} }
    }
  }
`;

export const DELETE_ASSISTANT_PET = gql`
  mutation DeleteAssistantPet($petId: ID!) {
    deleteAssistantPet(petId: $petId) { success }
  }
`;

// Ranked by the person's situation on the server. Its own query: an older
// server without it must not break anything (the app keeps its built-in list).
export const GET_ASSISTANT_SUGGESTIONS = gql`
  query GetAssistantSuggestions($screen: String, $contextKey: String) {
    assistantSuggestions(screen: $screen, contextKey: $contextKey) {
      hints { id text prompt kind }
      starters { id text prompt kind }
      probe { id question answers { key label } }
    }
  }
`;

export const ANSWER_ASSISTANT_PROBE = gql`
  mutation AnswerAssistantProbe($probeId: String!, $answer: String!) {
    answerAssistantProbe(probeId: $probeId, answer: $answer) { success error label }
  }
`;

export type AssistantSuggestion = { id: string; text: string; prompt: string; kind: 'prompt' | 'probe' | 'picker' | string };
export type AssistantProbe = { id: string; question: string; answers: { key: string; label: string }[] };
