#!/usr/bin/env node

/**
 * Script to create default campaign tracking links
 * Run this after deploying the Cloudflare Worker
 */

const API_BASE = 'https://confio.lat/api';
const ADMIN_USERNAME = 'julian';
const ADMIN_PASSWORD = 'K9mX7nP4qR2vT5wY8zA3bC6dE1fG0hJ4kL7mN9oQ2sU5vW8xY1aB4cD7eF0gH3jK6lM9nP2qR5tV8wX1yZ4aB7cD0eF3gH6jK9lM2nP5qR8tV1wX4yZ7';

const defaultLinks = [
  {
    slug: 'wa',  // Changed from wa-beta
    type: 'testflight',
    payload: 'whatsapp-general',
    metadata: {
      campaign: 'whatsapp',
      source: 'whatsapp',
      medium: 'social',
      description: 'General WhatsApp sharing'
    }
  },
  {
    slug: 'wa-ref',
    type: 'testflight',
    payload: 'whatsapp-referral',
    metadata: {
      campaign: 'referral',
      source: 'whatsapp',
      medium: 'referral',
      description: 'WhatsApp referral program'
    }
  },
  {
    slug: 'wa-tiktok',
    type: 'testflight',
    payload: 'whatsapp-tiktok',
    metadata: {
      campaign: 'tiktok-to-whatsapp',
      source: 'tiktok',
      medium: 'social',
      description: 'TikTok to WhatsApp campaign'
    }
  },
  {
    slug: 'tiktok',
    type: 'testflight',
    payload: 'tiktok-creator',
    metadata: {
      campaign: 'tiktok-creator',
      source: 'tiktok',
      medium: 'creator',
      description: 'TikTok creator channel announcement'
    }
  },
  {
    slug: 'telegram',
    type: 'testflight',
    payload: 'telegram-group',
    metadata: {
      campaign: 'telegram-group',
      source: 'telegram',
      medium: 'group',
      description: 'Telegram group announcement'
    }
  }
];

async function createLink(link) {
  try {
    const response = await fetch(`${API_BASE}/links`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Basic ' + Buffer.from(`${ADMIN_USERNAME}:${ADMIN_PASSWORD}`).toString('base64')
      },
      body: JSON.stringify(link)
    });

    const data = await response.json();
    
    if (response.ok) {
      console.log(`✅ Created: ${data.shortUrl}`);
      return data;
    } else {
      console.error(`❌ Error creating ${link.slug}:`, data.error || response.statusText);
      return null;
    }
  } catch (error) {
    console.error(`❌ Network error creating ${link.slug}:`, error.message);
    return null;
  }
}

async function main() {
  console.log('🚀 Creating default campaign tracking links...\n');
  
  for (const link of defaultLinks) {
    await createLink(link);
    // Small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  
  console.log('\n✨ Done! Your campaign links are ready:');
  console.log('  • https://confio.lat/wa - General WhatsApp sharing');
  console.log('  • https://confio.lat/wa-ref - WhatsApp referral program');
  console.log('  • https://confio.lat/wa-tiktok - TikTok to WhatsApp campaign');
  console.log('  • https://confio.lat/tiktok - TikTok creator channel');
  console.log('  • https://confio.lat/telegram - Telegram group');
}

main().catch(console.error);