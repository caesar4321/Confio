export interface Env {
  LINKS: KVNamespace;
  ANALYTICS: KVNamespace;
  APPLE_APP_ID: string;
  ANDROID_PACKAGE_ID: string;
  IOS_BUNDLE_ID: string;
  TESTFLIGHT_URL: string;
  PLAY_STORE_URL: string;
  LANDING_PAGE_URL: string;
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
      return Response.redirect('https://confio-admin.pages.dev/admin.html', 302);
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