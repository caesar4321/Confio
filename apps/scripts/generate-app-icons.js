const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

// Android icon sizes
const androidSizes = {
  'mipmap-mdpi': 48,
  'mipmap-hdpi': 72,
  'mipmap-xhdpi': 96,
  'mipmap-xxhdpi': 144,
  'mipmap-xxxhdpi': 192
};

// Android notification icon sizes
const androidNotificationSizes = {
  'mipmap-mdpi': 24,
  'mipmap-hdpi': 36,
  'mipmap-xhdpi': 48,
  'mipmap-xxhdpi': 72,
  'mipmap-xxxhdpi': 96
};

// iOS icon sizes
const iosSizes = [
  { size: 20, scale: 1 },
  { size: 20, scale: 2 },
  { size: 20, scale: 3 },
  { size: 29, scale: 1 },
  { size: 29, scale: 2 },
  { size: 29, scale: 3 },
  { size: 40, scale: 1 },
  { size: 40, scale: 2 },
  { size: 40, scale: 3 },
  { size: 60, scale: 1 },
  { size: 60, scale: 2 },
  { size: 60, scale: 3 },
  { size: 76, scale: 1 },
  { size: 76, scale: 2 },
  { size: 83.5, scale: 2 },
  { size: 1024, scale: 1 }
];

// iOS notification icon sizes
const iosNotificationSizes = [
  { size: 20, scale: 1 },
  { size: 20, scale: 2 },
  { size: 20, scale: 3 }
];

async function generateAndroidIcons(sourceImage) {
  console.log('Generating Android icons...');
  const androidPath = path.join(__dirname, '../android/app/src/main/res');

  for (const [folder, size] of Object.entries(androidSizes)) {
    // Generate regular icon
    const outputPath = path.join(androidPath, folder, 'ic_launcher.png');
    await sharp(sourceImage)
      .resize(size, size)
      .toFile(outputPath);
    console.log(`Generated ${folder} icon (${size}x${size})`);

    // Generate round icon
    const roundOutputPath = path.join(androidPath, folder, 'ic_launcher_round.png');
    await sharp(sourceImage)
      .resize(size, size)
      .composite([{
        input: Buffer.from(
          `<svg><circle cx="${size/2}" cy="${size/2}" r="${size/2}" fill="white"/></svg>`
        ),
        blend: 'dest-in'
      }])
      .toFile(roundOutputPath);
    console.log(`Generated ${folder} round icon (${size}x${size})`);
  }
}

async function generateAndroidNotificationIcons(sourceImage) {
  console.log('Generating Android notification icons...');
  const androidPath = path.join(__dirname, '../android/app/src/main/res');

  for (const [folder, size] of Object.entries(androidNotificationSizes)) {
    // Generate white notification icon
    const outputPath = path.join(androidPath, folder, 'ic_notification.png');
    await sharp(sourceImage)
      .resize(size, size)
      .threshold(128) // Convert to black and white
      .negate() // Invert colors to make it white
      .toFile(outputPath);
    console.log(`Generated ${folder} notification icon (${size}x${size})`);
  }
}

async function generateIOSIcons(sourceImage) {
  console.log('Generating iOS icons...');
  const iosPath = path.join(__dirname, '../ios/Confio/Images.xcassets/AppIcon.appiconset');

  for (const { size, scale } of iosSizes) {
    const actualSize = size * scale;
    const outputPath = path.join(iosPath, `icon-${size}@${scale}x.png`);
    await sharp(sourceImage)
      .resize(actualSize, actualSize)
      .toFile(outputPath);
    console.log(`Generated iOS icon ${size}@${scale}x (${actualSize}x${actualSize})`);
  }
}

async function generateIOSNotificationIcons(sourceImage) {
  console.log('Generating iOS notification icons...');
  const iosPath = path.join(__dirname, '../ios/Confio/Images.xcassets/NotificationIcon.imageset');

  // Create the imageset directory if it doesn't exist
  if (!fs.existsSync(iosPath)) {
    fs.mkdirSync(iosPath, { recursive: true });
  }

  // Create Contents.json for the notification icon
  const contentsJson = {
    "images": iosNotificationSizes.map(({ size, scale }) => ({
      "idiom": "universal",
      "scale": `${scale}x`,
      "filename": `notification-${size}@${scale}x.png`,
      "template-rendering-intent": "template"
    })),
    "info": {
      "version": 1,
      "author": "xcode"
    }
  };

  fs.writeFileSync(
    path.join(iosPath, 'Contents.json'),
    JSON.stringify(contentsJson, null, 2)
  );

  // Generate the notification icons
  for (const { size, scale } of iosNotificationSizes) {
    const actualSize = size * scale;
    const outputPath = path.join(iosPath, `notification-${size}@${scale}x.png`);
    
    // Create a black and transparent template image
    await sharp(sourceImage)
      .resize(actualSize, actualSize)
      .threshold(128) // Convert to black and white
      .ensureAlpha() // Ensure alpha channel is preserved
      .toFile(outputPath);
    
    console.log(`Generated iOS notification icon ${size}@${scale}x (${actualSize}x${actualSize})`);
  }
}

async function main() {
  const sourceImage = path.join(__dirname, '../src/assets/png/$CONFIO.png');
  
  if (!fs.existsSync(sourceImage)) {
    console.error('Source image not found:', sourceImage);
    process.exit(1);
  }

  try {
    await generateAndroidIcons(sourceImage);
    await generateAndroidNotificationIcons(sourceImage);
    await generateIOSIcons(sourceImage);
    await generateIOSNotificationIcons(sourceImage);
    console.log('All app icons generated successfully!');
  } catch (error) {
    console.error('Error generating app icons:', error);
    process.exit(1);
  }
}

main(); 