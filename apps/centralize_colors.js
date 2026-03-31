#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function processFile(filePath) {
  let content = fs.readFileSync(filePath, 'utf-8');

  // Check if it has a local colors definition
  const colorsDefIndex = content.indexOf('const colors = {');
  if (colorsDefIndex === -1 && content.indexOf('  const colors = {') === -1) {
    return; // No local colors defined
  }

  // Remove the block
  let lines = content.split('\n');
  let newLines = [];
  let inColorsBlock = false;
  let braceCount = 0;
  let blockRemoved = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (!inColorsBlock && (line.trim().startsWith('const colors = {'))) {
      inColorsBlock = true;
      braceCount = 0;
      blockRemoved = true;
    }

    if (inColorsBlock) {
      for (let c of line) {
        if (c === '{') braceCount++;
        if (c === '}') braceCount--;
      }
      if (braceCount === 0) {
        inColorsBlock = false;
        // Optionally skip the empty line after the block
        if (i + 1 < lines.length && lines[i + 1].trim() === '') {
          i++;
        }
      }
    } else {
      newLines.push(line);
    }
  }

  if (!blockRemoved) return;

  let newContent = newLines.join('\n');

  // If import { colors } is not present, add it
  // Find where to put it: after last absolute import or vector icons import
  if (!newContent.includes("import { colors } from '../config/theme'")) {
    // try to put it near other relative imports or vector-icons
    const importLines = newLines.filter(l => l.startsWith('import '));
    if (importLines.length > 0) {
      // just put it after the last import
      let lastImportIndex = 0;
      for (let i = 0; i < newLines.length; i++) {
        if (newLines[i].startsWith('import ')) {
          lastImportIndex = i;
        }
      }
      // calculate depth based on filePath
      const isScreen = filePath.includes('/screens/');
      const isComponent = filePath.includes('/components/');
      let importPath = "import { colors } from '../config/theme';";
      if (filePath.includes('/components/')) {
        // if inside components, might be deep? we assume components and screens are 1 level deep inside src
        const relPath = path.relative(path.dirname(filePath), path.join(__dirname, 'src', 'config', 'theme'));
        // actually just use '../config/theme' since mostly they are src/screens/X or src/components/X
        importPath = `import { colors } from '${relPath.startsWith('.') ? relPath : './' + relPath}';`;
      }
      // Just hardcode '../config/theme' because all screens/components are exactly 1 directory deep in src
      // but let's use path.relative
      const themePath = path.resolve(__dirname, 'src', 'config', 'theme');
      let relativeThemePath = path.relative(path.dirname(filePath), themePath);
      if (!relativeThemePath.startsWith('.')) relativeThemePath = './' + relativeThemePath;
      
      newLines.splice(lastImportIndex + 1, 0, `import { colors } from '${relativeThemePath}';`);
    } else {
      newLines.unshift(`import { colors } from '../config/theme';`);
    }
  }
  
  newContent = newLines.join('\n');

  // Remappings
  newContent = newContent.replace(/colors\.text(?![\.A-Za-z])/g, 'colors.textFlat');
  newContent = newContent.replace(/colors\.textPrimary/g, 'colors.textFlat');
  newContent = newContent.replace(/colors\.textSecondary/g, 'colors.textSecondary'); // No change needed but explicit
  newContent = newContent.replace(/colors\.textMuted/g, 'colors.textSecondary');
  newContent = newContent.replace(/colors\.textLight/g, 'colors.textSecondary');
  newContent = newContent.replace(/colors\.heroFrom/g, 'colors.primaryLight');
  newContent = newContent.replace(/colors\.heroTo/g, 'colors.primary');
  newContent = newContent.replace(/colors\.confioGreen/g, 'colors.primary');
  newContent = newContent.replace(/colors\.white/g, 'colors.cardBackground');
  newContent = newContent.replace(/colors\.accentPurple/g, 'colors.secondary');
  newContent = newContent.replace(/colors\.darkGray/g, 'colors.dark');
  newContent = newContent.replace(/colors\.lightGray/g, 'colors.neutralDark');
  
  if (content !== newContent) {
    fs.writeFileSync(filePath, newContent, 'utf-8');
    console.log(`Updated ${path.basename(filePath)}`);
  }
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    if (fs.statSync(fullPath).isDirectory()) {
      walkDir(fullPath);
    } else if (fullPath.endsWith('.tsx')) {
      processFile(fullPath);
    }
  }
}

walkDir(path.join(__dirname, 'src', 'screens'));
walkDir(path.join(__dirname, 'src', 'components'));
console.log('Done.');
