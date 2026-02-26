# =============================================
# Scraper Vikazimut
# Sprint 6: Base de connaissances RAG
# =============================================

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup


# =============================================
# Types de données
# =============================================
@dataclass
class VikazimutAnalysis:
    """Une analyse Vikazimut."""

    article_id: str
    title: str
    url: str
    date: Optional[str] = None
    author: Optional[str] = None
    content: str = ""
    circuit_name: Optional[str] = None
    event_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class VikazimutCircuit:
    """Un circuit analysé."""

    name: str
    category: str
    analysis: str = ""
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


# =============================================
# Scraper Vikazimut
# =============================================
class VikazimutScraper:
    """
    Scraper pour Vikazimut (vikazimut.com).

    Vikazimut est un site français d'analyses de courses d'orientation.
    Il contient des articles techniques sur le traçage de circuits.
    """

    BASE_URL = "https://www.vikazimut.com"
    API_URL = "https://api.vikazimut.com"  # Si disponible

    def __init__(self):
        """Initialise le scraper."""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    def get_article(self, article_id: str) -> Optional[VikazimutAnalysis]:
        """
        Récupère un article par son ID.

        Args:
            article_id: ID de l'article

        Returns:
            VikazimutAnalysis ou None
        """
        url = f"{self.BASE_URL}/articles/{article_id}"

        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return self._parse_article(response.text, url)
        except Exception as e:
            print(f"Erreur récupération article: {e}")

        return None

    def get_latest_articles(self, limit: int = 10) -> List[VikazimutAnalysis]:
        """
        Récupère les derniers articles.

        Args:
            limit: Nombre d'articles

        Returns:
            Liste d'analyses
        """
        articles = []

        # Page d'accueil
        try:
            response = self.session.get(self.BASE_URL, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")

                # Chercher les articles (à adapter selon la structure réelle)
                article_links = soup.select("article a, .post a, .article a")

                for link in article_links[:limit]:
                    href = link.get("href", "")
                    if href and "/articles/" in href:
                        article_id = href.split("/")[-1]
                        article = self.get_article(article_id)
                        if article:
                            articles.append(article)
        except Exception as e:
            print(f"Erreur récupération articles: {e}")

        return articles

    def search_articles(
        self,
        query: str,
        tags: List[str] = None,
        limit: int = 20,
    ) -> List[VikazimutAnalysis]:
        """
        Recherche des articles.

        Args:
            query: Requête de recherche
            tags: Tags à filtrer
            limit: Nombre max de résultats

        Returns:
            Liste d'analyses
        """
        # Simulation de recherche
        # Dans la réalité, utiliser l'API de recherche si disponible
        return []

    def get_circuit_analysis(self, article_id: str) -> Optional[VikazimutCircuit]:
        """
        Extrait l'analyse d'un circuit depuis un article.

        Args:
            article_id: ID de l'article

        Returns:
            VikazimutCircuit ou None
        """
        article = self.get_article(article_id)
        if not article:
            return None

        # Parser le contenu pour extraire l'analyse
        return self._parse_circuit_analysis(article)

    def _parse_article(self, html: str, url: str) -> VikazimutAnalysis:
        """Parse le HTML d'un article."""
        soup = BeautifulSoup(html, "html.parser")

        # Titre
        title = ""
        title_elem = soup.select_one("h1, .title, .article-title")
        if title_elem:
            title = title_elem.get_text(strip=True)

        # Contenu
        content = ""
        content_elem = soup.select_one("article, .content, .article-content")
        if content_elem:
            content = content_elem.get_text(strip=True)

        # Extraire l'ID depuis l'URL
        article_id = url.split("/")[-1] if "/" in url else url

        # Date
        date = None
        date_elem = soup.select_one("time, .date, .published")
        if date_elem:
            date = date_elem.get("datetime") or date_elem.get_text(strip=True)

        # Auteur
        author = None
        author_elem = soup.select_one(".author, .byline, [rel='author']")
        if author_elem:
            author = author_elem.get_text(strip=True)

        # Tags
        tags = []
        tag_elems = soup.select(".tag, .tags a, [rel='tag']")
        for tag in tag_elems:
            tags.append(tag.get_text(strip=True))

        return VikazimutAnalysis(
            article_id=article_id,
            title=title,
            url=url,
            date=date,
            author=author,
            content=content,
            tags=tags,
        )

    def _parse_circuit_analysis(self, article: VikazimutAnalysis) -> VikazimutCircuit:
        """Parse le contenu pour extraire l'analyse du circuit."""
        # Simulation - dans la réalité, parser le contenu structuré
        circuit = VikazimutCircuit(
            name=article.circuit_name or "Circuit analysé",
            category="Analyse technique",
        )

        # Analyser le contenu pour extraire forces/faiblesses
        content_lower = article.content.lower()

        # Mots-clés pour les forces
        strength_keywords = [
            "bien conçu",
            "excellent",
            "bonne idée",
            "intéressant",
            "varié",
            "technique",
            "équilibré",
            "choix",
            "belle",
        ]
        for kw in strength_keywords:
            if kw in content_lower:
                circuit.strengths.append(kw)

        # Mots-clés pour les faiblesses
        weakness_keywords = [
            "problème",
            "difficulté",
            "trop simple",
            "linéaire",
            "danger",
            "attention",
            "éviter",
            "court",
            "long",
        ]
        for kw in weakness_keywords:
            if kw in content_lower:
                circuit.weaknesses.append(kw)

        # Suggestions (phrases avec "conseil", "suggestion", "pourrait")
        lines = article.content.split("\n")
        for line in lines:
            if any(
                word in line.lower()
                for word in ["conseil", "suggestion", "建议", "pourrait"]
            ):
                if len(line) > 20:
                    circuit.suggestions.append(line.strip())

        # Ajouter le contenu complet
        circuit.analysis = article.content[:2000]  # Limiter la taille

        return circuit


# =============================================
# Fonctions utilitaires
# =============================================
def export_analysis_to_text(analysis: VikazimutAnalysis) -> str:
    """
    Exporte une analyse en texte pour le RAG.

    Args:
        analysis: Analyse à exporter

    Returns:
        Texte formaté
    """
    lines = [
        f"Titre: {analysis.title}",
        f"URL: {analysis.url}",
        f"Date: {analysis.date or 'Inconnue'}",
        f"Auteur: {analysis.author or 'Inconnu'}",
        "",
        "Tags: " + ", ".join(analysis.tags) if analysis.tags else "Aucun",
        "",
        "Contenu:",
        analysis.content,
    ]

    return "\n".join(lines)


def export_circuit_to_text(circuit: VikazimutCircuit) -> str:
    """
    Exporte une analyse de circuit en texte pour le RAG.

    Args:
        circuit: Circuit analysé

    Returns:
        Texte formaté
    """
    lines = [
        f"Analyse de circuit: {circuit.name}",
        f"Catégorie: {circuit.category}",
        "",
    ]

    if circuit.strengths:
        lines.append("Points forts:")
        for s in circuit.strengths:
            lines.append(f"  - {s}")
        lines.append("")

    if circuit.weaknesses:
        lines.append("Points faibles:")
        for w in circuit.weaknesses:
            lines.append(f"  - {w}")
        lines.append("")

    if circuit.suggestions:
        lines.append("Suggestions:")
        for s in circuit.suggestions[:5]:
            lines.append(f"  - {s}")
        lines.append("")

    if circuit.analysis:
        lines.append("Analyse complète:")
        lines.append(circuit.analysis[:1000])

    return "\n".join(lines)
