const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'babel.config.js'),'utf8');
for(const [label,env,release] of [
 ['mainnet override',{CONFIO_ENV:'mainnet',ALLOW_APP_CHECK_DEBUG:'true'},true],
 ['testnet release',{CONFIO_ENV:'testnet',NODE_ENV:'production'},true],
 ['gradle release',{CONFIO_ENV:'testnet',CONFIO_GRADLE_BUNDLE_RELEASE:'true'},true],
 ['iOS release',{CONFIO_ENV:'testnet',CONFIGURATION:'Release'},true],
 ['Babel release',{CONFIO_ENV:'testnet',BABEL_ENV:'production'},true],
 ['testnet development',{CONFIO_ENV:'testnet'},false]]) {
 let generated,mode;
 env.FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID='shell-do-not-ship';
 env.FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS='shell-do-not-ship';
 const fake={existsSync:p=>!p.endsWith('appcheck-gradle-context'),readFileSync:()=> 'ALLOW_APP_CHECK_DEBUG=true\nFIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID=do-not-ship-android\nFIREBASE_APP_CHECK_DEBUG_TOKEN_IOS=do-not-ship-ios\nAPI_URL=https://example.test\n',mkdirSync:()=>{},writeFileSync:(p,v)=>{generated=v;},chmodSync:(p,v)=>{mode=v;}};
 vm.runInNewContext(source,{require:n=>n==='fs'?fake:require(n),__dirname:root,process:{env},module:{exports:{}},console:{log:()=>{}}});
 assert.equal(mode,0o600);
 assert.ok(generated.includes('API_URL=https://example.test'));
 if(release){assert.equal(env.FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID,'');assert.equal(env.FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS,'');assert.equal(env.ALLOW_APP_CHECK_DEBUG,'false');assert.ok(!generated.includes('do-not-ship'));assert.ok(generated.includes('ALLOW_APP_CHECK_DEBUG=false'));}
 else assert.ok(generated.includes('do-not-ship-android'));
 console.log('PASS',label);
}
