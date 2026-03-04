# =============================================
# AItraceur - Backend Dockerfile
# Sprint 1: Setup minimal
# =============================================

FROM python:3.11-slim

# =============================================
# Étape 1: Préparer l'environnement
# =============================================
WORKDIR /app

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    # Pour le parsing de fichiers
    libmagic1 \
    # Pour les dépendances Python qui ont besoin de compilateurs
    build-essential \
    # Nettoyer
    && rm -rf /var/lib/apt/lists/*

# =============================================
# Étape 2: Copier les dépendances
# =============================================
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# =============================================
# Étape 3: Copier le code source
# =============================================
COPY src/ ./src/

# =============================================
# Étape 4: Créer les dossiers nécessaires
# =============================================
RUN mkdir -p /app/uploads

# =============================================
# Exposer le port
# =============================================
EXPOSE 8000

# =============================================
# Point d'entrée par défaut
# =============================================
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
