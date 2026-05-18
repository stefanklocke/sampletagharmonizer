# Local Operations

## Remount Synology NAS in WSL

When Windows already sees the Synology share as drive `Z:` but WSL does not show `/mnt/z`, create the mount point and mount the Windows network drive through `drvfs`:

```bash
sudo mkdir -p /mnt/z
sudo mount -t drvfs Z: /mnt/z
```

Verify that the dataset is visible:

```bash
ls /mnt/z
ls "/mnt/z/stefan.klocke/DATA/AudioSamples/Native Instruments"
```

If `/mnt/z` exists but looks stale or empty, unmount and mount again:

```bash
sudo umount /mnt/z
sudo mount -t drvfs Z: /mnt/z
```

The project currently expects the NI dataset path to be available through `DATASET_PATH_NI` in `.env`.

## Sync Local Repository After GitHub Merge

After a PR was merged on GitHub and the remote branch was deleted, update the local repository:

```bash
git switch main
git pull
git fetch --prune
git branch -d <branch-name>
git status
git branch
```

Example:

```bash
git switch main
git pull
git fetch --prune
git branch -d feature/metadata-observations
git status
git branch
```

Expected result:

- current branch is `main`
- `main` is up to date with `origin/main`
- working tree is clean
- merged feature branch is removed locally

## Python Setup

### pyenv Installation

Run the installer:

```bash
curl https://pyenv.run | bash
```

Add pyenv to the shell configuration.

For bash, update `~/.bashrc`:

```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

For zsh, update `~/.zshrc`:

```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

Reload the shell:

```bash
exec "$SHELL"
```

Install Linux build dependencies:

```bash
sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
  xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

Verify pyenv:

```bash
pyenv versions
```

### Python Version

List available versions:

```bash
pyenv install --list
```

Install and select a Python version:

```bash
pyenv install 3.12.0
pyenv global 3.12.0
python --version
```

For a project-specific version:

```bash
pyenv local 3.12.0
```

### Virtual Environment

Create and activate a virtual environment in the project:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install the project in editable mode:

```bash
pip install -e .
```

Deactivate the environment:

```bash
deactivate
```

### Dependency Management

Export installed dependencies:

```bash
pip freeze > requirements.txt
```

Install dependencies later:

```bash
pip install -r requirements.txt
```

### Useful pyenv Commands

| Command | Purpose |
| --- | --- |
| `pyenv versions` | Show installed versions |
| `pyenv install 3.12.0` | Install a Python version |
| `pyenv global 3.12.0` | Set global default version |
| `pyenv local 3.12.0` | Set project-specific version through `.python-version` |
| `pyenv shell 3.11.0` | Set version for the current shell |
| `pyenv uninstall 3.11.0` | Uninstall a Python version |

### Alternative Tools

Poetry:

```bash
curl -sSL https://install.python-poetry.org | python3 -
poetry new my-project
cd my-project
poetry add flask
```

uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv pip install flask
```

### Troubleshooting

If pyenv is not found after installation:

```bash
exec "$SHELL"
```

If the wrong Python version is used:

```bash
which python
pyenv which python
python --version
```

If the virtual environment does not activate as expected:

```bash
/home/user/project/.venv/bin/python --version
```
