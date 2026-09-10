# Azure account ownership handoff

**Audience:** an engineer or coding agent standing up this app on a **new** Azure
subscription / tenant because the previous owner's personal or named account
must be vacated.

**This repo** = OptiSweep AI Support Assistant (FastAPI + Streamlit playbook
runtime). It does **not** host ingestion or Brain HTTP. Corpus data is produced
by the separate **ingestion** repo (Stage 11 Cosmos publish). Brain HTTP is a
separate Container App owned by ingestion.

Full dependency map (stages, containers, embedding contract, learning loop,
coordination checklist):
[`docs/INGESTION_DEPENDENCIES.md`](docs/INGESTION_DEPENDENCIES.md).

Read [`README.md`](README.md) and [`docs/README.md`](docs/README.md) first for
product context. This file is only **infra transfer + bring-up**.

---

## 0. Success criteria

You are done when all of the following are true on the **new** account:

1. `GET https://<new-app-fqdn>/` opens Streamlit Home.
2. `GET https://<new-app-fqdn>` backend health via in-container API is OK
   (or local `GET http://127.0.0.1:8000/health` shows `embedding_total > 0`
   and a `publish_version_id`).
3. Guided Troubleshoot can pin/follow a playbook against Cosmos.
4. Search / Chat returns cited hits from the published corpus.
5. Secrets live in Key Vault (or Container App secret refs) — **not** in git.
6. GitHub Actions can deploy from the company repo using OIDC (no long-lived
   Azure passwords in workflows).
7. Old personal subscription resources are scheduled for deletion only after
   the new environment is verified (see §10).

---

## 1. Inventory what must move

### 1.1 Owned by **this app** (must recreate or transfer)

| Resource (current names — treat as examples) | Purpose |
|----------------------------------------------|---------|
| Resource group `optisweepai` | App + shared demo RG |
| Container Apps env `managedEnvironment-optisweepai-a18c` | Hosts app |
| Container App `optisweepai-troubleshooting-app` | Live UI+API |
| Container App `optisweepai-app-preview` | Preview (optional) |
| ACR `optisweepaiacr` | Docker images |
| Key Vault `optisweep-ai-keyvault` | Secret refs for Container App |
| Cosmos DB account + DB `optisweep_knowledge_phase0` | Publish corpus + sessions/logs |
| Storage account + blob containers | Canonical images + user attachments |
| Azure OpenAI (chat + `text-embedding-3-small`) | LLM agents + query embeddings |
| Azure AI Vision (optional) | Attachment image summaries |
| GitHub repo secrets/vars + Entra app registration for OIDC | CI deploy |

### 1.2 Owned by **ingestion** (coordinate; do not recreate blindly in this repo)

| Dependency | Why it matters |
|------------|----------------|
| Stage 11 publisher + `publish_manifest.json` | Fills playbook/runbook/embedding containers |
| Brain HTTP Container App (example URL in `.env.example`) | SME Review + optional retrieve/troubleshoot overlay |
| Brain `brain_*` Cosmos containers | Written only by Brain, never by this app |

If the new owner only moves **this** app but leaves corpus empty, the UI will
boot and then fail retrieval (`embedding_total = 0`). Plan ingestion publish
(or a Cosmos data export/import) in the same cutover.

### 1.3 Do **not** commit

- `.env`, Key Vault values, Cosmos keys, ACR passwords, OpenAI keys
- Personal subscription IDs, tenant IDs, or client secrets in markdown

---

## 2. Choose a cutover strategy

Pick one before provisioning:

| Strategy | When to use | Notes |
|----------|-------------|-------|
| **A. Subscription transfer / RG move** | Company can take ownership of the existing RG | Fastest; keep endpoints; re-point GitHub OIDC + IAM |
| **B. Greenfield + Cosmos data copy** | Must leave personal subscription entirely | Create new resources; export/import Cosmos + blobs; update all endpoints |
| **C. Greenfield + re-publish from ingestion** | Cleanest long-term | New empty Cosmos; run ingestion Stage 11 `--publish-to-cosmos` into new account |

**Recommended for company handoff:** **C** if ingestion is available; else **B**.
Use **A** only if IT can reassign the subscription.

Placeholder names below use:

```text
NEW_RG=optisweepai
NEW_LOCATION=eastus
NEW_COSMOS_ACCOUNT=<choose unique>
NEW_COSMOS_DB=optisweep_knowledge_phase0
NEW_ACR=<choose unique>
NEW_KV=<choose unique>
NEW_ACA_ENV=managedEnvironment-optisweepai
NEW_APP=optisweepai-troubleshooting-app
NEW_STORAGE=<choose unique>
```

---

## 3. Prerequisites (agent checklist)

Before Azure commands:

- [ ] Azure CLI logged into the **destination** subscription (`az account show`)
- [ ] Rights to create RG, Cosmos, Storage, ACR, Key Vault, Container Apps, OpenAI, role assignments
- [ ] Access to company GitHub repo (or fork) that will own Actions
- [ ] Python 3.12 locally for preflight / verify scripts
- [ ] Contact for **ingestion** owner (corpus + Brain HTTP base URL)
- [ ] Decision on strategy A/B/C above

Install tools if missing: `az`, Docker (for local image test), `gh` optional.

---

## 4. Provision Azure (greenfield path B/C)

Run in PowerShell or bash against the **new** subscription. Adjust names for
global uniqueness.

### 4.1 Resource group + Container Apps environment

```bash
az group create -n "$NEW_RG" -l "$NEW_LOCATION"

az containerapp env create \
  -g "$NEW_RG" -n "$NEW_ACA_ENV" -l "$NEW_LOCATION"
```

### 4.2 Azure Container Registry

```bash
az acr create -g "$NEW_RG" -n "$NEW_ACR" -l "$NEW_LOCATION" --sku Basic
az acr update -n "$NEW_ACR" --admin-enabled true   # optional; prefer MI + AcrPull later
```

### 4.3 Key Vault

```bash
az keyvault create -g "$NEW_RG" -n "$NEW_KV" -l "$NEW_LOCATION"
```

Secrets to create (names must match Container App `secretRef` in
`deploy/container-app.yaml`):

| Secret name | Value |
|-------------|-------|
| `cosmos-endpoint` | `https://<account>.documents.azure.com:443/` |
| `cosmos-key` | Cosmos **key** (not a URL) |
| `azure-openai-endpoint` | Cognitive Services / OpenAI endpoint URL |
| `azure-openai-api-key` | OpenAI key |
| `azure-openai-deployment` | Chat deployment name (e.g. `gpt-4o` / `gpt-5.4`) |

```bash
az keyvault secret set --vault-name "$NEW_KV" --name cosmos-endpoint --value "..."
az keyvault secret set --vault-name "$NEW_KV" --name cosmos-key --value "..."
az keyvault secret set --vault-name "$NEW_KV" --name azure-openai-endpoint --value "..."
az keyvault secret set --vault-name "$NEW_KV" --name azure-openai-api-key --value "..."
az keyvault secret set --vault-name "$NEW_KV" --name azure-openai-deployment --value "..."
```

Optional later: storage connection string, vision endpoint/key.

### 4.4 Cosmos DB

```bash
az cosmosdb create -g "$NEW_RG" -n "$NEW_COSMOS_ACCOUNT" --locations regionName="$NEW_LOCATION" --default-consistency-level Session
az cosmosdb sql database create -g "$NEW_RG" -a "$NEW_COSMOS_ACCOUNT" -n "$NEW_COSMOS_DB"
```

**Knowledge containers** (partition key `/publish_version_id`) — create empty,
then fill via ingestion publish or data copy:

| Container | Env var |
|-----------|---------|
| `runbooks` | `COSMOS_CONTAINER_RUNBOOKS` |
| `playbooks_prompt_a` | `COSMOS_CONTAINER_PLAYBOOKS_A` |
| `playbooks_prompt_b` | `COSMOS_CONTAINER_PLAYBOOKS_B` |
| `operational_context` | `COSMOS_CONTAINER_OPERATIONAL_CONTEXT` |
| `relationship_links` | `COSMOS_CONTAINER_RELATIONSHIP_LINKS` |
| `source_artifacts` | `COSMOS_CONTAINER_SOURCE_ARTIFACTS` |
| `publish_canonical_images` | `COSMOS_CONTAINER_CANONICAL_IMAGES` |
| `gate_phrase_tables` | `COSMOS_CONTAINER_GATE_PHRASE_TABLES` |

**Runtime memory containers** (app-owned; PK `/session_id`):

| Container | Backend flag |
|-----------|--------------|
| `workflow_sessions` | `SESSION_BACKEND=cosmos` |
| `interaction_logs` | `INTERACTION_LOG_BACKEND=cosmos` |
| `feedback_events` | `FEEDBACK_BACKEND=cosmos` |

Create SQL containers with the correct partition key. Example pattern:

```bash
az cosmosdb sql container create \
  -g "$NEW_RG" -a "$NEW_COSMOS_ACCOUNT" -d "$NEW_COSMOS_DB" \
  -n runbooks --partition-key-path '/publish_version_id'

az cosmosdb sql container create \
  -g "$NEW_RG" -a "$NEW_COSMOS_ACCOUNT" -d "$NEW_COSMOS_DB" \
  -n workflow_sessions --partition-key-path '/session_id'
```

Repeat for every container in the tables above.

Repo helper `python -m backend.app.scripts.create_cosmos_containers` only covers
**legacy Phase-1** definitions in `container_config.py` — it does **not** create
the Stage 11 publish containers. Prefer explicit `az` creates (or ingestion
publisher bootstrap) for knowledge containers.

### 4.5 Blob Storage

```bash
az storage account create -g "$NEW_RG" -n "$NEW_STORAGE" -l "$NEW_LOCATION" --sku Standard_LRS
```

Create blob containers:

| Container | Purpose |
|-----------|---------|
| `canonical-images` | Playbook/runbook screenshots (`AZURE_CANONICAL_IMAGES_CONTAINER`) |
| `user-interaction-attachments` | User uploads for feedback / vision |

Copy image blobs from the old account if doing strategy **B**; or let ingestion
re-upload on publish (strategy **C**).

### 4.6 Azure OpenAI

Create a resource and deploy:

1. **Chat** model → set as `AZURE_OPENAI_DEPLOYMENT`
2. **Embeddings** `text-embedding-3-small`, dimensions **1536** →
   `AZURE_EMBEDDINGS_DEPLOYMENT` / `AZURE_EMBEDDING_DIMENSIONS`

Query embeddings **must match** the model used when the corpus was embedded
(Stage 10). Mismatched dims → silent bad retrieval.

### 4.7 Azure AI Vision (optional)

Needed only for attachment image summaries. Set `AZURE_VISION_ENDPOINT` +
`AZURE_VISION_KEY` (or Computer Vision aliases) if enabling uploads.

---

## 5. Load the corpus

### Strategy C — re-publish (preferred)

In the **ingestion** repo (not this one):

1. Point Stage 11 publisher at `NEW_COSMOS_*` + storage.
2. Run cumulative publish / `--publish-to-cosmos`.
3. Copy `publish_version_id` and container names from `publish_manifest.json`
   into this app’s `.env` / Key Vault / Container App env.
4. Confirm embeddings exist for that version.

### Strategy B — copy

1. Export documents from old Cosmos (Data Migration tool, `az cosmosdb`, or
   custom script) for each knowledge container, filtered or full.
2. Import into new account preserving `id`, `publish_version_id`, `doc_type`,
   vectors, and payloads.
3. Copy `canonical-images` blobs; refresh SAS/`storage_uri` if URLs are account-bound
   (`backend.app.scripts.refresh_canonical_image_sas` may help after env is set).

### Verify from this repo

```powershell
# .env pointed at NEW cosmos + openai
python -m backend.app.scripts.verify_cosmos_corpus
# Expect non-zero embeddings for the resolved publish version
```

Optional E2E:

```powershell
$env:COSMOS_E2E = "1"
pytest tests/test_cosmos_corpus_integration.py -q
```

---

## 6. Local bring-up (validate before deploy)

```powershell
cd <repo-root>
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Fill COSMOS_*, AZURE_OPENAI_*, storage URLs; leave BRAIN_HTTP_* false until Brain URL is known
python scripts/preflight_deployment.py
uvicorn backend.app.main:app --reload
# second terminal:
streamlit run ui/Home.py
```

Checks:

```text
GET http://127.0.0.1:8000/health
  → status ok, embedding_total > 0, publish_version_id set, gate_phrase_table_loaded true

GET http://127.0.0.1:8000/debug/settings
  → backends = cosmos where expected; brain flags as intended
```

Smoke UI: Guided Troubleshoot one pin; Search / Chat one cited answer.

---

## 7. Wire GitHub → Azure deploy (OIDC)

Current workflow: [`.github/workflows/deploy-container-app.yml`](.github/workflows/deploy-container-app.yml).

**Important:** On some branches this workflow targets **preview**
(`optisweepai-app-preview` + GitHub Environment `preview`). For company live
deploy, set:

```text
CONTAINER_APP_NAME=<NEW_APP>
RESOURCE_GROUP=<NEW_RG>
CONTAINER_APP_ENVIRONMENT=<NEW_ACA_ENV>
IMAGE_NAME=<NEW_ACR>.azurecr.io/optisweepai/troubleshooting-app
```

and use Environment `production` (or remove `environment:` until ready).

### 7.1 Entra app registration for GitHub Actions

1. Create App registration in the **destination** tenant.
2. Federated credential subject examples:
   - `repo:<ORG>/<REPO>:environment:production`
   - `repo:<ORG>/<REPO>:ref:refs/heads/main`
3. Assign roles on the RG (e.g. Contributor) + `AcrPush` on ACR +
   Key Vault Secrets Officer/User as needed.

### 7.2 GitHub configuration

**Secrets** (repo or environment):

| Name | Purpose |
|------|---------|
| `AZURE_CLIENT_ID` | Federated app client id |
| `AZURE_TENANT_ID` | Destination tenant |
| `AZURE_SUBSCRIPTION_ID` | Destination subscription |
| `AZURE_ACR_USERNAME` / `AZURE_ACR_PASSWORD` | If workflow uses admin pull/push |

**Variables:**

| Name | Purpose |
|------|---------|
| `AZURE_ACR_NAME` | ACR name without or with `.azurecr.io` |

### 7.3 Container App secrets

Point Container App secret refs at **new** Key Vault URLs (same secret names as
in `deploy/container-app.yaml`: `cosmos-endpoint`, `cosmos-key`,
`azure-openai-endpoint`, `azure-openai-api-key`, `azure-openai-deployment`).

Grant the Container App system-assigned identity:

- `AcrPull` on ACR
- `Key Vault Secrets User` on Key Vault

### 7.4 First deploy

```text
Actions → Deploy OptiSweep AI to Azure Container Apps → Run workflow
```

Or build/push manually:

```bash
az acr build -r "$NEW_ACR" -t optisweepai/troubleshooting-app:manual -f Dockerfile .
# then create/update container app with deploy/container-app.yaml
# image = $NEW_ACR.azurecr.io/optisweepai/troubleshooting-app:manual
# ingress external, targetPort 8501
```

Ingress **must** be port **8501** (Streamlit). FastAPI listens on `127.0.0.1:8000`
inside the same container (`scripts/start_azure_container_app.py`).

Non-secret env in YAML already sets Cosmos container names, embedding model,
and `AUTO_PUBLISH_VERSION=true`. Update `BRAIN_HTTP_BASE_URL` to the **new**
Brain host (or set flags `false` until Brain is moved).

---

## 8. Brain HTTP (optional but needed for SME Review)

1. Confirm with ingestion that Brain HTTP is deployed on the new account (or
   still reachable during transition).
2. Set on the app Container App / `.env`:

```text
BRAIN_HTTP_BASE_URL=https://<brain-host>
BRAIN_HTTP_ENABLED=true|false
BRAIN_HTTP_RETRIEVE=...
BRAIN_HTTP_TROUBLESHOOT=...
BRAIN_HTTP_FEEDBACK=...
BRAIN_HTTP_REVIEWS=...
BRAIN_HTTP_TIMEOUT_SECONDS=90
```

3. Defaults in `.env.example` are **off**. Live YAML currently turns them **on**
   against the Brain URL. Brain HTTP **v4** cold retrieve is ~40–50s (warm ~2s);
   keep timeout ≥ 90s. (Pre-v4 3–4 min latency was a cache/provider bug, not ANN.)

Contract: [`docs/brain/HTTP_BOUNDARY.md`](docs/brain/HTTP_BOUNDARY.md).

---

## 9. Post-cutover verification (agent runbook)

| Step | Command / action | Pass |
|------|------------------|------|
| 1 | `python scripts/preflight_deployment.py` | Exit 0 |
| 2 | `python -m backend.app.scripts.verify_cosmos_corpus` | Embeddings > 0 |
| 3 | Open Container App FQDN | Home loads |
| 4 | Guided Troubleshoot: enter a known symptom phrase | Candidates or pin |
| 5 | Search / Chat: ask a runbook question | Answer + Sources |
| 6 | Turns tab | Interaction logs persist if `INTERACTION_LOG_BACKEND=cosmos` |
| 7 | SME Review (if Brain on) | Queue loads or clear empty state |
| 8 | Confirm no secrets in git / workflow logs | — |

---

## 10. Decommission the old (personal) account

Only after §9 passes for **≥1 business day** (or stakeholder sign-off):

1. Snapshot / export any remaining Cosmos + Key Vault secrets to company secure
   storage (password manager / company KV).
2. Transfer GitHub repo ownership to the company org if still under a personal
   user; update OIDC federated subjects.
3. Disable old Container Apps (scale to 0) → delete preview → delete live.
4. Delete or lock old ACR, Key Vault, OpenAI, Storage, Cosmos.
5. Remove old Entra app registrations and federated credentials.
6. Cancel personal Azure spend alerts / subscription if applicable.
7. Update Confluence / Haslet runbooks with the **new** FQDN and owners.

Do **not** delete old Cosmos until a restore drill from the new account has
succeeded.

---

## 11. Common failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `embedding_total = 0` | Wrong DB/account or empty publish | Re-publish or fix `COSMOS_*` / `AUTO_PUBLISH_VERSION` |
| App starts then crashes on Cosmos | `COSMOS_KEY` set to endpoint URL | Use master key only |
| Retrieval returns nonsense | Embedding model/dims ≠ corpus | Align `text-embedding-3-small` / 1536 |
| Images broken | Old SAS URLs | Refresh SAS or re-publish images |
| Deploy 401 from ACR | Missing `AcrPull` / admin creds | Role assign or ACR admin for first push |
| Streamlit blank / wrong port | Ingress not 8501 | Fix Container App target port |
| SME Review errors | Brain URL still on old host | Update `BRAIN_HTTP_BASE_URL` or disable flags |
| Cold Brain retrieve timeout | Pre-v4 cache bug (~3–4 min) or Brain down | Prefer Brain **v4+**; timeout 90s; check `BRAIN_HTTP_BASE_URL` |

---

## 12. File map for agents

| Path | Use |
|------|-----|
| `.env.example` | Local/runtime env template |
| `ui/README.md` | Streamlit UX, backends, Brain learning loop, screenshots |
| `deploy/container-app.yaml` | Live Container App template |
| `deploy/container-app-preview.yaml` | Preview template |
| `Dockerfile` | Image build |
| `scripts/start_azure_container_app.py` | Process supervisor (API + UI) |
| `scripts/preflight_deployment.py` | Deploy input validation |
| `.github/workflows/deploy-container-app.yml` | CI deploy (check preview vs live targeting) |
| `docs/cosmos_data_map.md` | Container + document shapes |
| `docs/brain/HTTP_BOUNDARY.md` | Brain client contract |

---

## 13. Ownership handoff checklist (human)

- [ ] New Azure subscription / RG owner named
- [ ] GitHub org + Actions environments configured
- [ ] Ingestion owner confirmed for corpus + Brain URL
- [ ] Local verify + Azure verify both green
- [ ] Docs/Confluence updated with new URLs
- [ ] Old account deletion date scheduled
- [ ] This file’s example resource names updated to the **new** production names
  (edit §1.1 / placeholders so the next person is not pointed at a dead account)
