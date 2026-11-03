# Enterprise Autonomous Customer Support Agent Platform

An enterprise-grade, multi-tool conversational AI support platform engineered on **Amazon Bedrock AgentCore** and the **Strands Agent Framework**. The platform automates Tier-1 customer service workflows, including real-time order tracking, deterministic refund processing, semantic vector retrieval for enterprise product catalogs and policy documentation, multi-session contextual memory, sandboxed financial calculation, and live web automation.

---

## 1. Executive Summary & Architecture Overview

The Enterprise Autonomous Customer Support Agent Platform delivers high-concurrency, low-latency, and deterministic customer service automation. Built upon modern cloud-native patterns, the architecture isolates non-deterministic generative capabilities within strict validation boundaries while delegating transactional operations to authenticated microservices.

### High-Level System Architecture

```
+--------------------------------------------------------------------------------------------------+
|                                    Client Ingestion Layer                                        |
|                     (Web Portal / Mobile Application / B2B API Gateway)                          |
+--------------------------------------------------------------------------------------------------+
                                                 |
                                                 v
+--------------------------------------------------------------------------------------------------+
|                             Amazon Bedrock AgentCore Runtime                                     |
|                                                                                                  |
|   +------------------------------------------------------------------------------------------+   |
|   |                              Strands Agent Orchestrator                                  |   |
|   |                      Foundation Model: Amazon Nova 2 Lite (Bedrock)                      |   |
|   +------------------------------------------------------------------------------------------+   |
|          |                         |                        |                       |            |
|          v                         v                        v                       v            |
|   +--------------+      +--------------------+      +---------------+      +-----------------+   |
|   | Memory Hook  |      |   Knowledge Base   |      | Code Sandbox  |      | Browser Session |   |
|   |  (Lifecycle) |      |    (RAG Engine)    |      | (Interpreter) |      |   Automation    |   |
|   +--------------+      +--------------------+      +---------------+      +-----------------+   |
|          |                         |                        |                       |            |
+----------|-------------------------|------------------------|-----------------------|------------+
           |                         |                        |                       |
           v                         v                        v                       v
+--------------------+    +--------------------+    +--------------------+  +--------------------+
| AgentCore Memory   |    | Bedrock Knowledge  |    | AgentCore Code     |  | AgentCore Browser  |
|  - Facts Namespace |    |  Base (S3 Vectors  |    |  Interpreter       |  |  Puppeteer/CDP     |
|  - Prefs Namespace |    |  + Titan v2 Embed) |    |  (Pydantic Schema) |  |  Live Web Stream   |
+--------------------+    +--------------------+    +--------------------+  +--------------------+
                                     |
                                     v
+--------------------------------------------------------------------------------------------------+
|                        Model Context Protocol (MCP) Gateway Integration                          |
|                             (AgentCore Gateway over Streamable HTTP)                             |
+--------------------------------------------------------------------------------------------------+
                   |                                                    |
                   v                                                    v
+----------------------------------------+           +----------------------------------------+
|      Order Tracking Microservice       |           |      Refund Processing Microservice    |
|   (REST Proxy via AWS API Gateway)     |           |       (Direct Lambda Invocation)       |
|    - GET /orders/{order_id}            |           |        - initiate_refund               |
|    - GET /customers/{customer_id}      |           |        - check_refund_status           |
|    - GET /customers/{id}/orders        |           |        - get_return_label              |
+----------------------------------------+           +----------------------------------------+
                   |                                                    |
                   +--------------------------+-------------------------+
                                              v
+--------------------------------------------------------------------------------------------------+
|                              Enterprise Observability & Security                                 |
|           - AWS CloudWatch Structured Logs (Metric Filters & High-Error Alarms)                  |
|           - IAM Scoped Least-Privilege Execution Roles & BYPASS_TOOL_CONSENT Enforcement         |
+--------------------------------------------------------------------------------------------------+
```

---

## 2. Core Functional Capabilities

| Capability | Module / Tool | Integration Path | Primary SLA & Determinism Target |
|---|---|---|---|
| **Order Lifecycle Ingestion** | `order-tracker` | AgentCore Gateway (API Gateway Proxy) | Sub-second order lookup, carrier tracking verification |
| **Transactional Refunds** | `refund_processor` | AgentCore Gateway (Direct Lambda Context) | Strict order total validation prior to execution |
| **Catalog & Policy RAG** | `search_knowledge_base` | Amazon Bedrock Knowledge Base (S3 Vectors) | High-relevance semantic search with citation preservation |
| **Cross-Session Memory** | `MemoryHook` | Bedrock AgentCore Memory Client | Dual-namespace semantic fact & preference extraction |
| **Deterministic Math** | `calculate_loyalty_discount` | AgentCore Code Interpreter Sandbox | 100% precision arithmetic validated via Pydantic model |
| **Live External Inspection** | `AgentCoreBrowser` | AgentCore Browser Streaming | Headless DOM navigation for live web data extraction |
| **Failure Defense** | Fault Tolerance Subsystem | In-memory Graceful Fallback | Circuit breaking on quota blocks or API timeouts |

---

## 3. System Data Flow & Interaction Lifecycles

### 3.1 Retrieval-Augmented Generation (RAG) Workflow

```
Customer Query ───────> Agent Engine ───────> Bedrock Retrieve API
                             ▲                           │
                             │                           v
                    Synthesized Context <────── Chunks Delimited by "---"
                             │                           │
                             ▼                           v
                      Model Response <────────── Amazon Titan Embeddings v2
                                                         │
                                                         v
                                                Amazon S3 Vector Bucket
```

### 3.2 Transactional Order & Refund Flowchart

```
Customer Inquiry ──> Strands Agent Orchestrator
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
    [Order Status Inquiry]     [Refund Request Ingestion]
             │                           │
    Calls Gateway REST Proxy             ▼
  (GET /orders/{order_id})     Look up Order Total via Gateway
             │                           │
    Receives Tracking Details    Order Status Validated (DELIVERED)
             │                           │
             │                 Verify Return Window via KB (< 30 days)
             │                           │
             │                 Execute Direct Lambda Target:
             │                 initiate_refund(order_id, reason, amount)
             │                           │
             ▼                           ▼
    Returns Carrier Status     Generates REF-XXXXXX & Return Label
```

### 3.3 Contextual Memory Synchronization Lifecycle

```
[Inbound Turn: MessageAddedEvent]
 ├── Extract Customer Query
 ├── Resolve Namespaces (Semantic Facts + User Preferences)
 ├── Query MemoryClient (Top-K = 5 per Namespace)
 └── Inject Formatted "Customer Context:" Header into User Message Payload
         │
         ▼
[Agent Inference Execution]
         │
         ▼
[Outbound Turn: AfterInvocationEvent]
 ├── Extract Clean User Prompt (Stripping Injected Context)
 ├── Extract Final Assistant Content
 └── Asynchronously Call MemoryClient.create_event(actor_id, session_id, messages)
```

---

## 4. Repository Structure & Artifact Layout

```
D:\AI-Support-agent\
├── .gitignore                      # Security exclusions (credentials, .venv, local caches)
├── CODEOWNERS                      # Repository governance and ownership manifest
├── LICENSE.txt                     # Enterprise license definition
├── readme.md                       # Master enterprise system architecture documentation
├── solution/                       # Verified production reference implementation
│   ├── main.py                     # Production agent runtime, hooks, and tool bindings
│   ├── product_catalog.txt         # RAG source document (policies, catalog, warranties)
│   ├── pyproject.toml              # Production dependency definitions (uv managed)
│   ├── uv.lock                     # Deterministic dependency lockfile
│   ├── README.md                   # Production deployment and configuration guide
│   ├── REFLECTION.md               # Architectural Decision Records (ADR) and Post-Mortem
│   ├── lambda/                     # Microservice handlers and tool interface definitions
│   │   ├── lambda_schema           # MCP JSON schema for Gateway tool registration
│   │   ├── order_tracker.py        # Order tracking microservice (REST Proxy integration)
│   │   └── refund_processor.py     # Refund management microservice (Direct invocation)
│   └── screenshots/                # Deployment audit assets
│       └── .gitkeep                # Directory preservation marker
└── starter/                        # Enterprise developer scaffold
    ├── main.py                     # Scaffolding template with standardized interface hooks
    ├── product_catalog.txt         # Enterprise knowledge corpus source
    ├── pyproject.toml              # Developer template dependency specifications
    ├── README.md                   # Developer implementation roadmap and setup guide
    └── lambda/                     # Microservice implementation source
        ├── lambda_schema           # Tool interface definitions
        ├── order_tracker.py        # Order tracking service baseline
        └── refund_processor.py     # Refund processor service baseline
```

---

## 5. Microservices & External Tool Contracts

### 5.1 Order Tracker Microservice (`order-tracker`)
- **Integration Mode**: AgentCore Gateway via AWS API Gateway REST proxy.
- **Runtime Environment**: Python 3.12 (AWS Lambda).
- **Exposed Endpoints**:

| Route | HTTP Method | Path Parameters | Description |
|---|---|---|---|
| `/orders/{order_id}` | `GET` | `order_id` (e.g. `ORD-001`) | Fetches order record, carrier status, line items, and delivery estimate |
| `/customers/{customer_id}/orders` | `GET` | `customer_id` (e.g. `CUST-123`) | Returns all historical orders associated with a customer account |
| `/customers/{customer_id}` | `GET` | `customer_id` (e.g. `CUST-123`) | Returns customer profile data, tier status, and contact metadata |

### 5.2 Refund Processor Microservice (`refund-processor`)
- **Integration Mode**: AgentCore Gateway via Direct Lambda Target.
- **Routing Protocol**: Target tool name passed via Lambda `client_context` (`TargetName___toolName`).
- **Tool Definitions**:

| Tool Name | Parameters | Required Fields | Return Payload Contract |
|---|---|---|---|
| `initiate_refund` | `order_id`: str, `reason`: str, `amount`: float | `order_id`, `reason` | `refund_id`, `status: "APPROVED"`, `amount`, `estimated_days` |
| `check_refund_status` | `refund_id`: str | `refund_id` | `refund_id`, `status: "PROCESSING"`, `created_date` |
| `get_return_label` | `order_id`: str | `order_id` | `tracking_number`, `carrier`, `label_url`, `expiry` |

### 5.3 Knowledge Base RAG Tool (`search_knowledge_base`)
- **Function Signature**: `search_knowledge_base(query: str) -> str`
- **Underlying Engine**: Bedrock Runtime `retrieve` API.
- **Storage Subsystem**: Amazon S3 Vector Bucket.
- **Embedding Model**: Amazon Titan Embeddings v2 (`amazon.titan-embed-text-v2:0`).
- **Chunk Delimiter**: `\n---\n`.

### 5.4 Loyalty Discount Calculator (`calculate_loyalty_discount`)
- **Function Signature**: `calculate_loyalty_discount(loyalty_points: int, tier: str, order_total: float, product_category: str = "standard") -> str`
- **Execution Runtime**: AgentCore Code Interpreter (`executeCode` in isolated Python sandbox).
- **Output Validation Engine**: Pydantic `LoyaltyDiscountResult` strict parser.
- **Business Logic Rules**:
  - Point conversion: 100 points = $1.00 USD.
  - Redemption granularity: Blocks of 500 points ($5.00 increments).
  - Maximum allowable points discount: 50% of gross order total.
  - Tier discount applied to subtotal post-point redemption:
    - Silver: 0%
    - Gold: 10%
    - Platinum: 15%
  - Point accrual on net payment: Standard (1x), Device (2x), Fresh (5x).

### 5.5 Browser Automation Tool (`AgentCoreBrowser`)
- **Function Signature**: `agent_core_browser.browser`
- **Execution Engine**: Headless browser automation streaming via AgentCore browser service.
- **Capabilities**: Live web page retrieval, content extraction, dynamic JavaScript rendering.

---

## 6. Security, Identity & Governance

### 6.1 Principle of Least Privilege (IAM)
The runtime operates under a dedicated IAM role (`AmazonBedrockAgentCoreSDKRuntime-*`) configured with precise resource-scoped permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-lite-v1:0"
    },
    {
      "Sid": "KnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": "bedrock:Retrieve",
      "Resource": "arn:aws:bedrock:us-east-1:<account-id>:knowledge-base/<kb-id>"
    },
    {
      "Sid": "BrowserSessionControl",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:StartBrowserSession",
        "bedrock-agentcore:ConnectBrowserAutomationStream",
        "bedrock-agentcore:StopBrowserSession"
      ],
      "Resource": "*"
    },
    {
      "Sid": "GatewayInvokeAccess",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:InvokeGateway",
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:<account-id>:gateway/*"
    }
  ]
}
```

### 6.2 Autonomous Runtime Hardening
- **Headless Tool Authorization**: `os.environ["BYPASS_TOOL_CONSENT"] = "true"` prevents interactive blocking prompts during autonomous cloud execution.
- **Deterministic Prompt Safeguards**: System prompts enforce strict anti-hallucination guardrails:
  - Absolute ban on fabricating order data, refund statuses, prices, or policies.
  - Mandatory pre-flight lookup of order totals before refund initiation to eliminate `$0.00` false approvals.
  - Code Interpreter display strings treated as immutable truth.

---

## 7. Infrastructure Provisioning & Deployment

### 7.1 Environment Prerequisites

| Dependency | Minimum Version | Installation / Management |
|---|---|---|
| Python | 3.12 or 3.14+ | Core execution runtime |
| uv | Latest | High-performance Python package installer & resolver |
| AWS CLI | v2.15+ | AWS infrastructure provisioning |
| AgentCore CLI (`agentcore`) | Latest | Runtime deployment & session management |
| Model Access | Active | Amazon Nova 2 Lite (`amazon.nova-2-lite-v1:0`) in `us-east-1` |

### 7.2 Microservice & Resource Setup

1. **Deploy Microservices**:
   - Package `solution/lambda/order_tracker.py` and deploy as AWS Lambda function `order-tracker`.
   - Package `solution/lambda/refund_processor.py` and deploy as AWS Lambda function `refund-processor`.

2. **Configure AgentCore Gateway**:
   - Create Gateway `CustomerSupportGateway`.
   - Register Target `order_tracker` pointing to `order-tracker` via API Gateway REST proxy.
   - Register Target `refund_processor` pointing directly to `refund-processor` with schema from `solution/lambda/lambda_schema`.
   - Export Gateway URL (`https://<alias>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp`).

3. **Configure Bedrock Knowledge Base**:
   - Upload `solution/product_catalog.txt` to an S3 source bucket.
   - Create Knowledge Base `CustomerSupportKB` using Amazon S3 Vectors and Amazon Titan Embeddings v2.
   - Sync data source and record the Knowledge Base ID.

4. **Initialize Local Deployment**:
   ```powershell
   cd D:\AI-Support-agent\solution
   uv sync
   ```

5. **Deploy Agent Runtime**:
   ```powershell
   agentcore configure --entrypoint main.py --name customer_support_agent
   agentcore deploy
   ```

---

## 8. Operational Verification & Validation Matrix

The platform undergoes continuous validation across six core operational scenarios:

| Test ID | Scenario | Invocation Command & Input Payload | Verification Assertions |
|---|---|---|---|
| **TEST-01** | **Order Tracking Ingestion** | `agentcore invoke '{\"prompt\": \"Can you track order ORD-001?\", \"customer_id\": \"CUST-123\"}' -s test-session-001` | Returns order status `SHIPPED`, carrier `UPS`, tracking number `TRK987654321`, delivery date. |
| **TEST-02** | **Transactional Refund Processing** | `agentcore invoke '{\"prompt\": \"I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.\", \"customer_id\": \"CUST-123\"}' -s test-session-002` | Resolves order total `$139.99`, executes refund tool, returns refund ID `REF-XXXXXXXX`, status `APPROVED`. |
| **TEST-03** | **Knowledge Base Semantic RAG** | `agentcore invoke '{\"prompt\": \"What are the benefits of the Platinum loyalty tier?\", \"customer_id\": \"CUST-123\"}' -s test-session-003` | Retrieves verified benefits: free same-day shipping, 15% tier discount, dedicated priority support. |
| **TEST-04** | **Cross-Session Memory Persistence** | *Turn A*: `{\"prompt\": \"I prefer concise responses.\", \"customer_id\": \"CUST-123\"}`<br>*Turn B*: `{\"prompt\": \"What are my preferences?\", \"customer_id\": \"CUST-123\"}` | Verifies recall of communication preference ("concise responses") across distinct session IDs. |
| **TEST-05** | **Sandboxed Financial Calculation** | `agentcore invoke '{\"prompt\": \"I am a Gold member with 4250 points. Calculate my discount on a $150 order.\", \"customer_id\": \"CUST-123\"}' -s test-session-005` | Validates sandbox math: 4,000 points redeemed ($40.00 discount), 10% Gold tier discount ($11.00), total savings $51.00, final total $99.00. |
| **TEST-06** | **Live Headless Browser Automation** | `agentcore invoke '{\"prompt\": \"Go to https://www.amazon.com and tell me the page title.\", \"customer_id\": \"CUST-123\"}' -s test-session-006` | Launches AgentCore browser session, fetches DOM, extracts and reports accurate live page title. |

---

## 9. Observability, Telemetry & Incident Response

### 9.1 CloudWatch Structured Telemetry
All agent execution traces, tool dispatches, and runtime errors emit structured JSON events to AWS CloudWatch Log Groups under `/aws/bedrock-agentcore/customer_support_agent`.

```
+--------------------------------------------------------------------------------------------------+
|                                    Telemetry Pipeline                                            |
|                                                                                                  |
|   AgentCore Runtime Logs ──────> CloudWatch Log Group: /aws/bedrock-agentcore/...                |
|                                         │                                                        |
|                                         v                                                        |
|                               Metric Filter: "ERROR"                                             |
|                                         │                                                        |
|                                         v                                                        |
|                          Custom Metric: CustomerSupportAgentErrorCount                           |
|                                         │                                                        |
|                                         v                                                        |
|                         CloudWatch Alarm: HighErrorRateAlert                                     |
|                       (Threshold: > 5 errors in 5 minutes)                                       |
|                                         │                                                        |
|                                         v                                                        |
|                               SNS Notification / PagerDuty                                       |
+--------------------------------------------------------------------------------------------------+
```

### 9.2 CloudWatch Metric Filter Specification
- **Filter Name**: `CustomerSupportAgentErrors`
- **Filter Pattern**: `ERROR`
- **Metric Namespace**: `CustomerSupportAgent`
- **Metric Name**: `CustomerSupportAgentErrorCount`
- **Metric Value**: `1`

### 9.3 CloudWatch Incident Alarm
- **Alarm Name**: `CustomerSupportAgent-HighErrorRate`
- **Comparison Operator**: `GreaterThanThreshold`
- **Evaluation Periods**: `1`
- **Period**: `300 seconds (5 minutes)`
- **Threshold**: `5`
- **Datapoints to Alarm**: `1 of 1`
- **Treatment of Missing Data**: `notBreaching`

---

## 10. Fault Tolerance & Graceful Degradation Architecture

To guarantee high availability even during partial cloud provider degradation, the platform enforces strict failure isolation boundaries:

```
                                 [External System Call]
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
          [AgentCore Memory API]                        [Code Interpreter API]
                    │                                             │
             Is API Healthy?                               Is Sandbox Ready?
             ├── YES ──> Inject Context                    ├── YES ──> Pydantic Validation
             └── NO                                        └── NO
                  │                                             │
                  ▼                                             ▼
       [Graceful Fallback Path]                      [Graceful Fallback Path]
     - Log Warning Telemetry                       - Log Sandbox Warning
     - Bypass Context Enrichment                   - Execute Local Deterministic Math
     - Complete Request Execution                  - Flag `fallback: true` in Result
```

1. **Memory Subsystem Isolation**:
   - If `MEMORY_ID` is not configured or fails due to account-level quotas (e.g. quota code `L-81002DCC`), `get_namespaces` returns an empty mapping.
   - `MemoryHook` automatically disables itself (`self.enabled = False`), converting memory callbacks into instant no-ops.
   - Core conversational flows, tool dispatch, and RAG operations remain 100% available.

2. **Financial Math Sandbox Fallback**:
   - If the remote Code Interpreter service becomes unavailable or returns malformed stdout, the system catches the exception and immediately invokes a deterministic fallback calculator.
   - Output still adheres strictly to the `LoyaltyDiscountResult` schema with `fallback: True`, ensuring zero downtime for customer checkouts.
