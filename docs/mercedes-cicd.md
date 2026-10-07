# Mercedes-Benz CI/CD integration

NTF Insight is intended for use in a Mercedes-Benz environment. The repository therefore keeps the application build and quality gates **portable** so an internal Mercedes-Benz pipeline can call the same commands as the public development CI.

> This repository does **not** contain or claim an official Mercedes-Benz internal pipeline template. Internal runner images, artifact repositories, security scanners, certificate/signing services, deployment environments and secret names are company-specific and must be connected using the approved internal template available to the project.

## Pipeline contract

An internal pipeline should execute the following stages.

### 1. Validate / test

```bash
python -m pip install -e ".[dev]"
python ci/quality_gate.py
```

The quality gate produces:

- `reports/junit.xml`
- `reports/coverage.xml`
- terminal coverage output
- Ruff static checks
- Python bytecode compilation check
- full pytest suite including an offscreen PySide6 GUI smoke test

The same command is used by GitHub Actions to reduce CI drift.

### 2. Security / compliance

Connect the approved Mercedes-Benz internal tooling for:

- SAST
- software-composition / dependency scanning
- license policy checks
- secret scanning
- SBOM generation
- malware scanning of produced artifacts

Do not substitute an unapproved public scanner if internal policy requires a specific service.

### 3. Package

For the current Python package:

```bash
python -m build --wheel
```

For desktop rollout, add the approved Windows packaging mechanism later (for example the internally approved PyInstaller/Nuitka/MSIX path). Packaging is intentionally kept separate from application logic.

### 4. Sign

Windows executable/installers should be signed only through the approved Mercedes-Benz certificate/code-signing process. Certificates or tokens must never be stored in this repository.

### 5. Publish / deploy

Publish only to the approved internal artifact repository/software distribution channel. The concrete repository URL, runner labels and deployment credentials belong in the internal pipeline configuration, not in application source code.

## Recommended quality gates

Before a merge/release, require at minimum:

- unit/integration tests pass
- Windows GUI smoke test passes
- Ruff has no errors
- coverage report is produced
- internal SAST/SCA/license gates pass
- no credentials or real vehicle/customer data in Git
- release artifact is traceable to commit SHA
- production package is signed by the approved process

## Required internal inputs

To turn this adapter into the actual Mercedes-Benz deployment pipeline, provide or map the project-approved internal equivalents for:

- CI platform/template (for example internal GitLab/Jenkins/other)
- runner/container image
- Python/PyPI mirror
- artifact repository
- SAST/SCA/license scanner
- SBOM policy
- Windows packaging standard
- code-signing service
- deployment/software-distribution target

Once those are known, only the thin pipeline adapter should change. The reusable `ci/quality_gate.py` stays the same.
