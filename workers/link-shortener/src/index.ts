export interface Env {
  LINKS: KVNamespace;
  ANALYTICS: KVNamespace;
  APPLE_APP_ID: string;
  ANDROID_PACKAGE_ID: string;
  IOS_BUNDLE_ID: string;
  TESTFLIGHT_URL: string;
  PLAY_STORE_URL: string;
  LANDING_PAGE_URL: string;
  ADMIN_USERNAME: string;
  ADMIN_PASSWORD: string;
}

interface LinkData {
  payload: string;
  type: 'referral' | 'influencer' | 'deeplink' | 'achievement';
  createdAt: string;
  clicks: number;
  metadata?: Record<string, any>;
}

interface AnalyticsEvent {
  timestamp: string;
  userAgent: string;
  ip: string;
  country: string;
  platform: 'ios' | 'android' | 'desktop' | 'unknown';
  slug: string;
  referer?: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    
    // Handle apple-app-site-association
    if (url.pathname === '/.well-known/apple-app-site-association' || 
        url.pathname === '/apple-app-site-association') {
      const appleConfig = {
        "applinks": {
          "apps": [],
          "details": [
            {
              "appID": `${env.APPLE_APP_ID}.${env.IOS_BUNDLE_ID}`,
              "paths": [
                "/app/*",
                "/referral/*",
                "/achievement/*",
                "/influencer/*",
                "/*"
              ]
            }
          ]
        },
        "webcredentials": {
          "apps": [`${env.APPLE_APP_ID}.${env.IOS_BUNDLE_ID}`]
        }
      };
      
      return new Response(JSON.stringify(appleConfig, null, 2), {
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'public, max-age=3600'
        }
      });
    }
    
    // Handle API endpoints
    if (url.pathname.startsWith('/api/')) {
      return handleAPI(request, env, url);
    }
    
    // Handle admin UI
    if (url.pathname === '/admin' || url.pathname === '/admin/') {
      // Check basic auth
      const authHeader = request.headers.get('Authorization');
      const expectedAuth = 'Basic ' + btoa(`${env.ADMIN_USERNAME}:${env.ADMIN_PASSWORD}`);
      
      if (authHeader !== expectedAuth) {
        return new Response('Unauthorized', {
          status: 401,
          headers: {
            'WWW-Authenticate': 'Basic realm="Admin Panel"'
          }
        });
      }
      
      // Serve admin HTML directly
      const adminHTML = await getAdminHTML();
      return new Response(adminHTML, {
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-cache'
        }
      });
    }
    
    // Handle root domain
    if (url.pathname === '/' || url.pathname === '') {
      return Response.redirect(env.LANDING_PAGE_URL, 302);
    }
    
    // Extract slug from path
    const slug = url.pathname.slice(1).split('/')[0];
    
    // Validate slug format (alphanumeric, 4-10 chars)
    if (!slug || !/^[a-zA-Z0-9]{4,10}$/.test(slug)) {
      return new Response('Invalid link', { status: 404 });
    }
    
    // Get link data from KV
    const linkDataStr = await env.LINKS.get(slug);
    if (!linkDataStr) {
      return new Response('Link not found', { status: 404 });
    }
    
    const linkData: LinkData = JSON.parse(linkDataStr);
    
    // Detect platform
    const userAgent = request.headers.get('user-agent') || '';
    const platform = detectPlatform(userAgent);
    
    // Log analytics asynchronously
    ctx.waitUntil(logAnalytics(env, {
      timestamp: new Date().toISOString(),
      userAgent,
      ip: request.headers.get('cf-connecting-ip') || 'unknown',
      country: request.headers.get('cf-ipcountry') || 'unknown',
      platform,
      slug,
      referer: request.headers.get('referer')
    }));
    
    // Increment click count
    ctx.waitUntil(incrementClicks(env, slug, linkData));
    
    // Generate redirect URL based on platform
    const redirectUrl = getRedirectUrl(platform, linkData, env);
    
    return Response.redirect(redirectUrl, 302);
  },
};

function detectPlatform(userAgent: string): 'ios' | 'android' | 'desktop' | 'unknown' {
  const ua = userAgent.toLowerCase();
  
  if (/iphone|ipad|ipod/.test(ua)) return 'ios';
  if (/android/.test(ua)) return 'android';
  if (/windows|mac|linux/.test(ua)) return 'desktop';
  
  return 'unknown';
}

function getRedirectUrl(platform: string, linkData: LinkData, env: Env): string {
  const encodedPayload = encodeURIComponent(linkData.payload);
  
  switch (platform) {
    case 'ios':
      // For iOS, use Universal Links during closed beta
      // After app store launch, this will be the App Store URL
      if (linkData.type === 'referral' || linkData.type === 'influencer') {
        // TestFlight with deep link path
        return `${env.TESTFLIGHT_URL}?referrer=${encodedPayload}`;
      }
      // For other types, use universal link
      return `https://confio.lat/app/${linkData.type}/${encodedPayload}`;
      
    case 'android':
      // Android Play Store with referrer parameter
      return `${env.PLAY_STORE_URL}&referrer=${encodedPayload}`;
      
    default:
      // Desktop - redirect to landing page with campaign data
      return `${env.LANDING_PAGE_URL}?c=${encodedPayload}&t=${linkData.type}`;
  }
}

async function incrementClicks(env: Env, slug: string, linkData: LinkData): Promise<void> {
  linkData.clicks = (linkData.clicks || 0) + 1;
  await env.LINKS.put(slug, JSON.stringify(linkData));
}

async function logAnalytics(env: Env, event: AnalyticsEvent): Promise<void> {
  const key = `${event.slug}:${Date.now()}:${Math.random().toString(36).substr(2, 9)}`;
  await env.ANALYTICS.put(key, JSON.stringify(event), {
    expirationTtl: 90 * 24 * 60 * 60 // 90 days
  });
}

async function handleAPI(request: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname;
  
  // CORS headers for API
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Content-Type': 'application/json'
  };
  
  // Handle preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }
  
  try {
    // Create link endpoint
    if (path === '/api/links' && request.method === 'POST') {
      const body = await request.json() as {
        slug?: string;
        payload: string;
        type: LinkData['type'];
        metadata?: Record<string, any>;
      };
      
      // Generate slug if not provided
      const slug = body.slug || generateSlug();
      
      // Validate slug availability
      const existing = await env.LINKS.get(slug);
      if (existing) {
        return new Response(
          JSON.stringify({ error: 'Slug already exists' }), 
          { status: 409, headers: corsHeaders }
        );
      }
      
      // Create link data
      const linkData: LinkData = {
        payload: body.payload,
        type: body.type,
        createdAt: new Date().toISOString(),
        clicks: 0,
        metadata: body.metadata
      };
      
      await env.LINKS.put(slug, JSON.stringify(linkData));
      
      return new Response(
        JSON.stringify({ 
          slug, 
          shortUrl: `https://confio.lat/${slug}`,
          data: linkData 
        }), 
        { status: 201, headers: corsHeaders }
      );
    }
    
    // Get link stats
    if (path.startsWith('/api/links/') && request.method === 'GET') {
      const slug = path.split('/')[3];
      const linkDataStr = await env.LINKS.get(slug);
      
      if (!linkDataStr) {
        return new Response(
          JSON.stringify({ error: 'Link not found' }), 
          { status: 404, headers: corsHeaders }
        );
      }
      
      const linkData = JSON.parse(linkDataStr);
      
      // Get recent analytics
      const analyticsKeys = await env.ANALYTICS.list({ prefix: `${slug}:` });
      const analytics = await Promise.all(
        analyticsKeys.keys.slice(0, 100).map(key => 
          env.ANALYTICS.get(key.name).then(data => data ? JSON.parse(data) : null)
        )
      );
      
      return new Response(
        JSON.stringify({ 
          slug,
          shortUrl: `https://confio.lat/${slug}`,
          data: linkData,
          recentClicks: analytics.filter(Boolean)
        }), 
        { headers: corsHeaders }
      );
    }
    
    return new Response(
      JSON.stringify({ error: 'Not found' }), 
      { status: 404, headers: corsHeaders }
    );
    
  } catch (error) {
    return new Response(
      JSON.stringify({ error: 'Internal server error' }), 
      { status: 500, headers: corsHeaders }
    );
  }
}

function generateSlug(length: number = 6): string {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let slug = '';
  for (let i = 0; i < length; i++) {
    slug += chars[Math.floor(Math.random() * chars.length)];
  }
  return slug;
}

async function getAdminHTML(): Promise<string> {
  return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Confio Link Admin</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        h1 {
            color: #34d399;
            margin-bottom: 30px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            color: #333;
        }
        
        input, select, textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 16px;
        }
        
        button {
            background: #34d399;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover {
            background: #2dc385;
        }
        
        .result {
            margin-top: 20px;
            padding: 20px;
            background: #f0fdf4;
            border: 1px solid #34d399;
            border-radius: 6px;
            display: none;
        }
        
        .link-display {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 10px;
        }
        
        .link-url {
            flex: 1;
            padding: 10px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-family: monospace;
        }
        
        .copy-btn {
            background: #6b7280;
        }
        
        .copy-btn:hover {
            background: #4b5563;
        }
        
        .stats {
            margin-top: 40px;
        }
        
        .stat-item {
            background: #f9fafb;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 10px;
        }
        
        .error {
            color: #dc2626;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔗 Confio Link Manager</h1>
        
        <form id="linkForm">
            <div class="form-group">
                <label for="type">Tipo de enlace</label>
                <select id="type" required>
                    <option value="referral">Referido (48h window)</option>
                    <option value="influencer">Influencer TikTok</option>
                    <option value="achievement">Logro específico</option>
                    <option value="deeplink">Deep link general</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="payload">Payload (datos del enlace)</label>
                <input type="text" id="payload" placeholder="ej: tiktok|@usuario123" required>
                <small style="color: #6b7280;">Formato: tipo|identificador</small>
            </div>
            
            <div class="form-group">
                <label for="slug">Slug personalizado (opcional)</label>
                <input type="text" id="slug" placeholder="ej: promo2024" pattern="[a-zA-Z0-9]{4,10}">
                <small style="color: #6b7280;">4-10 caracteres alfanuméricos. Se genera automáticamente si se deja vacío.</small>
            </div>
            
            <div class="form-group">
                <label for="metadata">Metadata (JSON opcional)</label>
                <textarea id="metadata" rows="3" placeholder='{"campaign": "whatsapp-beta", "creator": "marketing"}'></textarea>
            </div>
            
            <button type="submit">Crear enlace corto</button>
        </form>
        
        <div id="result" class="result">
            <h3>✅ ¡Enlace creado!</h3>
            <div class="link-display">
                <input type="text" class="link-url" id="shortUrl" readonly>
                <button class="copy-btn" onclick="copyLink()">Copiar</button>
            </div>
            <p style="margin-top: 10px; color: #6b7280;">
                Este enlace detectará automáticamente la plataforma del usuario y lo redirigirá apropiadamente.
            </p>
        </div>
        
        <div id="error" class="error"></div>
        
        <div class="stats">
            <h2>📊 Verificar estadísticas</h2>
            <div class="form-group">
                <label for="checkSlug">Slug a verificar</label>
                <input type="text" id="checkSlug" placeholder="ej: promo2024">
            </div>
            <button onclick="checkStats()">Ver estadísticas</button>
            
            <div id="statsResult" style="margin-top: 20px;"></div>
        </div>
    </div>
    
    <script>
        const API_BASE = window.location.origin + '/api';
        
        document.getElementById('linkForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const type = document.getElementById('type').value;
            const payload = document.getElementById('payload').value;
            const slug = document.getElementById('slug').value;
            const metadataStr = document.getElementById('metadata').value;
            
            let metadata = {};
            if (metadataStr) {
                try {
                    metadata = JSON.parse(metadataStr);
                } catch (err) {
                    showError('Metadata JSON inválido');
                    return;
                }
            }
            
            try {
                const response = await fetch(\`\${API_BASE}/links\`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        type,
                        payload,
                        slug: slug || undefined,
                        metadata
                    })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    document.getElementById('shortUrl').value = data.shortUrl;
                    document.getElementById('result').style.display = 'block';
                    document.getElementById('error').textContent = '';
                    document.getElementById('linkForm').reset();
                } else {
                    showError(data.error || 'Error al crear el enlace');
                }
            } catch (err) {
                showError('Error de conexión');
            }
        });
        
        function copyLink() {
            const urlInput = document.getElementById('shortUrl');
            urlInput.select();
            document.execCommand('copy');
            
            const btn = event.target;
            const originalText = btn.textContent;
            btn.textContent = '¡Copiado!';
            setTimeout(() => {
                btn.textContent = originalText;
            }, 2000);
        }
        
        async function checkStats() {
            const slug = document.getElementById('checkSlug').value;
            if (!slug) return;
            
            try {
                const response = await fetch(\`\${API_BASE}/links/\${slug}\`);
                const data = await response.json();
                
                if (response.ok) {
                    const statsHtml = \`
                        <div class="stat-item">
                            <strong>URL:</strong> \${data.shortUrl}<br>
                            <strong>Tipo:</strong> \${data.data.type}<br>
                            <strong>Payload:</strong> \${data.data.payload}<br>
                            <strong>Clicks:</strong> \${data.data.clicks}<br>
                            <strong>Creado:</strong> \${new Date(data.data.createdAt).toLocaleString()}<br>
                            \${data.data.metadata ? \`<strong>Metadata:</strong> \${JSON.stringify(data.data.metadata)}\` : ''}
                        </div>
                        <h3>Últimos clicks:</h3>
                        \${data.recentClicks.map(click => \`
                            <div class="stat-item">
                                \${new Date(click.timestamp).toLocaleString()} - 
                                \${click.platform} - 
                                \${click.country}
                            </div>
                        \`).join('')}
                    \`;
                    document.getElementById('statsResult').innerHTML = statsHtml;
                } else {
                    document.getElementById('statsResult').innerHTML = 
                        \`<div class="error">Enlace no encontrado</div>\`;
                }
            } catch (err) {
                document.getElementById('statsResult').innerHTML = 
                    \`<div class="error">Error al cargar estadísticas</div>\`;
            }
        }
        
        function showError(message) {
            document.getElementById('error').textContent = message;
            document.getElementById('result').style.display = 'none';
        }
    </script>
</body>
</html>`;
}