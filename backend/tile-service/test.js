/**
 * Tests du tile service - AItraceur
 * Lancer : node test.js  (depuis backend/tile-service/)
 *
 * Note : ces tests vérifient le code sans démarrer le serveur (pas de port).
 */

let passed = 0;
let failed = 0;

function ok(label) {
  console.log(`  \x1b[32m✓\x1b[0m ${label}`);
  passed++;
}

function fail(label, detail) {
  console.log(`  \x1b[31m✗\x1b[0m ${label}`);
  if (detail) console.log(`    → ${detail}`);
  failed++;
}

function section(title) {
  console.log(`\n\x1b[33m${title}\x1b[0m`);
}

// ============================================================
// Test 1 : Dépendances critiques
// ============================================================
section('[1/4] Dépendances');

try {
  require('express');
  ok('express chargeable');
} catch (e) { fail('express manquant', e.message); }

try {
  require('sharp');
  ok('sharp chargeable (conversion SVG→PNG)');
} catch (e) { fail('sharp manquant - npm install requis', e.message); }

try {
  require('multer');
  ok('multer chargeable (upload fichiers)');
} catch (e) { fail('multer manquant', e.message); }

try {
  require('proj4');
  ok('proj4 chargeable (conversion CRS)');
} catch (e) { fail('proj4 manquant', e.message); }

try {
  require('ocad2geojson');
  ok('ocad2geojson chargeable (parsing OCAD)');
} catch (e) { fail('ocad2geojson manquant', e.message); }

try {
  require('ocad2tiles');
  ok('ocad2tiles chargeable (rendu tuiles)');
} catch (e) { fail('ocad2tiles manquant', e.message); }

// ============================================================
// Test 2 : Conversion CRS (Lambert-93 → WGS84)
// ============================================================
section('[2/4] Conversion CRS Lambert-93 → WGS84');

try {
  const proj4 = require('proj4');

  // Définition Lambert-93 (EPSG:2154)
  const LAMBERT93 = '+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=44 +lat_2=49 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs';
  const WGS84 = 'EPSG:4326';

  // Coordonnées de Paris Lambert-93 : environ [652157, 6862275]
  const [lng, lat] = proj4(LAMBERT93, WGS84, [652157, 6862275]);

  // Paris doit être à environ [2.35, 48.85]
  if (Math.abs(lng - 2.35) < 0.1 && Math.abs(lat - 48.85) < 0.1) {
    ok(`Lambert-93 → WGS84 : [${lng.toFixed(4)}, ${lat.toFixed(4)}] (Paris OK)`);
  } else {
    fail('Conversion Lambert-93 incorrecte', `Obtenu [${lng.toFixed(4)}, ${lat.toFixed(4)}], attendu ~[2.35, 48.85]`);
  }
} catch (e) {
  fail('Erreur conversion CRS', e.message);
}

// ============================================================
// Test 3 : sharp (conversion SVG → PNG)
// ============================================================
section('[3/4] Conversion SVG → PNG (sharp)');

try {
  const sharp = require('sharp');
  // SVG minimal
  const svgBuffer = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="white"/></svg>');

  sharp(svgBuffer)
    .png()
    .toBuffer()
    .then(png => {
      if (png.length > 0) {
        ok(`SVG → PNG : ${png.length} bytes produits`);
      } else {
        fail('SVG → PNG : buffer vide');
      }
      printSummary();
    })
    .catch(e => {
      fail('SVG → PNG échoué', e.message);
      printSummary();
    });
} catch (e) {
  fail('sharp non disponible', e.message);
  printSummary();
  return;
}

// ============================================================
// Test 4 : Structure de server.js
// ============================================================
section('[4/4] Structure de server.js');

try {
  const fs = require('fs');
  const code = fs.readFileSync('./server.js', 'utf8');

  if (code.includes('app.post') && code.includes('/upload')) {
    ok('Endpoint POST /upload présent');
  } else {
    fail('Endpoint POST /upload absent de server.js');
  }

  if (code.includes('app.get') && code.includes('/health')) {
    ok('Endpoint GET /health présent');
  } else {
    fail('Endpoint GET /health absent de server.js');
  }

  if (code.includes('sharp')) {
    ok('sharp utilisé dans server.js');
  } else {
    fail('sharp non utilisé dans server.js');
  }

  if (code.includes('renderSvg') || code.includes('ocad2tiles')) {
    ok('ocad2tiles utilisé pour le rendu');
  } else {
    fail('ocad2tiles non utilisé dans server.js');
  }
} catch (e) {
  fail('Impossible de lire server.js', e.message);
}

// ============================================================
// Résumé (appelé après les tests async de sharp)
// ============================================================
function printSummary() {
  const total = passed + failed;
  console.log('\n\x1b[34m============================================\x1b[0m');
  if (failed === 0) {
    console.log(`\x1b[32m  ✓ Tout est OK (${passed}/${total} tests passés)\x1b[0m`);
  } else {
    console.log(`\x1b[33m  ⚠ ${failed} problème(s) sur ${total} tests\x1b[0m`);
  }
  console.log('\x1b[34m============================================\x1b[0m\n');
  if (failed > 0) process.exit(1);
}
