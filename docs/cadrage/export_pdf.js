/**
 * Export du dossier de cadrage en PDF.
 *
 * Outil local, pas une dépendance du projet : le PDF versionné est le
 * livrable, ce script sert à le régénérer après une modification du Markdown.
 *
 * Prérequis :
 *   npm install --no-save --no-package-lock playwright
 *   npx playwright install chromium
 *
 * Usage :
 *   cd docs/cadrage
 *   node export_pdf.js
 */
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const dossier = __dirname;
  const source = "file://" + path.join(dossier, "dossier_cadrage.html");
  const cible = path.join(dossier, "dossier_cadrage.pdf");

  const navigateur = await chromium.launch({ headless: true });
  const page = await navigateur.newPage();
  await page.goto(source, { waitUntil: "networkidle" });
  await page.pdf({
    path: cible,
    format: "A4",
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: "<div></div>",
    footerTemplate:
      '<div style="width:100%;font-size:7.5px;color:#666;padding:0 16mm;' +
      'display:flex;justify-content:space-between;' +
      'font-family:DejaVu Sans, Arial, sans-serif;">' +
      "<span>PrediCare — Dossier de cadrage — 20 octobre 2026</span>" +
      '<span>Page <span class="pageNumber"></span> / ' +
      '<span class="totalPages"></span></span>' +
      "</div>",
    margin: { top: "16mm", bottom: "18mm", left: "16mm", right: "16mm" },
    preferCSSPageSize: true,
  });
  await navigateur.close();
  console.log("PDF écrit :", cible);
})();
