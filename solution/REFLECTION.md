# Enterprise Architecture Decision Records (ADR) & Operational Review

This document records key architectural decisions, operational diagnostics, and production engineering practices established during the design, deployment, and testing of the Enterprise Customer Support AI Agent Platform.

---

## ADR-001: Strict Schema Validation for Sandboxed Code Interpreter Execution

### Context & Problem Statement
The customer loyalty program requires precise, multi-variable financial calculations:
- Base point conversion ($1 per 100 points, redeemed in discrete blocks of 500 points up to a 50% order value cap).
- Tier-based percentage discounts (Silver 0%, Gold 10%, Platinum 15%) applied post-point redemption.
- Category-dependent point accrual rates (Standard 1x, Device 2x, Fresh 5x).

Large Language Models (LLMs) executing mental arithmetic or unstructured text generation risk mathematical hallucinations and precision errors. While offloading computation to the Amazon Bedrock AgentCore Code Interpreter executes Python in an isolated container sandbox, the execution output is returned via standard output (`stdout`) as unvalidated string data. If execution fails, outputs unparseable text, or emits malformed JSON, downstream agent reasoning can fail unpredictably.

### Decision
1. **Pydantic Model Enforcement**: All Code Interpreter executions serialize output as JSON, which is immediately parsed and validated against a strict Pydantic model (`LoyaltyDiscountResult`).
2. **Defensive Invariant Validation**: The schema enforces type constraints and numerical boundaries:
   - `points_redeemed`: non-negative integer.
   - `tier_discount_pct`: integer between 0 and 100.
   - `final_total`, `total_savings`: non-negative floats rounded to 2 decimal places.
3. **Deterministic Fallback Circuit**: If the remote sandbox times out, throws a runtime error, or returns schema-violating output, execution safely falls back to a local, tier-based deterministic calculation with `fallback: True`.
4. **Prompt Immutability Contract**: The system prompt instructs the foundation model to treat the tool's `display_text` as authoritative and prohibits recalculation or alteration of figures.

```
+--------------------------------------------------------------------------------------------------+
|                                    ADR-001 Validation Pipeline                                  |
|                                                                                                  |
|   Agent Tool Invocation ──> Sandboxed Python Execution ──> Raw Stdout JSON String                |
|                                                                    │                             |
|                                                                    v                             |
|                                                     LoyaltyDiscountResult.model_validate_json()  |
|                                                                    │                             |
|                                          ┌─────────────────────────┴─────────────────────────┐   |
|                                          ▼                                                   ▼   |
|                                    [Schema Valid]                                    [Schema Invalid]    |
|                                          │                                                   │   |
|                                          v                                                   v   |
|                              Return Sanitized Output                     Execute Tier-Only Fallback      |
+--------------------------------------------------------------------------------------------------+
```

### Consequences & Trade-offs
- **Positive**: Eliminates mathematical hallucinations; provides deterministic SLA guarantees; isolates agent from sandbox parsing failures.
- **Trade-off**: Requires strict synchronization between the sandboxed Python script template and the Pydantic schema definition.

---

## ADR-002: Graceful Degradation & Quota Fault-Tolerance in AgentCore Memory

### Context & Problem Statement
During deployment and testing against enterprise AWS accounts, account-level AWS service quota overrides can constrain AgentCore "Memories" to 0 (quota code `L-81002DCC`, default AWS quota is 150). Under this constraint, calling `CreateMemory` returns a generic `AccessDeniedException` rather than an explicit quota-exceeded error code.

In an unhardened system, failure to initialize memory strategies would cause catastrophic request failure, crashing the entire agent invocation and preventing customer support interactions.

### Decision
1. **Safe Initialization & Introspection**: `get_namespaces()` wraps memory strategy discovery in defensive exception handlers. If `MEMORY_ID` is unconfigured, set to a placeholder, or blocked by cloud quotas, it returns an empty dictionary rather than raising an unhandled exception.
2. **Dynamic Circuit Breaking**: `MemoryHook` checks namespace availability at initialization. If empty, `self.enabled` is set to `False`.
3. **No-Op Execution**: When disabled, both `retrieve_customer_context` (`MessageAddedEvent`) and `save_support_interaction` (`AfterInvocationEvent`) become zero-overhead no-ops.
4. **Seamless Activation**: Once service quotas are adjusted or enterprise memory identifiers are provided, updating `MEMORY_ID` immediately activates multi-session memory persistence without code modifications or redeployment.

```
+--------------------------------------------------------------------------------------------------+
|                                   ADR-002 Fault-Tolerance Flow                                   |
|                                                                                                  |
|   Inbound Customer Request ──────> MemoryHook Initialization                                     |
|                                                │                                                 |
|                                                v                                                 |
|                                  get_namespaces(MEMORY_ID)                                       |
|                                                │                                                 |
|                               ┌────────────────┴────────────────┐                                |
|                               ▼                                 ▼                                |
|                        [Namespaces Valid]             [Quota Block / Empty]                      |
|                               │                                 │                                |
|                               v                                 v                                |
|                        enabled = True                    enabled = False                         |
|                               │                                 │                                |
|                               v                                 v                                |
|                      Full Context Injection             Graceful Fallback                        |
|                                                 (Core Agent Operations 100% Available)           |
+--------------------------------------------------------------------------------------------------+
```

### Consequences & Trade-offs
- **Positive**: 100% uptime for core transactional workflows (order queries, refunds, RAG knowledge search, calculator) regardless of downstream memory availability.
- **Trade-off**: Multi-turn personalization is temporarily bypassed until cloud memory resources are provisioned.

---

## ADR-003: Enterprise Packaging & Multi-Directory Python Build Topology

### Context & Problem Statement
During containerized packaging via `agentcore configure` and `agentcore deploy`, standard setuptools package discovery can fail when non-package directories (`lambda/`, `screenshots/`, configuration artifacts) reside adjacent to the application entrypoint (`main.py`). Additionally, mismatches between the target build container runtime (e.g. Python 3.12) and the local development environment specification (`pyproject.toml`) can cause build-time failures.

### Decision
1. **Explicit Build Manifest Isolation**: Standardize `pyproject.toml` dependencies with explicit Python runtime compatibility constraints (`>=3.12, <3.15`).
2. **Clean Project Structure**: Separate infrastructure microservices into dedicated subdirectories (`lambda/`) with independent dependency profiles, preventing circular dependency resolution during AgentCore container builds.
3. **Deterministic Lockfiles**: Maintain cryptographically pinned `uv.lock` files to guarantee binary package reproducibility between local environments and cloud deployment builders.

---

## ADR-004: Granular Least-Privilege IAM Scoping & CI Policy Enforcement

### Context & Problem Statement
The default execution role generated by `agentcore configure` provides baseline Bedrock invocation permissions but omits granular resource-level authorizations required for specialized tools:
- `search_knowledge_base` requires explicit `bedrock:Retrieve` permissions on the Knowledge Base ARN.
- `AgentCoreBrowser` requires `bedrock-agentcore:StartBrowserSession` and streaming permissions.

Without explicit policies, tool invocations fail silently or return ambiguous "authorization issue" error strings to end users.

### Decision
1. **Explicit Least-Privilege Policies**: Attach dedicated inline policies to the runtime role (`AmazonBedrockAgentCoreSDKRuntime-*`):
   - `KnowledgeBaseRetrieveAccess`: Scoped strictly to the target Knowledge Base ARN.
   - `BrowserToolAccess`: Authorizes browser session instantiation and automation streams.
2. **Automated CI Validation**: Pre-deployment validation scripts in the CI/CD pipeline verify that execution role policies contain required resource ARNs before allowing `agentcore deploy` to proceed.

```
+--------------------------------------------------------------------------------------------------+
|                                    IAM Governance Pipeline                                       |
|                                                                                                  |
|   Runtime Execution Role ──────> Automated CI Role Policy Validator                              |
|                                                │                                                 |
|                                                ├── Validates bedrock:Retrieve (Scoped ARN)       |
|                                                ├── Validates bedrock-agentcore Browser Actions   |
|                                                └── Validates CloudWatch Logging Write Actions    |
|                                                │                                                 |
|                                                v                                                 |
|                                     Deployment Authorization                                     |
+--------------------------------------------------------------------------------------------------+
```
