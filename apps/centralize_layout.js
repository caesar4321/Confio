const fs = require('fs');
const path = require('path');

function processFile(filePath) {
  let content = fs.readFileSync(filePath, 'utf-8');

  // Check if it has StatusBar.currentHeight
  if (!content.includes('StatusBar.currentHeight')) {
    return;
  }

  // Ensure IMPORT
  if (!content.includes("APP_LAYOUT") && !content.includes("import { APP_LAYOUT }")) {
    let lines = content.split('\n');
    const importLines = lines.filter(l => l.startsWith('import '));
    let lastImportIndex = 0;
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('import ')) {
            lastImportIndex = i;
        }
    }
    const themePath = path.resolve(__dirname, 'src', 'config', 'layout');
    let relativeThemePath = path.relative(path.dirname(filePath), themePath);
    if (!relativeThemePath.startsWith('.')) relativeThemePath = './' + relativeThemePath;
    lines.splice(lastImportIndex + 1, 0, `import { APP_LAYOUT } from '${relativeThemePath}';`);
    content = lines.join('\n');
  }

  // Precise AST/Regex Translations
  content = content.replace(/Platform\.OS === 'android' \? \(StatusBar\.currentHeight \|\| 24\) \+ 10 : 0/g, "Platform.OS === 'android' ? APP_LAYOUT.topSafeArea + 10 : 0");
  
  content = content.replace(/Platform\.OS === 'ios' \? 48 : \(StatusBar\.currentHeight \|\| 32\)/g, "Platform.OS === 'ios' ? APP_LAYOUT.topSafeArea : APP_LAYOUT.topSafeArea + 8");

  content = content.replace(/Platform\.OS === 'android' \? \(StatusBar\.currentHeight \|\| 0\) \+ 12 : 12/g, "APP_LAYOUT.topSafeArea + 12");
  
  content = content.replace(/Platform\.OS === 'android' \? \(StatusBar\.currentHeight \|\| 24\) \+ 12 : 16/g, "APP_LAYOUT.topSafeArea + 12");
  
  // A catch-all for any other stray StatusBar.currentHeight usages
  content = content.replace(/\(StatusBar\.currentHeight \|\| \d+\)/g, "APP_LAYOUT.topSafeArea");

  fs.writeFileSync(filePath, content, 'utf-8');
  console.log(`Updated ${path.basename(filePath)}`);
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    if (fs.statSync(fullPath).isDirectory()) {
      walkDir(fullPath);
    } else if (fullPath.endsWith('.tsx') || fullPath.endsWith('.ts')) {
      processFile(fullPath);
    }
  }
}

walkDir(path.join(__dirname, 'src', 'screens'));
walkDir(path.join(__dirname, 'src', 'components'));
console.log('Layout Migration Done.');
