// Confío IA operations. Kept out of the shared queries/mutations files and
// never merged into another query: an older server rejects only these.
import { gql } from '@apollo/client';

const MESSAGE_FIELDS = `
  id
  role
  body
  createdAt
  senderName
  modality
  actions { type destination }
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

export const GET_CONFIO_IA_PLAN = gql`
  query GetConfioIaPlan {
    confioIaPlan { ${PLAN_FIELDS} }
  }
`;

export const GET_CONFIO_IA_WAKE_WORD = gql`
  query GetConfioIaWakeWord {
    confioIaWakeWord { accessKey }
  }
`;

export const VERIFY_CONFIO_IA_PURCHASE = gql`
  mutation VerifyConfioIaPurchase($platform: String!, $signedTransaction: String, $purchaseToken: String) {
    verifyConfioIaPurchase(platform: $platform, signedTransaction: $signedTransaction, purchaseToken: $purchaseToken) {
      success
      error
      plan { ${PLAN_FIELDS} }
    }
  }
`;

export const START_CONFIO_IA_VOICE = gql`
  mutation StartConfioIaVoice($screen: String, $timezone: String) {
    startConfioIaVoice(screen: $screen, timezone: $timezone) {
      success
      error
      sessionId
      model
      minutesLeft
    }
  }
`;

export const CONNECT_CONFIO_IA_VOICE = gql`
  mutation ConnectConfioIaVoice($sessionId: ID!, $offerSdp: String!) {
    connectConfioIaVoice(sessionId: $sessionId, offerSdp: $offerSdp) {
      success
      error
      answerSdp
    }
  }
`;

export const RUN_CONFIO_IA_VOICE_TOOL = gql`
  mutation RunConfioIaVoiceTool($sessionId: ID!, $name: String!, $arguments: String) {
    runConfioIaVoiceTool(sessionId: $sessionId, name: $name, arguments: $arguments) {
      output
      handedOff
      keepGoing
    }
  }
`;

export const LOG_CONFIO_IA_VOICE = gql`
  mutation LogConfioIaVoice(
    $sessionId: ID!
    $transcript: [ConfioIaTranscriptInput!]
    $usageJson: String
    $ended: Boolean
  ) {
    logConfioIaVoice(sessionId: $sessionId, transcript: $transcript, usageJson: $usageJson, ended: $ended) {
      keepGoing
      minutesLeft
    }
  }
`;

export type ConfioIaPlan = {
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
  // Launch switches: when off, the app shows no call button / no IA+ at all.
  voiceCallsEnabled: boolean;
  plusSalesEnabled: boolean;
};

export const GET_CONFIO_IA_THREAD = gql`
  query GetConfioIaThread($limit: Int, $beforeId: ID, $contextKey: String) {
    confioIaThread(limit: $limit, beforeId: $beforeId, contextKey: $contextKey) {
      messages { ${MESSAGE_FIELDS} }
      hasMore
      mode
      remainingTurns
      enabled
      profile { ${PROFILE_FIELDS} }
    }
  }
`;

export const ASK_CONFIO_IA = gql`
  mutation AskConfioIa(
    $body: String
    $audioBase64: String
    $audioMimeType: String
    $audioDurationMs: Int
    $screen: String
    $timezone: String
  ) {
    askConfioIa(
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
      actions { type destination }
      mode
      remainingTurns
      dataChanged
    }
  }
`;

export const RETURN_TO_CONFIO_IA = gql`
  mutation ReturnToConfioIa {
    returnToConfioIa { success mode }
  }
`;

export const UPDATE_CONFIO_IA_PROFILE = gql`
  mutation UpdateConfioIaProfile(
    $mascot: String
    $mascotName: String
    $mascotColor: String
    $bubbleSide: String
    $bubbleHeight: Float
    $wakeWordEnabled: Boolean
  ) {
    updateConfioIaProfile(
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

export type ConfioIaAction = { type: string; destination?: string | null };

export type ConfioIaMessage = {
  id: string;
  role: 'user' | 'assistant' | 'team' | 'system';
  body: string;
  createdAt: string;
  senderName: string;
  modality?: string | null;
  actions: ConfioIaAction[];
  pending?: boolean;
};

export type ConfioIaProfile = {
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

export type ConfioIaPet = { id: string; imageUrl?: string | null; idea: string; source: string };

const PET_FIELDS = 'id imageUrl idea source';

export const GET_CONFIO_IA_PETS = gql`
  query GetConfioIaPets {
    confioIaPets { ${PET_FIELDS} }
  }
`;

export const CREATE_CONFIO_IA_PET = gql`
  mutation CreateConfioIaPet($idea: String, $photoBase64: String, $photoMimeType: String) {
    createConfioIaPet(idea: $idea, photoBase64: $photoBase64, photoMimeType: $photoMimeType) {
      success
      error
      creationsLeft
      pet { ${PET_FIELDS} }
    }
  }
`;

export const USE_CONFIO_IA_PET = gql`
  mutation UseConfioIaPet($petId: ID) {
    useConfioIaPet(petId: $petId) {
      success
      error
      profile { ${PROFILE_FIELDS} }
    }
  }
`;

export const DELETE_CONFIO_IA_PET = gql`
  mutation DeleteConfioIaPet($petId: ID!) {
    deleteConfioIaPet(petId: $petId) { success }
  }
`;
