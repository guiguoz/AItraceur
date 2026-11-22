/**
 * Calcul de la résolution de rendu OCAD (m/px).
 *
 * Règle : on vise ~50 Mpx (RAW = résolution qui donne 50 Mpx),
 * puis on arrondit par paliers, avec deux garanties :
 *   - plancher 0,1 m/px (qualité minimale sprint)
 *   - plafond 200 Mpx (marge sous la limite dure de Sharp 268 Mpx)
 */

/**
 * Choisit la résolution (m/px) pour rendre une emprise de extentW × extentH mètres.
 * @param {number} extentW - largeur en mètres
 * @param {number} extentH - hauteur en mètres
 * @returns {number} résolution en m/px
 */
function chooseResolution(extentW, extentH) {
  const RAW = Math.sqrt((extentW * extentH) / 50_000_000)
  let resolution = RAW < 0.3 ? Math.max(0.1, RAW) : RAW < 0.8 ? 0.5 : Math.ceil(RAW)
  // Garantie dure : jamais plus de 200 Mpx
  resolution = Math.max(resolution, Math.sqrt((extentW * extentH) / 200_000_000))
  return resolution
}

/**
 * Nombre de pixels (w × h) pour une emprise et une résolution données.
 * @param {number} extentW - largeur en mètres
 * @param {number} extentH - hauteur en mètres
 * @param {number} resolution - résolution en m/px
 * @returns {number} nombre de pixels
 */
function pixelCount(extentW, extentH, resolution) {
  return (extentW / resolution) * (extentH / resolution)
}

module.exports = { chooseResolution, pixelCount }
