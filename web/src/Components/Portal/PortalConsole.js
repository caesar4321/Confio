import React, { useEffect, useMemo, useRef, useState } from 'react';
import { gql, useMutation, useQuery } from '@apollo/client';

import './PortalConsole.css';

const SUPPORT_POLL_INTERVAL_MS = 5000;

const GET_PORTAL_ME = gql`
  query GetPortalMe {
    me {
      id
      username
      firstName
      lastName
      email
      isStaff
      isOtpVerified
    }
  }
`;

const GET_PORTAL_SUPPORT_CONVERSATIONS = gql`
  query GetPortalSupportConversations($status: String) {
    portalSupportConversations(status: $status) {
      id
      customerName
      customerEmail
      contextLabel
      status
      assignedToName
      lastMessageAt
      lastPreview
      unreadCount
      messages {
        id
        senderType
        senderName
        body
        createdAt
      }
    }
  }
`;

const GET_PORTAL_CONTENT_ITEMS = gql`
  query GetPortalContentItems($channelSlug: String, $status: String) {
    portalContentItems(channelSlug: $channelSlug, status: $status) {
      id
      channelSlug
      channelTitle
      itemType
      status
      title
      body
      tag
      publishedAt
      visibilityPolicy
      sendPush
      sendInApp
      pushSentAt
      surfaces
      metadata
    }
  }
`;

const PORTAL_SEND_SUPPORT_REPLY = gql`
  mutation PortalSendSupportReply($conversationId: ID!, $body: String!) {
    portalSendSupportReply(conversationId: $conversationId, body: $body) {
      success
      conversation {
        id
      }
    }
  }
`;

const PORTAL_SET_SUPPORT_STATUS = gql`
  mutation PortalSetSupportConversationStatus($conversationId: ID!, $status: String!) {
    portalSetSupportConversationStatus(conversationId: $conversationId, status: $status) {
      success
      conversation {
        id
        status
      }
    }
  }
`;

const PORTAL_SAVE_CONTENT_ITEM = gql`
  mutation PortalSaveContentItem(
    $contentItemId: ID
    $channelSlug: String!
    $itemType: String!
    $title: String
    $body: String
    $tag: String
    $status: String!
    $publishedAt: DateTime
    $visibilityPolicy: String
    $sendPush: Boolean
    $sendInApp: Boolean
    $metadata: JSONString
    $surfaces: [String!]
  ) {
    portalSaveContentItem(
      contentItemId: $contentItemId
      channelSlug: $channelSlug
      itemType: $itemType
      title: $title
      body: $body
      tag: $tag
      status: $status
      publishedAt: $publishedAt
      visibilityPolicy: $visibilityPolicy
      sendPush: $sendPush
      sendInApp: $sendInApp
      metadata: $metadata
      surfaces: $surfaces
    ) {
      success
      contentItem {
        id
      }
    }
  }
`;

const REQUEST_PUBLICATION_IMAGE_UPLOAD = gql`
  mutation RequestPublicationImageUpload($filename: String, $contentType: String) {
    requestPublicationImageUpload(filename: $filename, contentType: $contentType) {
      success
      error
      upload {
        url
        key
        method
        fields
        expiresIn
        publicUrl
      }
    }
  }
`;

function createEmptyDraft() {
  return {
    id: null,
    channelSlug: 'julian',
    itemType: 'TEXT',
    status: 'DRAFT',
    publishedAt: '',
    visibilityPolicy: 'FROM_PUBLISH_TIME',
    title: '',
    body: '',
    blocks: [createParagraphBlock('')],
    tag: '',
    sendPush: false,
    sendInApp: true,
    surfaces: ['CHANNEL'],
    tagColor: '',
    tiktokUrl: '',
    instagramUrl: '',
    youtubeUrl: '',
    metadataText: '{}',
  };
}

const TAG_COLOR_OPTIONS = [
  { value: '', label: 'Automático' },
  { value: '#1DB587', label: 'Verde Producto' },
  { value: '#7C3AED', label: 'Morado KYC' },
  { value: '#F97316', label: 'Naranja Preventa' },
  { value: '#F59E0B', label: 'Amarillo Mercado' },
  { value: '#FF4444', label: 'Rojo Video' },
  { value: '#2563EB', label: 'Azul' },
];

const PUBLICATION_IMAGE_MAX_LANDSCAPE = 1440;
const PUBLICATION_IMAGE_MAX_PORTRAIT = 1280;
const PUBLICATION_IMAGE_TARGET_BYTES = 300 * 1024;
const PUBLICATION_IMAGE_MAX_BYTES = 700 * 1024;

function createParagraphBlock(text = '') {
  return {
    id: `paragraph-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: 'paragraph',
    text,
  };
}

function createImageBlock(image) {
  return {
    id: `image-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: 'image',
    image,
  };
}

function normalizeBlocks(metadata, fallbackBody) {
  const existingBlocks = Array.isArray(metadata?.blocks) ? metadata.blocks : [];
  if (existingBlocks.length > 0) {
    return existingBlocks.map((block, index) => ({
      id: block.id || `${block.type || 'block'}-${index}`,
      ...block,
    }));
  }

  const nextBlocks = [];
  if (fallbackBody) {
    nextBlocks.push(createParagraphBlock(fallbackBody));
  }
  if (metadata?.image?.url) {
    nextBlocks.push(createImageBlock(metadata.image));
  }
  return nextBlocks.length > 0 ? nextBlocks : [createParagraphBlock('')];
}

function stripInlineLinks(text = '') {
  return text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '$1');
}

function parsePortalMetadata(metadata) {
  if (!metadata) {
    return {};
  }
  if (typeof metadata === 'string') {
    try {
      return JSON.parse(metadata);
    } catch (error) {
      console.warn('Failed to parse portal content metadata', error);
      return {};
    }
  }
  return metadata;
}

function formatDateTime(value) {
  if (!value) {
    return '';
  }
  return new Intl.DateTimeFormat('es-AR', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value));
}

function toDateTimeLocalValue(value) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function fromDateTimeLocalValue(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
}

function getBackendOrigin() {
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    return 'http://localhost:8000';
  }
  const graphqlUrl = process.env.REACT_APP_GRAPHQL_URL;
  if (graphqlUrl) {
    try {
      return new URL(graphqlUrl, window.location.origin).origin;
    } catch (error) {
      console.warn('Failed to parse REACT_APP_GRAPHQL_URL', error);
    }
  }
  return window.location.origin;
}

function buildPortalAuthUrl(backendOrigin, path) {
  if (window.location.origin === backendOrigin) {
    return `${backendOrigin}${path}`;
  }
  return `${backendOrigin}${path}?frontend_origin=${encodeURIComponent(window.location.origin)}`;
}

function loadImageFromUrl(url) {
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('No se pudo leer la imagen.'));
    image.src = url;
  });
}

async function compressPublicationImage(file) {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await loadImageFromUrl(objectUrl);
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('No se pudo preparar la compresión.');
    }

    const isLandscape = image.width >= image.height;
    const maxDimension = isLandscape ? PUBLICATION_IMAGE_MAX_LANDSCAPE : PUBLICATION_IMAGE_MAX_PORTRAIT;
    const scale = Math.min(1, maxDimension / Math.max(image.width, image.height));
    const width = Math.max(1, Math.round(image.width * scale));
    const height = Math.max(1, Math.round(image.height * scale));

    canvas.width = width;
    canvas.height = height;
    ctx.drawImage(image, 0, 0, width, height);

    const qualities = [0.82, 0.78, 0.74, 0.7];
    let selectedBlob = null;
    for (const quality of qualities) {
      // eslint-disable-next-line no-await-in-loop
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob((nextBlob) => {
          if (nextBlob) {
            resolve(nextBlob);
          } else {
            reject(new Error('No se pudo exportar la imagen.'));
          }
        }, 'image/webp', quality);
      });
      selectedBlob = blob;
      if (blob.size <= PUBLICATION_IMAGE_TARGET_BYTES) {
        break;
      }
    }

    if (!selectedBlob) {
      throw new Error('No se pudo comprimir la imagen.');
    }
    if (selectedBlob.size > PUBLICATION_IMAGE_MAX_BYTES) {
      throw new Error('La imagen quedó demasiado pesada. Usa una imagen más liviana.');
    }

    return {
      blob: selectedBlob,
      width,
      height,
      filename: `${file.name.replace(/\.[^.]+$/, '') || 'publication'}.webp`,
      contentType: 'image/webp',
    };
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function uploadPublicationImage(upload, blob, filename, contentType) {
  if (upload.method !== 'POST') {
    throw new Error('Método de subida no soportado.');
  }
  const normalizedFields =
    typeof upload.fields === 'string'
      ? JSON.parse(upload.fields || '{}')
      : (upload.fields || {});
  const formData = new FormData();
  Object.entries(normalizedFields).forEach(([key, value]) => {
    formData.append(key, value);
  });
  formData.append('file', blob, filename);

  const response = await fetch(upload.url, {
    method: 'POST',
    body: formData,
    headers: {
      Accept: 'application/json',
    },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`Upload failed (${response.status}): ${text}`);
  }
  return { contentType };
}

export default function PortalConsole() {
  const [activeTab, setActiveTab] = useState('support');
  const [supportStatus, setSupportStatus] = useState('OPEN');
  const [contentChannelFilter, setContentChannelFilter] = useState('');
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [replyDraft, setReplyDraft] = useState('');
  const [draft, setDraft] = useState(createEmptyDraft);
  const [imageUploadError, setImageUploadError] = useState('');
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const supportThreadRef = useRef(null);

  const meQuery = useQuery(GET_PORTAL_ME, {
    fetchPolicy: 'network-only',
  });
  const isOtpVerified = Boolean(meQuery.data?.me?.isOtpVerified);
  const shouldPollSupport = activeTab === 'support' && Boolean(meQuery.data?.me?.isStaff) && isOtpVerified;
  const supportQuery = useQuery(GET_PORTAL_SUPPORT_CONVERSATIONS, {
    variables: { status: supportStatus },
    skip: !meQuery.data?.me?.isStaff || !isOtpVerified,
    fetchPolicy: 'network-only',
    pollInterval: shouldPollSupport ? SUPPORT_POLL_INTERVAL_MS : 0,
  });
  const contentQuery = useQuery(GET_PORTAL_CONTENT_ITEMS, {
    variables: { channelSlug: contentChannelFilter || null, status: null },
    skip: !meQuery.data?.me?.isStaff || !isOtpVerified,
    fetchPolicy: 'network-only',
  });

  const [sendReply, sendReplyState] = useMutation(PORTAL_SEND_SUPPORT_REPLY, {
    refetchQueries: [{ query: GET_PORTAL_SUPPORT_CONVERSATIONS, variables: { status: supportStatus } }],
  });
  const [setSupportStatusMutation] = useMutation(PORTAL_SET_SUPPORT_STATUS, {
    refetchQueries: [{ query: GET_PORTAL_SUPPORT_CONVERSATIONS, variables: { status: supportStatus } }],
  });
  const [saveContentItem, saveContentState] = useMutation(PORTAL_SAVE_CONTENT_ITEM, {
    refetchQueries: [{ query: GET_PORTAL_CONTENT_ITEMS, variables: { channelSlug: contentChannelFilter || null, status: null } }],
  });
  const [requestPublicationImageUpload] = useMutation(REQUEST_PUBLICATION_IMAGE_UPLOAD);

  const conversations = supportQuery.data?.portalSupportConversations || [];
  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) || conversations[0] || null,
    [conversations, activeConversationId]
  );
  const contentItems = contentQuery.data?.portalContentItems || [];
  const backendOrigin = getBackendOrigin();
  const loginUrl = buildPortalAuthUrl(backendOrigin, '/portal/login/');
  const logoutUrl = buildPortalAuthUrl(backendOrigin, '/portal/logout/');
  const setup2faUrl = buildPortalAuthUrl(backendOrigin, '/portal/setup-2fa/');

  useEffect(() => {
    if (!activeConversationId && conversations[0]?.id) {
      setActiveConversationId(conversations[0].id);
    }
  }, [activeConversationId, conversations]);

  useEffect(() => {
    if (activeTab !== 'support' || !activeConversation) {
      return;
    }
    if (!supportThreadRef.current) {
      return;
    }
    requestAnimationFrame(() => {
      supportThreadRef.current.scrollTop = supportThreadRef.current.scrollHeight;
    });
  }, [activeTab, activeConversation?.id, activeConversation?.messages?.length]);

  const startNewDraft = () => setDraft(createEmptyDraft());

  const editContentItem = (item) => {
    const metadata = parsePortalMetadata(item.metadata);
    const platformLinks = metadata.platform_links || {};
    setDraft({
      id: item.id,
      channelSlug: item.channelSlug,
      itemType: item.itemType,
      status: item.status,
      publishedAt: toDateTimeLocalValue(item.publishedAt),
      visibilityPolicy: item.visibilityPolicy || 'FROM_PUBLISH_TIME',
      title: item.title || '',
      body: item.body || '',
      blocks: normalizeBlocks(metadata, item.body || ''),
      tag: item.tag || '',
      sendPush: Boolean(item.sendPush),
      sendInApp: Boolean(item.sendInApp),
      surfaces: item.surfaces?.length ? item.surfaces : ['CHANNEL'],
      tagColor: metadata.tag_color || '',
      tiktokUrl: platformLinks.TikTok || '',
      instagramUrl: platformLinks.Instagram || '',
      youtubeUrl: platformLinks.YouTube || '',
      metadataText: JSON.stringify(metadata || {}, null, 2),
    });
    setImageUploadError('');
  };

  const handlePublicationImageSelected = async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    if (!file.type.startsWith('image/')) {
      setImageUploadError('Selecciona una imagen válida.');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setImageUploadError('La imagen no puede superar 10 MB antes de comprimir.');
      return;
    }

    setIsUploadingImage(true);
    setImageUploadError('');
    try {
      const compressed = await compressPublicationImage(file);
      const response = await requestPublicationImageUpload({
        variables: {
          filename: compressed.filename,
          contentType: compressed.contentType,
        },
      });
      const payload = response.data?.requestPublicationImageUpload;
      if (!payload?.success || !payload?.upload) {
        throw new Error(payload?.error || 'No se pudo preparar la subida.');
      }

      await uploadPublicationImage(
        payload.upload,
        compressed.blob,
        compressed.filename,
        compressed.contentType
      );

      setDraft((current) => ({
        ...current,
        blocks: [
          ...current.blocks,
          createImageBlock({
            key: payload.upload.key,
            url: payload.upload.publicUrl,
            width: compressed.width,
            height: compressed.height,
          }),
        ],
      }));
    } catch (error) {
      setImageUploadError(error.message || 'No se pudo subir la imagen.');
    } finally {
      event.target.value = '';
      setIsUploadingImage(false);
    }
  };

  const updateBlock = (blockId, patch) => {
    setDraft((current) => ({
      ...current,
      blocks: current.blocks.map((block) => (
        block.id === blockId ? { ...block, ...patch } : block
      )),
    }));
  };

  const removeBlock = (blockId) => {
    setDraft((current) => {
      const nextBlocks = current.blocks.filter((block) => block.id !== blockId);
      return {
        ...current,
        blocks: nextBlocks.length > 0 ? nextBlocks : [createParagraphBlock('')],
      };
    });
  };

  const moveBlock = (blockId, direction) => {
    setDraft((current) => {
      const index = current.blocks.findIndex((block) => block.id === blockId);
      if (index < 0) {
        return current;
      }
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= current.blocks.length) {
        return current;
      }
      const nextBlocks = [...current.blocks];
      const [block] = nextBlocks.splice(index, 1);
      nextBlocks.splice(targetIndex, 0, block);
      return { ...current, blocks: nextBlocks };
    });
  };

  const addParagraphBlock = () => {
    setDraft((current) => ({
      ...current,
      blocks: [...current.blocks, createParagraphBlock('')],
    }));
  };

  const submitReply = async () => {
    if (!activeConversation || !replyDraft.trim()) {
      return;
    }
    await sendReply({
      variables: {
        conversationId: activeConversation.id,
        body: replyDraft.trim(),
      },
    });
    setReplyDraft('');
  };

  const toggleConversationStatus = async () => {
    if (!activeConversation) {
      return;
    }
    await setSupportStatusMutation({
      variables: {
        conversationId: activeConversation.id,
        status: activeConversation.status === 'OPEN' ? 'CLOSED' : 'OPEN',
      },
    });
  };

  const submitContent = async (event) => {
    event.preventDefault();
    let metadata = {};
    try {
      metadata = draft.metadataText.trim() ? JSON.parse(draft.metadataText) : {};
    } catch (error) {
      window.alert('Metadata debe ser JSON válido.');
      return;
    }

    if (draft.tagColor) {
      metadata.tag_color = draft.tagColor;
    } else {
      delete metadata.tag_color;
    }

    const platformLinks = {};
    if (draft.tiktokUrl.trim()) {
      platformLinks.TikTok = draft.tiktokUrl.trim();
    }
    if (draft.instagramUrl.trim()) {
      platformLinks.Instagram = draft.instagramUrl.trim();
    }
    if (draft.youtubeUrl.trim()) {
      platformLinks.YouTube = draft.youtubeUrl.trim();
    }

    if (Object.keys(platformLinks).length > 0) {
      metadata.platform_links = platformLinks;
      metadata.platforms = Object.keys(platformLinks);
    } else {
      delete metadata.platform_links;
      delete metadata.platforms;
    }

    const cleanedBlocks = draft.blocks
      .map((block) => {
        if (block.type === 'paragraph') {
          return {
            id: block.id,
            type: 'paragraph',
            text: block.text || '',
          };
        }
        if (block.type === 'image' && block.image?.url) {
          return {
            id: block.id,
            type: 'image',
            image: block.image,
          };
        }
        return null;
      })
      .filter(Boolean);

    metadata.blocks = cleanedBlocks;
    const previewImageBlock = cleanedBlocks.find((block) => block.type === 'image' && block.image?.url);
    if (previewImageBlock?.image) {
      metadata.image = previewImageBlock.image;
    } else {
      delete metadata.image;
    }

    const bodyPreview = cleanedBlocks
      .filter((block) => block.type === 'paragraph')
      .map((block) => stripInlineLinks(block.text || '').trim())
      .filter(Boolean)
      .join('\n\n');

    await saveContentItem({
      variables: {
        contentItemId: draft.id,
        channelSlug: draft.channelSlug,
        itemType: draft.itemType,
        title: draft.title || null,
        body: bodyPreview || null,
        tag: draft.tag || null,
        status: draft.status,
        publishedAt: fromDateTimeLocalValue(draft.publishedAt),
        visibilityPolicy: draft.visibilityPolicy,
        sendPush: draft.sendPush,
        sendInApp: draft.sendInApp,
        metadata: JSON.stringify(metadata),
        surfaces: draft.surfaces,
      },
    });
    startNewDraft();
    setImageUploadError('');
  };

  const me = meQuery.data?.me;
  const isAuthenticated = Boolean(me?.id);
  const isStaff = Boolean(me?.isStaff);

  if (meQuery.loading) {
    return <div className="portal-shell"><div className="portal-card">Cargando portal...</div></div>;
  }

  if (!isAuthenticated) {
    return (
      <div className="portal-shell">
        <div className="portal-gate">
          <div className="portal-eyebrow">Portal interno</div>
          <h1>Confío Publishing & Support</h1>
          <p>Inicia sesión para entrar al portal.</p>
          <button
            className="portal-primary-button"
            onClick={() => window.location.assign(loginUrl)}
          >
            Iniciar sesión
          </button>
        </div>
      </div>
    );
  }

  if (!isStaff) {
    return (
      <div className="portal-shell">
        <div className="portal-gate">
          <div className="portal-eyebrow">Portal interno</div>
          <h1>Acceso restringido</h1>
          <p>Tu usuario inició sesión correctamente, pero no tiene permisos de staff para este portal.</p>
          <div className="portal-inline-actions">
            <button
              className="portal-secondary-button"
              onClick={() => window.location.assign(logoutUrl)}
            >
              Cerrar sesión
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!isOtpVerified) {
    return (
      <div className="portal-shell">
        <div className="portal-gate">
          <div className="portal-eyebrow">Portal interno</div>
          <h1>Configura tu autenticación en dos pasos</h1>
          <p>Este portal solo está disponible para staff con 2FA activa.</p>
          <div className="portal-inline-actions">
            <button
              className="portal-primary-button"
              onClick={() => window.location.assign(setup2faUrl)}
            >
              Configurar 2FA
            </button>
            <button
              className="portal-secondary-button"
              onClick={() => window.location.assign(logoutUrl)}
            >
              Cerrar sesión
            </button>
          </div>
        </div>
      </div>
    );
  }

  const handleLogout = () => window.location.assign(logoutUrl);

  return (
    <div className="portal-shell">
      <div className="portal-header">
        <div>
          <div className="portal-eyebrow">confio.lat/portal</div>
          <h1>Portal editorial y soporte</h1>
        </div>
        <div className="portal-user-chip">
          {me.firstName || me.username}
        </div>
      </div>

      <div className="portal-tabs">
        <button className={activeTab === 'support' ? 'active' : ''} onClick={() => setActiveTab('support')}>Soporte</button>
        <button className={activeTab === 'content' ? 'active' : ''} onClick={() => setActiveTab('content')}>Publicaciones</button>
        <button className="portal-ghost-tab" onClick={handleLogout}>Cerrar sesión</button>
      </div>

      {activeTab === 'support' ? (
        <div className="portal-grid portal-grid-support">
          <section className="portal-panel">
            <div className="portal-panel-header">
              <h2>Conversaciones</h2>
              <select value={supportStatus} onChange={(event) => setSupportStatus(event.target.value)}>
                <option value="OPEN">Abiertas</option>
                <option value="CLOSED">Cerradas</option>
              </select>
            </div>
            <div className="portal-list">
              {conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  className={`portal-list-row ${activeConversation?.id === conversation.id ? 'selected' : ''}`}
                  onClick={() => setActiveConversationId(conversation.id)}
                >
                  <div className="portal-list-title-row">
                    <strong>{conversation.customerName}</strong>
                    <span>{conversation.unreadCount}</span>
                  </div>
                  <div className="portal-list-meta">{conversation.contextLabel}</div>
                  <div className="portal-list-preview">{conversation.lastPreview}</div>
                </button>
              ))}
            </div>
          </section>

          <section className="portal-panel">
            {activeConversation ? (
              <>
                <div className="portal-panel-header portal-thread-header">
                  <div>
                    <h2>{activeConversation.customerName}</h2>
                    <div className="portal-list-meta">
                      {activeConversation.contextLabel}
                      {activeConversation.customerEmail ? ` · ${activeConversation.customerEmail}` : ''}
                    </div>
                  </div>
                  <button className="portal-secondary-button" onClick={toggleConversationStatus}>
                    {activeConversation.status === 'OPEN' ? 'Cerrar' : 'Reabrir'}
                  </button>
                </div>
                <div className="portal-thread" ref={supportThreadRef}>
                  {activeConversation.messages.map((message) => (
                    <div
                      key={message.id}
                      className={`portal-message ${message.senderType === 'USER' ? 'from-user' : 'from-agent'}`}
                    >
                      <div className="portal-message-sender">{message.senderName}</div>
                      <div className="portal-message-body">{message.body}</div>
                      <div className="portal-message-time">{formatDateTime(message.createdAt)}</div>
                    </div>
                  ))}
                </div>
                <div className="portal-reply-box">
                  <textarea
                    value={replyDraft}
                    onChange={(event) => setReplyDraft(event.target.value)}
                    placeholder="Responder al usuario..."
                  />
                  <button
                    className="portal-primary-button"
                    onClick={submitReply}
                    disabled={!replyDraft.trim() || sendReplyState.loading}
                  >
                    Enviar
                  </button>
                </div>
              </>
            ) : (
              <div className="portal-empty">No hay conversaciones en esta vista.</div>
            )}
          </section>
        </div>
      ) : (
        <div className="portal-grid portal-grid-content">
          <section className="portal-panel">
            <div className="portal-panel-header">
              <h2>Publicaciones</h2>
              <div className="portal-inline-actions">
                <select value={contentChannelFilter} onChange={(event) => setContentChannelFilter(event.target.value)}>
                  <option value="">Todos</option>
                  <option value="julian">Julian</option>
                  <option value="confio-news">Confío News</option>
                </select>
                <button className="portal-secondary-button" onClick={startNewDraft}>Nueva</button>
              </div>
            </div>
            <div className="portal-list">
              {contentItems.map((item) => (
                <button key={item.id} className="portal-list-row" onClick={() => editContentItem(item)}>
                  <div className="portal-list-title-row">
                    <strong>{item.title || 'Sin título'}</strong>
                    <span>{item.status}</span>
                  </div>
                  <div className="portal-list-meta">{item.channelTitle} · {item.itemType}</div>
                  <div className="portal-list-preview">{item.body}</div>
                </button>
              ))}
            </div>
          </section>

          <section className="portal-panel">
            <div className="portal-panel-header">
              <h2>{draft.id ? 'Editar publicación' : 'Nueva publicación'}</h2>
            </div>
            <form className="portal-form" onSubmit={submitContent}>
              <label>
                Canal
                <select value={draft.channelSlug} onChange={(event) => setDraft((current) => ({ ...current, channelSlug: event.target.value }))}>
                  <option value="julian">Julian</option>
                  <option value="confio-news">Confío News</option>
                </select>
              </label>
              <div className="portal-form-row">
                <label>
                  Tipo
                  <select value={draft.itemType} onChange={(event) => setDraft((current) => ({ ...current, itemType: event.target.value }))}>
                    <option value="TEXT">Text</option>
                    <option value="NEWS">News</option>
                    <option value="VIDEO">Video</option>
                  </select>
                </label>
                <label>
                  Estado
                  <select value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value }))}>
                    <option value="DRAFT">Draft</option>
                    <option value="SCHEDULED">Scheduled</option>
                    <option value="PUBLISHED">Published</option>
                    <option value="ARCHIVED">Archived</option>
                  </select>
                </label>
              </div>
              <label>
                Fecha y hora
                <input
                  type="datetime-local"
                  value={draft.publishedAt}
                  onChange={(event) => setDraft((current) => ({ ...current, publishedAt: event.target.value }))}
                />
              </label>
              <label>
                Visibilidad en canal
                <select
                  value={draft.visibilityPolicy}
                  onChange={(event) => setDraft((current) => ({ ...current, visibilityPolicy: event.target.value }))}
                >
                  <option value="FROM_PUBLISH_TIME">Desde publicación</option>
                  <option value="BACKLOG">Backlog</option>
                  <option value="PINNED">Pinned</option>
                </select>
              </label>
              <label>
                Título
                <input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} />
              </label>
              <div className="portal-block-editor">
                <div className="portal-form-image-header">
                  <div>
                    <strong>Contenido del detalle</strong>
                    <div className="portal-form-image-copy">
                      Agrega párrafos e imágenes en el orden que quieras mostrar en el detalle.
                    </div>
                  </div>
                  <div className="portal-inline-actions">
                    <button type="button" className="portal-secondary-button" onClick={addParagraphBlock}>
                      Agregar texto
                    </button>
                    <label className="portal-upload-button">
                      {isUploadingImage ? 'Subiendo...' : 'Agregar imagen'}
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        onChange={handlePublicationImageSelected}
                        disabled={isUploadingImage}
                      />
                    </label>
                  </div>
                </div>
                <div className="portal-block-list">
                  {draft.blocks.map((block, index) => (
                    <div key={block.id} className="portal-block-item">
                      <div className="portal-block-toolbar">
                        <span className="portal-upload-meta">
                          {block.type === 'paragraph' ? `Texto ${index + 1}` : `Imagen ${index + 1}`}
                        </span>
                        <div className="portal-inline-actions">
                          <button type="button" className="portal-secondary-button" onClick={() => moveBlock(block.id, 'up')}>
                            Subir
                          </button>
                          <button type="button" className="portal-secondary-button" onClick={() => moveBlock(block.id, 'down')}>
                            Bajar
                          </button>
                          <button type="button" className="portal-secondary-button" onClick={() => removeBlock(block.id)}>
                            Quitar
                          </button>
                        </div>
                      </div>
                      {block.type === 'paragraph' ? (
                        <div className="portal-block-text-wrap">
                          <textarea
                            value={block.text || ''}
                            onChange={(event) => updateBlock(block.id, { text: event.target.value })}
                            className="portal-block-textarea"
                          />
                          <div className="portal-upload-meta">
                            Usa enlaces inline como <code>[Koywe](https://koywe.com)</code>. Solo se verán en el detalle.
                          </div>
                        </div>
                      ) : (
                        <div className="portal-block-image-wrap">
                          <img
                            src={block.image?.url}
                            alt="Bloque de publicación"
                            className="portal-form-image-preview"
                          />
                          <div className="portal-upload-meta">
                            {block.image?.width && block.image?.height
                              ? `${block.image.width} × ${block.image.height}`
                              : 'Imagen subida'}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {imageUploadError ? (
                  <div className="portal-upload-error">{imageUploadError}</div>
                ) : null}
              </div>
              <label>
                Tag
                <input value={draft.tag} onChange={(event) => setDraft((current) => ({ ...current, tag: event.target.value }))} />
              </label>
              <div className="portal-form-row">
                <label>
                  Color de etiqueta
                  <select value={draft.tagColor} onChange={(event) => setDraft((current) => ({ ...current, tagColor: event.target.value }))}>
                    {TAG_COLOR_OPTIONS.map((option) => (
                      <option key={option.value || 'auto'} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Mostrar en
                  <div className="portal-surface-badges">
                    <span className={`portal-surface-badge ${draft.surfaces.includes('CHANNEL') ? 'active' : ''}`}>Canal</span>
                    <span className={`portal-surface-badge ${draft.surfaces.includes('DISCOVER') ? 'active' : ''}`}>Descubrir</span>
                  </div>
                </label>
              </div>
              {draft.itemType === 'VIDEO' && (
                <div className="portal-form-video-grid">
                  <label>
                    TikTok URL
                    <input value={draft.tiktokUrl} onChange={(event) => setDraft((current) => ({ ...current, tiktokUrl: event.target.value }))} />
                  </label>
                  <label>
                    Instagram URL
                    <input value={draft.instagramUrl} onChange={(event) => setDraft((current) => ({ ...current, instagramUrl: event.target.value }))} />
                  </label>
                  <label>
                    YouTube URL
                    <input value={draft.youtubeUrl} onChange={(event) => setDraft((current) => ({ ...current, youtubeUrl: event.target.value }))} />
                  </label>
                </div>
              )}
              <div className="portal-checks">
                <label><input type="checkbox" checked={draft.sendPush} onChange={(event) => setDraft((current) => ({ ...current, sendPush: event.target.checked }))} /> Push</label>
                <label><input type="checkbox" checked={draft.sendInApp} onChange={(event) => setDraft((current) => ({ ...current, sendInApp: event.target.checked }))} /> In-app</label>
                <label><input type="checkbox" checked={draft.surfaces.includes('CHANNEL')} onChange={(event) => setDraft((current) => ({ ...current, surfaces: event.target.checked ? Array.from(new Set([...current.surfaces, 'CHANNEL'])) : current.surfaces.filter((surface) => surface !== 'CHANNEL') }))} /> Canal</label>
                <label><input type="checkbox" checked={draft.surfaces.includes('DISCOVER')} onChange={(event) => setDraft((current) => ({ ...current, surfaces: event.target.checked ? Array.from(new Set([...current.surfaces, 'DISCOVER'])) : current.surfaces.filter((surface) => surface !== 'DISCOVER') }))} /> Descubrir</label>
              </div>
              <details className="portal-advanced">
                <summary>Metadata avanzada (JSON)</summary>
                <label>
                  Metadata (JSON)
                  <textarea value={draft.metadataText} onChange={(event) => setDraft((current) => ({ ...current, metadataText: event.target.value }))} />
                </label>
              </details>
              <button className="portal-primary-button" type="submit" disabled={saveContentState.loading}>
                Guardar publicación
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
