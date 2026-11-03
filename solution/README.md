# Production Reference Implementation — Customer Support AI Agent

This directory contains the production-grade reference implementation of the **Autonomous Customer Support AI Agent Platform**, orchestrated via the **Strands Agent Framework** and deployed to **Amazon Bedrock AgentCore**.

---

## 1. Architectural Overview & Component Inventory

The reference implementation is designed for enterprise deployment with strict isolation between generative reasoning, deterministic computation, and external transactional systems.

### Directory Inventory

| File / Directory | Enterprise Purpose & Technical Responsibility |
|---|---|
| `main.py` | Production agent runtime, lifecycle hooks, tool dispatchers, model bindings, and AgentCore entrypoint |
| `product_catalog.txt` | Ground-truth enterprise knowledge corpus (product specs, return rules, warranty policies, loyalty tiers) |
| `pyproject.toml` | Deterministic dependency manifest managed via `uv` |
| `uv.lock` | Cryptographically pinned dependency lockfile ensuring reproducible builds across CI/CD |
| `REFLECTION.md` | Architectural Decision Records (ADRs) covering schema validation, quota resilience, and IAM security |
| `lambda/order_tracker.py` | Order lifecycle microservice integrated via AgentCore Gateway REST proxy |
| `lambda/refund_processor.py` | Transactional refund management microservice invoked directly via Gateway context |
| `lambda/lambda_schema` | Declarative Model Context Protocol (MCP) tool schema for Gateway target registration |
| `screenshots/` | Historical audit directory (retained for backward compatibility; replaced by structured test matrices) |

---

## 2. Technical Implementation Deep Dive

### 2.1 Core Orchestration Engine (`main.py`)

The agent is built on `BedrockAgentCoreApp` with the `amazon.nova-2-lite-v1:0` foundation model. It coordinates tools and lifecycle hooks through the following execution pipeline:

```
[Inbound Request: invoke(payload, context)]
                   │
                   ▼
       [Input Validation & ID Extraction]
       - prompt: str (required)
       - customer_id: str (default: "anonymous")
       - session_id: str (UUID generated if absent)
                   │
                   ▼
       [Lifecycle Hook Attachment: MemoryHook]
       - Injects historical facts & preferences via MessageAddedEvent
                   │
                   ▼
       [Tool Aggregation & Registration]
       - search_knowledge_base (Local RAG Tool)
       - calculate_loyalty_discount (Sandboxed Code Tool)
       - AgentCoreBrowser.browser (Headless Web Automation)
       - Gateway MCP Tools (Loaded dynamically via streamable_http_client)
                   │
                   ▼
       [Strands Agent Invocation]
       - Asynchronous reasoning loop over Amazon Nova 2 Lite
                   │
                   ▼
       [Post-Invocation Persistence: AfterInvocationEvent]
       - Asynchronous memory event creation for future multi-turn recall
                   │
                   ▼
       [Response Serialization & Return]
```

### 2.2 Storage & Vector Architecture: Amazon S3 Vectors

This deployment leverages **Amazon S3 Vectors** as the underlying vector storage layer for the Bedrock Knowledge Base instead of OpenSearch Serverless:

```
+--------------------------------------------------------------------------------------------------+
|                                    Vector Storage Architecture                                   |
|                                                                                                  |
|   Document: product_catalog.txt ────> S3 Source Bucket                                           |
|                                             │                                                    |
|                                             v                                                    |
|                                Bedrock Knowledge Base Ingestion                                  |
|                                             │                                                    |
|                                             v                                                    |
|                               Amazon Titan Embeddings v2                                         |
|                                             │                                                    |
|                                             v                                                    |
|                                  Amazon S3 Vector Bucket                                         |
|                 - Native S3 object-level durability and access controls                          |
|                 - Zero cluster provisioning, zero cold starts, zero index management            |
|                 - Sub-second retrieval latency directly integrated with Bedrock Runtime         |
+--------------------------------------------------------------------------------------------------+
```

### 2.3 Resilient Memory Hook Engine (`MemoryHook`)

The memory engine implements the Strands `HookProvider` protocol, managing cross-session persistence across two distinct strategy namespaces:
1. `SEMANTIC` (`cs_agent/{actorId}/facts`): Extracts customer-specific attributes and past interactions.
2. `USER_PREFERENCE` (`cs_agent/{actorId}/preferences`): Retains explicit communication or channel preferences.

#### Graceful Degradation Pattern
If `MEMORY_ID` is set to a placeholder, or if an AWS account-level service quota blocks memory creation (such as quota code `L-81002DCC`), `get_namespaces()` returns an empty dictionary. `MemoryHook.enabled` evaluates to `False`, converting both `retrieve_customer_context` and `save_support_interaction` into safe no-ops without degrading conversational or transactional tool availability.

### 2.4 Deterministic Financial Computation Sandbox

Loyalty discount calculations require exact arithmetic. Generative models attempting mental arithmetic on tiered discounts and point balances can hallucinate values. The platform executes calculations within the **AgentCore Code Interpreter**:

```
Agent Tool Dispatch ───> Python Code Block ───> AgentCore Code Interpreter Sandbox
                                                         │
                                                         ▼
                                                Stdout: JSON String
                                                         │
                                                         ▼
       Valid JSON ───> Pydantic Model Validation (LoyaltyDiscountResult)
                                 │
                                 ├── Valid ───> Return Sanitized Result String
                                 │
                                 └── Invalid / Exception ───> Tier-Only Deterministic Fallback
```

#### Strict Pydantic Data Contract
```python
class LoyaltyDiscountResult(BaseModel):
    points_redeemed: int = Field(ge=0)
    points_discount: float = Field(ge=0)
    tier_discount_pct: int = Field(ge=0, le=100)
    tier_discount: float = Field(ge=0)
    total_savings: float = Field(ge=0)
    final_total: float = Field(ge=0)
    points_earned: int = Field(ge=0)
    remaining_points: int = Field(ge=0)
    display_text: str
    fallback: bool = False
```

---

## 3. Production IAM Security & Least-Privilege Policies

When running `agentcore configure`, the auto-generated runtime role lacks tool-specific permissions required for Knowledge Base retrieval and browser automation. The following two inline IAM policies must be attached to the agent execution role (`AmazonBedrockAgentCoreSDKRuntime-*`):

### 3.1 Knowledge Base Retrieval Policy (`KnowledgeBaseRetrieveAccess`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockKnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": [
        "bedrock:Retrieve"
      ],
      "Resource": "arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:knowledge-base/<KB_ID>"
    }
  ]
}
```

### 3.2 Headless Browser Automation Policy (`BrowserToolAccess`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentCoreBrowserAutomationStreaming",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:StartBrowserSession",
        "bedrock-agentcore:ConnectBrowserAutomationStream",
        "bedrock-agentcore:StopBrowserSession"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 4. Configuration & Deployment Procedure

### 4.1 Configuration Parameters (`main.py`)
Update the top-level configuration constants before deployment:

```python
GATEWAY_URL = "https://<GATEWAY_ALIAS>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "<YOUR_BEDROCK_KB_ID>"
REGION      = "us-east-1"
MEMORY_ID   = "<YOUR_MEMORY_ID>"   # Retain "<memory-id>" placeholder if Memory quota is constrained
```

### 4.2 Packaging and Deployment Commands

```powershell
# 1. Synchronize Python environment and lockfile
uv sync

# 2. Configure AgentCore runtime packaging
agentcore configure --entrypoint main.py --name customer_support_agent

# 3. Deploy containerized artifact to AgentCore
agentcore deploy
```

---

## 5. Structured Operational Verification Suite

The table below outlines the end-to-end test scenarios, command syntax, and production output specifications:

| Test Scenario | CLI Command | Input Payload | Verified Output Contract |
|---|---|---|---|
| **1. Order Tracking Verification** | `agentcore invoke '<payload>' -s test1-order-session-001` | `{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123"}` | Order `ORD-001` status: `SHIPPED`. Carrier: `UPS`. Tracking: `TRK987654321`. Estimated delivery: 2 days from query. |
| **2. Transactional Refund Processing** | `agentcore invoke '<payload>' -s test2-refund-session-002` | `{"prompt": "I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.", "customer_id": "CUST-123"}` | Resolves order total `$139.99`. Generates refund `REF-XXXXXXXX`. Status: `APPROVED`. Refund credited within 3–5 business days. |
| **3. Knowledge Base Semantic RAG** | `agentcore invoke '<payload>' -s test3-kb-session-003` | `{"prompt": "What are the benefits of the Platinum loyalty tier?", "customer_id": "CUST-123"}` | Extracts 3 verified policy terms: Free same-day shipping on eligible orders, 15% discount on all purchases, dedicated 24/7 priority support line. |
| **4. Contextual Memory Recall** | `agentcore invoke '<payload>' -s test4-memory-session-004` | *Session A*: `{"prompt": "Hi, I am Jane. I prefer concise responses.", "customer_id": "CUST-123"}`<br>*Session B*: `{"prompt": "Do you remember my name and preference?", "customer_id": "CUST-123"}` | Correctly recalls customer name ("Jane") and communication style preference ("concise responses") without re-prompting. |
| **5. Sandboxed Loyalty Math** | `agentcore invoke '<payload>' -s test5-loyalty-session-005` | `{"prompt": "I am a Gold member with 4250 points. Calculate my discount on a $150 standard order.", "customer_id": "CUST-123"}` | Points redeemed: 4,000 ($40.00). Tier discount: 10% on remaining $110 ($11.00). Total savings: $51.00. Final total: $99.00. Remaining points: 349. |
| **6. Live Browser Tool Automation** | `agentcore invoke '<payload>' -s test6-browser-session-006` | `{"prompt": "Go to https://www.amazon.com and tell me the page title.", "customer_id": "CUST-123"}` | Connects to CDP stream, navigates to target URL, extracts `<title>` attribute, and returns verified page title. |

---

## 6. Observability & Alarm Telemetry

Enterprise monitoring is configured via Amazon CloudWatch:

```
+--------------------------------------------------------------------------------------------------+
|                                  CloudWatch Telemetry Topology                                   |
|                                                                                                  |
|   Log Group: /aws/bedrock-agentcore/customer_support_agent                                       |
|      ├── Metric Filter: CustomerSupportAgentErrors (Pattern: ERROR)                              |
|      │      └── Custom Metric: CustomerSupportAgent/CustomerSupportAgentErrorCount               |
|      │             └── CloudWatch Alarm: CustomerSupportAgent-HighErrorRate                      |
|      │                    - Evaluation: 1 period of 300 seconds (5 minutes)                      |
|      │                    - Threshold: > 5 errors                                                |
|      │                    - Severity: SEV-2 Incident                                             |
|      └── Structured Audit: Inbound payloads, tool execution latency, and completion status       |
+--------------------------------------------------------------------------------------------------+
```
