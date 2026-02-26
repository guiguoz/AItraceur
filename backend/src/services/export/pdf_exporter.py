# =============================================
# Exporteur PDF
# Sprint 9: Exports & Polish
# =============================================

import io
from dataclasses import dataclass
from typing import Dict, List, Optional


# =============================================
# Exporteur PDF simple
# =============================================
class PDFExporter:
    """
    Exporte les circuits en PDF.

    Note: Pour un vrai PDF, installer reportlab:
    pip install reportlab

    Cette version génère un PDF basique ou retourne des instructions.
    """

    def __init__(self):
        """Initialise l'exporteur."""
        self.reportlab_available = False

        # Vérifier si reportlab est installé
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            self.reportlab_available = True
        except ImportError:
            pass

    def export_circuit_description(
        self,
        circuit_data: Dict,
        controls: List[Dict],
    ) -> bytes:
        """
        Exporte les détails du circuit en PDF.

        Args:
            circuit_data: Données du circuit
            controls: Liste des contrôles

        Returns:
            PDF en bytes
        """
        if self.reportlab_available:
            return self._export_with_reportlab(circuit_data, controls)
        else:
            return self._export_fallback(circuit_data, controls)

    def _export_with_reportlab(
        self,
        circuit_data: Dict,
        controls: List[Dict],
    ) -> bytes:
        """Exporte avec reportlab."""
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        # Titre
        c.setFont("Helvetica-Bold", 24)
        c.drawString(20 * mm, height - 30 * mm, circuit_data.get("name", "Circuit"))

        # Infos générales
        y = height - 45 * mm
        c.setFont("Helvetica", 12)

        infos = [
            ("Catégorie:", circuit_data.get("category", "N/A")),
            ("Niveau technique:", circuit_data.get("technical_level", "N/A")),
            ("Longueur:", f"{circuit_data.get('length_meters', 0)} m"),
            ("Dénivelé:", f"{circuit_data.get('climb_meters', 0)} m"),
            ("Nombre de postes:", str(len(controls))),
            ("Temps gagné:", f"{circuit_data.get('winning_time_minutes', 0)} min"),
        ]

        for label, value in infos:
            c.drawString(20 * mm, y, f"{label} {value}")
            y -= 8 * mm

        # Liste des contrôles
        y -= 10 * mm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, y, "Postes:")
        y -= 10 * mm

        c.setFont("Helvetica", 10)

        for ctrl in controls:
            ctrl_text = f"  {ctrl.get('order', '')}. {ctrl.get('description', '')}"
            c.drawString(20 * mm, y, ctrl_text)
            y -= 6 * mm

            if y < 30 * mm:
                c.showPage()
                y = height - 30 * mm
                c.setFont("Helvetica", 10)

        # Note en bas
        c.setFont("Helvetica-Italic", 8)
        c.drawString(20 * mm, 20 * mm, "Généré par AItraceur")

        c.save()
        buffer.seek(0)

        return buffer.getvalue()

    def _export_fallback(
        self,
        circuit_data: Dict,
        controls: List[Dict],
    ) -> bytes:
        """
        Version fallback sans reportlab.
        Retourne un PDF très simple ou un message.
        """
        # Créer un fichier texte qui peut être converti
        text = self._create_text_description(circuit_data, controls)

        # Essayer avec fpdf
        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)

            # Titre
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, circuit_data.get("name", "Circuit"), ln=True, align="C")
            pdf.ln(5)

            # Infos
            pdf.set_font("Arial", size=12)
            infos = [
                f"Catégorie: {circuit_data.get('category', 'N/A')}",
                f"Niveau: {circuit_data.get('technical_level', 'N/A')}",
                f"Longueur: {circuit_data.get('length_meters', 0)} m",
                f"D+: {circuit_data.get('climb_meters', 0)} m",
                f"Postes: {len(controls)}",
            ]

            for info in infos:
                pdf.cell(0, 8, info, ln=True)

            pdf.ln(5)

            # Postes
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Postes:", ln=True)
            pdf.set_font("Arial", size=10)

            for ctrl in controls:
                ctrl_text = f"  {ctrl.get('order', '')}. {ctrl.get('description', '')}"
                pdf.cell(0, 6, ctrl_text, ln=True)

            return pdf.output(dest="S").encode("latin-1")

        except ImportError:
            # Retourner du texte brut encodé
            return text.encode("utf-8")

    def _create_text_description(
        self,
        circuit_data: Dict,
        controls: List[Dict],
    ) -> str:
        """Crée une description textuelle."""
        lines = [
            "=" * 50,
            f"CIRCUIT: {circuit_data.get('name', 'N/A')}",
            "=" * 50,
            "",
            f"Catégorie: {circuit_data.get('category', 'N/A')}",
            f"Niveau: {circuit_data.get('technical_level', 'N/A')}",
            f"Longueur: {circuit_data.get('length_meters', 0)} m",
            f"D+: {circuit_data.get('climb_meters', 0)} m",
            f"Postes: {len(controls)}",
            f"Temps gagné: {circuit_data.get('winning_time_minutes', 0)} min",
            "",
            "LISTE DES POSTES:",
            "-" * 30,
        ]

        for ctrl in controls:
            lines.append(f"  {ctrl.get('order', '')}. {ctrl.get('description', '')}")

        lines.extend(
            [
                "",
                "-" * 30,
                "Généré par AItraceur",
            ]
        )

        return "\n".join(lines)


# =============================================
# Fonctions utilitaires
# =============================================
def export_circuit_to_pdf(circuit_data: Dict, controls: List[Dict]) -> bytes:
    """Exporte un circuit en PDF."""
    exporter = PDFExporter()
    return exporter.export_circuit_description(circuit_data, controls)
