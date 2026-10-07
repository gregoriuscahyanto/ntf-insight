# Managed Windows environment

NTF Insight is expected to run on managed enterprise Windows clients.

## Pytest temporary directory

Some managed Windows configurations restrict access below the user-wide system temp directory, for example:

```text
C:\Users\<user>\AppData\Local\Temp
```

The repository therefore configures pytest to use a **repository-local** temporary directory:

```text
.pytest-tmp/
```

This is configured in `pyproject.toml` through:

```toml
[tool.pytest.ini_options]
addopts = "--basetemp=.pytest-tmp"
```

The application report-acquisition workflow likewise avoids the system temp directory and creates temporary work directories below the configured NTF Insight data directory.

## Local application data

Default:

```text
%USERPROFILE%\.ntf-insight\
├── ntf-insight.duckdb
├── raw\
├── work\
└── logs\
```

Override with:

```powershell
$env:NTF_INSIGHT_DATA_DIR = "D:\approved\ntf-insight-data"
python -m ntf_insight
```

Use only a location approved for the actual vehicle/supplier data classification.

## Tests

After updating the repository:

```powershell
git pull
python -m pip install -e ".[dev]"
pytest
```

If an old repository-local pytest directory is left from an interrupted run, it can be removed before retrying:

```powershell
Remove-Item -Recurse -Force .pytest-tmp -ErrorAction SilentlyContinue
pytest
```
