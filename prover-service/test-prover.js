import fetch from 'node-fetch';

async function testProver() {
  console.log('🧪 Testing zkLogin Prover Service...\n');

  // First check health
  try {
    const healthRes = await fetch('http://localhost:3001/health');
    const health = await healthRes.json();
    console.log('✅ Health check:', health);
  } catch (error) {
    console.error('❌ Health check failed:', error.message);
    return;
  }

  console.log('\n📝 Current Setup:');
  console.log('   - Using Mysten\'s external prover');
  console.log('   - This does NOT support custom audiences (Apple/Google OAuth)');
  console.log('   - For production, you\'ll need Docker + self-hosted prover');
}

testProver();