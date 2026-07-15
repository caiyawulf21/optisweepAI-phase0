# OptiSweep AI App — Azure Container Apps Deployment Handoff

**Application:** `optisweep-ai-app`  
**Azure subscription:** `Azure subscription 1`  
**Resource group:** `optisweepai`  
**Container Apps environment:** `managedEnvironment-optisweepai-bba4`  
**Region:** `eastus`  
**Workload profile:** Consumption  
**Primary deployment source:** GitHub repository  
**Purpose:** Demo and validation deployment of the OptiSweep AI troubleshooting application

---

## 1. Deployment Model

The recommended deployment model is continuous deployment from a designated GitHub branch.

```text
Developer updates GitHub repository
                |
                v
GitHub Actions workflow starts
                |
                v
Application dependencies and source are validated
                |
                v
Cloud build creates a new container image
                |
                v
Image is pushed to Azure Container Registry
                |
                v
Azure Container Apps creates a new immutable revision
                |
                v
New revision becomes active and serves the application URL
```

No application secrets should be stored in the repository or container image. Runtime secrets should be supplied by Azure Container Apps through Azure Key Vault references or Container App secret references.

---

## 2. What Happens When the GitHub Repository Is Updated

The behavior depends on whether the changed branch is configured as the deployment branch.

### Changes pushed to the deployment branch

For example, if the workflow listens to `main`:

1. A developer merges or pushes a commit to `main`.
2. GitHub Actions starts the deployment workflow.
3. The workflow checks out the new commit.
4. The workflow authenticates to Azure.
5. Azure builds a container image from the repository source.
6. The image is tagged for that version, preferably using the Git commit SHA.
7. The image is pushed to Azure Container Registry.
8. Azure Container Apps creates a new revision of `optisweep-ai-app`.
9. The new revision starts with the existing Container App configuration, environment variables, secret references, ingress settings, and scaling rules.
10. Traffic is directed to the new revision according to the configured revision mode.

### Changes pushed to another branch

No deployment occurs unless the GitHub Actions workflow includes that branch.

Recommended branch model:

```text
feature/*  -> development only; no Azure deployment
main       -> approved demo deployment
```

For a larger production implementation, add separate `dev`, `test`, and `production` environments later. One deployment branch is sufficient for the current demo.

### If the build fails

The GitHub Actions workflow reports a failure, but the currently active Container Apps revision remains available. A failed build does not overwrite the existing working revision.

### If the build succeeds but the application fails to start

Azure may create the revision, but the revision can remain unhealthy because its container does not bind to the expected port, crashes during startup, or lacks required configuration. Review:

- GitHub Actions logs
- Container App revision status
- Container App console and system logs
- Missing environment variables
- Incorrect startup command
- Incorrect target port
- Missing runtime files or Python dependencies

Do not delete the last healthy revision until the new one has been validated.

---

## 3. Recommended Revision Behavior

Azure Container Apps represents each deployed version as an immutable revision.

For the current demo, use **single revision mode** unless controlled testing between two versions is required.

### Single revision mode

- The newest healthy revision receives traffic.
- The prior revision remains available in revision history but is inactive.
- Rollback is performed by reactivating or copying a prior revision.

### Multiple revision mode

- Multiple revisions may be active simultaneously.
- Traffic can be split between versions.
- This is useful for blue-green deployments or stakeholder testing, but it is unnecessary for the initial demo.

Recommended current setting:

```text
Revision mode: Single
Deployment branch: main
Image tag: Git commit SHA
```

---

## 4. Repository Requirements

The repository must be self-contained enough for a Linux-based cloud build. Anything that exists only on a developer laptop will not exist in the deployed application.

Recommended structure:

```text
optisweep-ai-app/
├── .github/
│   └── workflows/
│       └── deploy-container-app.yml
├── backend/
│   └── app/
│       ├── api/
│       ├── graph/
│       ├── routing/
│       ├── repositories/
│       ├── models/
│       └── ...
├── frontend/
│   └── streamlit_app.py
├── data/
│   └── runtime/
│       ├── workflows/
│       ├── procedures/
│       └── retrieval/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

Adjust the paths to match the actual repository. The important requirement is that the workflow's `appSourcePath` points to the directory containing the application entry point and dependency file.

---

## 5. What the Application Code Must Do

The application must satisfy the following runtime contract.

### 5.1 Run on Linux

The Azure container runs on Linux. The code must not depend on:

- Windows-only paths such as `C:\Users\...`
- locally mounted drives
- desktop applications
- interactive terminal input
- files outside the repository or configured Azure storage

Use `pathlib.Path` and paths relative to the project root.

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "data" / "runtime"))
```

### 5.2 Read configuration from environment variables

Required settings must be read at runtime rather than hardcoded.

```python
import os


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


AZURE_OPENAI_ENDPOINT = require_env("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = require_env("AZURE_OPENAI_DEPLOYMENT")
```

The app may use a local `.env` file for local development, but production deployment must not depend on that file.

### 5.3 Bind to the correct host and port

The application must listen on all interfaces, not only `localhost`.

For Streamlit:

```bash
streamlit run frontend/streamlit_app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

For FastAPI:

```bash
uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port 8000
```

The Azure Container App target port must match the process port.

Recommended initial deployment:

```text
Single Streamlit-facing application
Target port: 8501
External ingress: Enabled
```

If Streamlit imports and invokes the application services directly, do not run a second FastAPI process merely for architecture purity. For the demo, one process is simpler and more reliable.

If the UI truly requires HTTP calls to FastAPI, then either:

1. run both processes with a deliberate process manager in the same container, or
2. deploy Streamlit and FastAPI as separate Container Apps.

Option 2 is cleaner for production, but it adds deployment complexity. Avoid it for the first working demo unless the current code already requires separate services.

### 5.4 Include every runtime dependency

`requirements.txt` must contain all imported production packages.

Example categories:

```text
streamlit
fastapi
uvicorn
pydantic
langgraph
langchain
langchain-openai
azure-identity
azure-keyvault-secrets
azure-cosmos
python-dotenv
```

Do not blindly copy this list. Generate the dependency file from the application's real imports and pin compatible versions when practical.

### 5.5 Include required runtime knowledge assets

The current demo uses local retrieval and canonical workflow/procedure files. Approved runtime assets must either:

- be included in the repository and therefore copied into the image, or
- be downloaded from Azure storage during startup, or
- be read from Cosmos DB or Azure AI Search.

Recommended for the immediate demo:

```text
Package only the approved, non-sensitive runtime data in data/runtime/.
```

Do not package:

- raw Teams exports
- unrestricted Salesforce case data
- unapproved incident notes
- local developer files
- secrets
- source documents that are not approved for repository storage

The app should validate required files during startup and produce a clear error when one is missing.

```python
required_path = DATA_ROOT / "workflows"
if not required_path.exists():
    raise RuntimeError(f"Runtime workflow directory not found: {required_path}")
```

### 5.6 Provide a health endpoint or startup check

For FastAPI, provide a lightweight endpoint:

```python
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

For Streamlit, ensure the initial page can load without immediately executing a full LLM request. Display configuration errors clearly without exposing secret values.

### 5.7 Log to standard output

Use Python logging rather than writing logs only to local files. Azure captures standard output and standard error.

```python
import logging

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
```

Never log:

- API keys
- access tokens
- complete connection strings
- confidential case payloads
- user credentials

---

## 6. Build Strategy Without a Locally Created Dockerfile

There are two viable deployment approaches.

### Option A — GitHub Actions source build without a Dockerfile

The `azure/container-apps-deploy-action` can attempt to build supported Python source when no Dockerfile exists.

This is acceptable when:

- the Python project is conventional
- the dependency file is in the source path
- the startup process can be detected or explicitly configured
- only one application process is required

Example workflow:

```yaml
name: Deploy OptiSweep AI to Azure Container Apps

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Log in to Azure
        uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Build and deploy Container App
        uses: azure/container-apps-deploy-action@v1
        with:
          appSourcePath: ${{ github.workspace }}
          acrName: <ACR_NAME>
          containerAppName: optisweep-ai-app
          resourceGroup: optisweepai
```

Replace `<ACR_NAME>` after Azure Container Registry is created or identified.

**Important:** source auto-detection is less predictable for a nonstandard monorepo. The source path must contain the correct `requirements.txt` and application entry point.

### Option B — Add a Dockerfile to the repository

This is the more reliable long-term approach because it makes the startup command, file copy behavior, and port explicit. Docker does not need to be installed locally merely to store a Dockerfile in GitHub; a coding agent or GitHub's web editor can create the file, and GitHub/Azure performs the build remotely.

Recommended when:

- the repository contains both Streamlit and FastAPI
- source auto-detection fails
- the project has nonstandard paths
- build reproducibility matters
- system-level packages are required

Example Streamlit Dockerfile:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
```

The actual entry-point path must match the repository.

### Recommendation

Try Option A once if avoiding a Dockerfile is a hard requirement. Use Option B if the source build cannot reliably identify the application or start it. For a multi-folder OptiSweep repository, a small Dockerfile is likely to be the more maintainable handoff artifact.

---

## 7. GitHub Actions Authentication

The workflow needs permission to deploy Azure resources. This is separate from the credentials used by the running application.

### Preferred enterprise approach

Use GitHub OpenID Connect federation with Microsoft Entra ID. This avoids storing a long-lived Azure client secret in GitHub.

The workflow would use:

```yaml
permissions:
  id-token: write
  contents: read

- name: Log in to Azure
  uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

This requires an Azure administrator or authorized user to create the federated credential and appropriate role assignments.

### Simpler temporary approach

Use a service principal stored as the GitHub repository secret `AZURE_CREDENTIALS`.

This is easier for a demo but uses a long-lived credential and should follow enterprise security policy.

Do not place Azure credentials directly inside the workflow YAML.

---

## 8. Runtime Secrets and Configuration

### Sensitive values

Store sensitive values in Azure Key Vault or Container App secrets:

```text
AZURE_OPENAI_API_KEY
AZURE_COSMOS_KEY
AZURE_SEARCH_KEY
connection strings
client secrets
access tokens
```

### Non-sensitive values

Set ordinary Container App environment variables directly:

```text
APP_ENV=demo
LOG_LEVEL=INFO
AZURE_OPENAI_ENDPOINT=<endpoint>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_OPENAI_API_VERSION=<version>
RETRIEVAL_BACKEND=local_bm25
DATA_ROOT=/app/data/runtime
```

Whether an endpoint is considered sensitive depends on company policy. API keys and tokens are always sensitive.

### Key Vault pattern

```text
Azure Key Vault secret
        |
        v
Container App secret reference
        |
        v
Container environment variable
        |
        v
Python os.environ
```

Required setup:

1. Enable system-assigned managed identity on `optisweep-ai-app`.
2. Grant that identity `Key Vault Secrets User` on the Key Vault.
3. Add Container App secrets that reference Key Vault secret URIs.
4. Map environment variables to those Container App secrets.
5. Restart or create a new revision after configuration changes when necessary.

Updating application code does not require re-entering secrets. The new revision receives the Container App's existing secret and environment-variable configuration.

---

## 9. Initial Azure Container App Settings

Recommended demo settings:

```text
Container App: optisweep-ai-app
Resource group: optisweepai
Environment: managedEnvironment-optisweepai-bba4
Region: eastus
Ingress: External
Target port: 8501
Transport: Auto
Revision mode: Single
CPU: 1.0
Memory: 2 GiB
Minimum replicas: 1 during scheduled demos
Maximum replicas: 1 for the initial demo
```

After demonstrations, minimum replicas may be returned to `0` to reduce idle consumption.

The original `0.5 CPU / 1 GiB` setting may be insufficient when loading Streamlit, LangGraph, retrieval assets, and Azure SDK clients together.

---

## 10. First Deployment Procedure

### Azure owner / administrator

1. Confirm the Azure Container App exists.
2. Enable external ingress.
3. Set the target port to the application port.
4. Create or identify an Azure Container Registry.
5. Enable the Container App's system-assigned managed identity.
6. Grant the identity `AcrPull` on the registry.
7. Grant required access to Key Vault and other Azure resources.
8. Configure runtime environment variables and secret references.
9. Provide or approve the GitHub-to-Azure deployment identity.

### Repository owner

1. Confirm the deployable code is on the selected branch.
2. Add or validate `requirements.txt`.
3. Remove laptop-specific paths and assumptions.
4. Confirm the application binds to `0.0.0.0` and the selected port.
5. Add `.github/workflows/deploy-container-app.yml`.
6. Add the required GitHub Actions secrets or OIDC configuration.
7. Push or merge the workflow into `main`.
8. Monitor the first workflow under the GitHub **Actions** tab.
9. Verify the new revision in Azure.
10. Open the Container App application URL and execute a smoke test.

---

## 11. Normal Update Procedure

After initial setup, application updates should follow this process:

```text
1. Create a feature branch.
2. Make and test changes.
3. Open a pull request.
4. Confirm code review and automated checks pass.
5. Merge to main.
6. GitHub Actions builds and deploys automatically.
7. Confirm the new Container Apps revision is healthy.
8. Run the smoke-test prompts.
9. Record the deployed commit SHA and validation result.
```

The Azure URL normally remains the same while the underlying revision changes.

---

## 12. Changes That Require a Code Deployment

A GitHub deployment is required for changes to:

- Python source code
- Streamlit pages or UI components
- LangGraph orchestration
- routing logic
- bundled workflows or procedures
- bundled local BM25 retrieval data
- `requirements.txt`
- startup scripts
- application configuration defaults

---

## 13. Changes That Do Not Necessarily Require a Code Deployment

A code deployment is not normally required for:

- changing a Container App environment variable
- changing a Container App secret reference
- changing CPU or memory
- changing min/max replicas
- changing ingress configuration
- changing revision traffic weights
- changing a Key Vault secret value

Some configuration changes create a new revision automatically, and some secret changes require a restart or new revision before the running application reads the new value. Validate after every configuration change.

---

## 14. Data Update Decision

The handoff owner must understand where runtime data is stored.

### Current recommended demo approach

Approved workflow, procedure, and retrieval assets are committed in the repository.

Consequence:

```text
Updating runtime knowledge requires a Git commit and a new application revision.
```

This is acceptable for the demo because it creates a versioned, traceable package.

### Later production approach

Move mutable knowledge to:

- Cosmos DB
- Azure AI Search
- Blob Storage

Consequence:

```text
Knowledge can be updated without rebuilding the application image.
```

Do not introduce this migration merely to support the first demo. Complete it when the operational ownership and review process are ready.

---

## 15. Smoke-Test Checklist

Run after every deployment.

### Availability

- [ ] Application URL opens over HTTPS.
- [ ] Initial page loads without a crash.
- [ ] No secret values appear in the UI or logs.
- [ ] New revision status is healthy.

### Runtime configuration

- [ ] Azure OpenAI client initializes.
- [ ] Required deployment name is found.
- [ ] Retrieval backend initializes.
- [ ] Canonical workflow and procedure files load.
- [ ] Application can access required Azure resources.

### OptiSweep behavior

- [ ] A known high-confidence prompt routes to an approved workflow.
- [ ] A medium-confidence prompt asks the expected diagnostic question.
- [ ] A low-confidence prompt avoids inventing a workflow and uses retrieval/escalation behavior.
- [ ] Citations or source references render correctly.
- [ ] Escalation boundaries remain deterministic.

### Recommended validation prompts

Use the stakeholder-approved demo prompts, including:

- AGVs stopped with no alarms
- zone unable to get a pair after AMR replacement
- system stuck in bag-out
- tote still shown in RMS after removal

---

## 16. Rollback Procedure

Rollback is needed when the new revision starts but fails functional validation.

1. Open Azure Portal.
2. Navigate to `optisweep-ai-app`.
3. Open **Revisions and replicas**.
4. Identify the last validated revision.
5. Reactivate or copy the previous revision as appropriate.
6. Direct traffic back to the validated revision.
7. Confirm the public URL is working.
8. Record the failed commit SHA and failure reason.
9. Fix the issue in a new branch and redeploy through the normal workflow.

Do not edit a deployed revision in place. Revisions are immutable; deploy a corrected revision.

---

## 17. Troubleshooting Guide

### GitHub workflow does not start

Check:

- workflow file is under `.github/workflows/`
- pushed branch matches the `on.push.branches` configuration
- workflow YAML is valid
- GitHub Actions is enabled for the repository

### Azure login fails

Check:

- GitHub secret names match the workflow
- service principal or OIDC credential has not expired or been removed
- identity has access to the correct subscription/resource group
- tenant and subscription IDs are correct

### Build cannot identify the Python application

Check:

- `appSourcePath` points to the correct directory
- `requirements.txt` exists in that directory
- application entry point is conventional or explicitly configured
- repository structure is not hiding the app one level deeper

If auto-detection remains unreliable, add a repository Dockerfile.

### Revision starts and immediately crashes

Check:

- startup command and module path
- target port
- binding address is `0.0.0.0`
- missing Python package
- missing environment variable
- missing runtime data file
- file-name capitalization; Linux paths are case-sensitive

### App opens but LLM calls fail

Check:

- Azure OpenAI endpoint
- deployment name
- API version
- API key or managed identity role
- network restrictions
- model quota or deployment availability

### App opens but retrieval has no results

Check:

- runtime data directory exists inside the container
- `DATA_ROOT` matches the packaged location
- BM25 index or retrieval documents were committed
- initialization logs show the expected document count

---

## 18. Security Rules

The following are non-negotiable:

- Never commit `.env` files containing values.
- Never commit API keys or tokens.
- Never print secrets in logs.
- Never expose raw customer case data through a public demo.
- Never make the repository public without a data and intellectual-property review.
- Use least-privilege Azure role assignments.
- Keep application runtime identity separate from deployment identity.
- Preserve source citations and support-safe/engineer-required boundaries.

Recommended `.gitignore` entries:

```gitignore
.env
.env.*
!.env.example
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.streamlit/secrets.toml
```

---

## 19. Coding-Agent Implementation Prompt

The following prompt can be provided to Cursor, Codex, or another coding agent working inside the application repository.

```text
Prepare this OptiSweep AI application for deployment to Azure Container Apps from GitHub.

Deployment target:
- Azure resource group: optisweepai
- Container App: optisweep-ai-app
- Container Apps environment: managedEnvironment-optisweepai-bba4
- Region: eastus
- External ingress
- Target port: 8501 for the Streamlit application
- Deployment branch: main
- Build occurs in GitHub/Azure; do not require Docker to be installed locally

Required work:
1. Inspect the repository and identify the actual Streamlit and FastAPI entry points.
2. Determine whether the demo can run as one Streamlit process that imports backend services directly. Prefer one process for the demo unless the code requires a separate FastAPI service.
3. Ensure the deployed process binds to 0.0.0.0 and the configured port.
4. Remove or replace Windows-specific and developer-machine-specific file paths.
5. Centralize runtime configuration in a typed settings module that reads environment variables.
6. Fail clearly when required environment variables or runtime assets are missing, without exposing secret values.
7. Ensure requirements.txt contains all production runtime dependencies and no unnecessary development-only dependencies.
8. Add an .env.example containing variable names only. Confirm real .env files and Streamlit secrets are ignored.
9. Verify approved local retrieval, workflow, and procedure assets are included under a stable runtime data directory and are loaded using relative paths or DATA_ROOT.
10. Add structured stdout logging and do not log keys, tokens, connection strings, or confidential source payloads.
11. Add a lightweight startup/health validation.
12. Add .github/workflows/deploy-container-app.yml using azure/login and azure/container-apps-deploy-action. Configure it to run on pushes to main and manual workflow dispatch.
13. Initially support source build without a Dockerfile when feasible. If the repository structure or startup requirements make source auto-detection unreliable, add a minimal production Dockerfile for Streamlit. The Dockerfile is committed as text and built remotely; do not assume local Docker access.
14. Do not place application secrets in GitHub Actions YAML. Use GitHub secrets only for deployment authentication and Azure Container App/Key Vault references for runtime secrets.
15. Add a deployment section to README.md that documents startup command, port, required environment variables, runtime data path, GitHub workflow, and smoke tests.
16. Add a script or automated test that verifies imports, required runtime files, and settings behavior before deployment.

Do not redesign the OptiSweep architecture, add new agents, migrate retrieval backends, or change approved workflow logic as part of this deployment task. The objective is a reliable demo deployment, not an infrastructure expansion.

Before changing files, report:
- detected repository root
- detected application entry point
- selected one-process or two-service deployment model
- selected source-build or Dockerfile approach
- required Azure environment variables
- runtime data directories that must be packaged

After implementation, report every file created or changed and provide exact Azure Portal values needed for ingress, target port, CPU, memory, and startup behavior.
```

---

## 20. Handoff Ownership Matrix

| Responsibility | Repository owner | Azure owner / IT | Application support owner |
|---|---:|---:|---:|
| Application code | Primary | — | Review |
| GitHub Actions workflow | Primary | Approve identity | Monitor |
| Deployment identity | Request | Primary | — |
| Container App configuration | Consulted | Primary | Review |
| Key Vault and secrets | No secret access unless authorized | Primary | Request updates |
| Runtime knowledge package | Primary during demo | — | Validate content |
| Workflow and procedure approval | Implement | — | Primary |
| Deployment smoke test | Primary | Support | Participate |
| Revision rollback | Support | Primary or delegated owner | Request |
| Production monitoring | Support | Platform support | Primary operational owner |

---

## 21. Definition of Done

Deployment handoff is complete when:

- [ ] A push or merge to `main` triggers GitHub Actions.
- [ ] The workflow builds without requiring Docker on the enterprise laptop.
- [ ] The image is stored in an approved registry.
- [ ] A new Container Apps revision is created.
- [ ] External HTTPS ingress is enabled.
- [ ] The app listens on the configured target port.
- [ ] Runtime secrets are not stored in GitHub.
- [ ] Approved demo knowledge assets are available in the container.
- [ ] All smoke tests pass.
- [ ] A previous revision can be restored.
- [ ] A named owner has access to GitHub Actions, Container Apps logs, Key Vault configuration, and revision management.

---

## 22. References

- [Deploy to Azure Container Apps with GitHub Actions](https://learn.microsoft.com/en-us/azure/container-apps/github-actions)
- [Build and deploy from a repository to Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/quickstart-repo-to-cloud)
- [Manage secrets in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets)
- [Manage environment variables in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/environment-variables)
- [Managed identities in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)
- [Update and deploy changes using Container Apps revisions](https://learn.microsoft.com/en-us/azure/container-apps/revisions)
- [Manage Azure Container Apps revisions](https://learn.microsoft.com/en-us/azure/container-apps/revisions-manage)
