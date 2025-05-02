const fs = require('fs');
const path = require('path');

// Paths
const buildIndexPath = path.join(__dirname, '../build/index.html');
const djangoTemplatePath = path.join(__dirname, '../../config/templates/index.html');

// Read the build index.html
const indexContent = fs.readFileSync(buildIndexPath, 'utf8');

// Write to Django templates
fs.writeFileSync(djangoTemplatePath, indexContent);

console.log('Successfully copied index.html to Django templates'); 