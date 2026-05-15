# Python Setup – Vollständige Anleitung

## 1. pyenv Installation

### Schritt 1: Installer ausführen
```bash
curl https://pyenv.run | bash
```

### Schritt 2: Shell-Konfiguration aktualisieren

**Für bash** – `~/.bashrc` anpassen:
```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

**Für zsh** – `~/.zshrc` anpassen:
```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

### Schritt 3: Shell neuladen
```bash
exec $SHELL
```

### Schritt 4: Abhängigkeiten installieren (Linux)
```bash
sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
  xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

### Schritt 5: Testen
```bash
pyenv versions
```

---

## 2. Python-Version installieren und setzen

### Installation
```bash
# Verfügbare Versionen anschauen
pyenv install --list

# Spezifische Version installieren
pyenv install 3.12.0

# Global setzen
pyenv global 3.12.0

# Überprüfen
python --version
```

---

## 3. Virtuelles Environment pro Projekt

### Setup im Projekt
```bash
cd my-project
pyenv local 3.12.0                # Optional: Python-Version für Projekt fixieren
python -m venv venv               # Virtual Environment erstellen
source venv/bin/activate          # Aktivieren (Linux/macOS)
# oder Windows: venv\Scripts\activate
```

### Dependencies installieren
```bash
pip install package-name
# oder aus Datei:
pip install -r requirements.txt
```

### Environment deaktivieren
```bash
deactivate
```

---

## 4. Git-Konfiguration

### `.gitignore` hinzufügen
```
venv/
__pycache__/
*.pyc
.env
.python-version
```

---

## 5. Dependencies verwalten

### Dependencies exportieren
```bash
pip freeze > requirements.txt
```

### Dependencies später installieren
```bash
pip install -r requirements.txt
```

---

## 6. Wichtigste pyenv-Kommandos

| Kommando | Zweck |
|----------|-------|
| `pyenv versions` | Installierte Versionen anzeigen |
| `pyenv install 3.12.0` | Python-Version installieren |
| `pyenv global 3.12.0` | Globale Standard-Version |
| `pyenv local 3.12.0` | Projekt-spezifische Version (`.python-version`) |
| `pyenv shell 3.11.0` | Version nur für aktuelles Terminal |
| `pyenv uninstall 3.11.0` | Version deinstallieren |

---

## 7. Typischer Workflow

```bash
# 1. Python-Version installieren und setzen
pyenv install 3.12.0
pyenv global 3.12.0

# 2. In Projekt gehen
cd ~/dev/mein-projekt

# 3. Projekt-spezifische Version
pyenv local 3.12.0

# 4. Virtual Environment
python -m venv venv
source venv/bin/activate

# 5. Packages installieren
pip install flask requests

# 6. Dependencies speichern
pip freeze > requirements.txt

# 7. Arbeiten...
python app.py

# 8. Environment deaktivieren
deactivate
```

---

## 8. Alternative Tools

### poetry (moderner, mit Dependency-Locking)
```bash
curl -sSL https://install.python-poetry.org | python3 -
poetry new my-project
cd my-project
poetry add flask
```

### uv (schneller, von Astral)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv pip install flask
```

---

## Troubleshooting

### pyenv wird nicht gefunden
```bash
exec $SHELL  # Shell neuladen nach .bashrc/.zshrc Änderung
```

### Falsche Python-Version wird verwendet
```bash
which python
pyenv which python
python --version
```

### Virtual Environment aktiviert sich nicht
```bash
# Absoluter Pfad testen
/home/user/project/venv/bin/python --version
```
