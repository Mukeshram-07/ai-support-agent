# Enterprise Agent Framework — Developer Starter Scaffold

This directory provides the baseline scaffolding and extensible architecture for engineering production-grade customer support AI agents using **Amazon Bedrock AgentCore** and the **Strands Agent Framework**.

---

## 1. Scaffold Overview & Component Topology

The developer scaffold establishes standard interfaces for external microservice communication via Model Context Protocol (MCP), Retrieval-Augmented Generation (RAG), stateful conversation memory, sandboxed code execution, and browser automation.

```
+--------------------------------------------------------------------------------------------------+
|                                    Developer Scaffold Architecture                               |
+--------------------------------------------------------------------------------------------------+
                                                 |
                                                 v
+--------------------------------------------------------------------------------------------------+
|                                    starter/main.py Core Loop                                     |
|                                                                                                  |
|   1. Configuration & Client Setup  ───> BedrockAgentCoreApp, BedrockModel, MemoryClient          |
|   2. RAG Retrieval Interface       ───> search_knowledge_base() via Bedrock Agent Runtime        |
|   3. Stateful Memory Hook          ───> MemoryHook (MessageAddedEvent / AfterInvocationEvent)    |
|   4. Sandboxed Arithmetic Engine   ───> calculate_loyalty_discount() via code_session()          |
|   5. Gateway MCP Client            ───> MCPClient over streamable_http_client                    |
|   6. Main Invocation Handler       ───> @app.entrypoint async def invoke(payload, context)       |
+--------------------------------------------------------------------------------------------------+
                                                 |
                                                 v
+--------------------------------------------------------------------------------------------------+
|                                External Microservice Integrations                                |
|   - starter/lambda/order_tracker.py       ───> REST Proxy integration (/orders, /customers)      |
|   - starter/lambda/refund_processor.py    ───> Direct Lambda invocation (tool context)           |
|   - starter/lambda/lambda_schema          ───> Declarative MCP tool definition schemas           |
+--------------------------------------------------------------------------------------------------+
```

---

## 2. Directory Layout & File Manifest

| Path | Component Type | Technical Purpose |
|---|---|---|
| `main.py` | Core Application Scaffolding | Contains standardized interface signatures, lifecycle hooks, and `# TODO` implementation markers |
| `product_catalog.txt` | Ground-Truth Knowledge Base | Enterprise document corpus containing product specs, return windows, warranty details, and loyalty tier policies |
| `pyproject.toml` | Package Specification | Project dependency manifest configured for `uv` package management |
| `lambda/lambda_schema` | MCP Tool Schemas | JSON schema definitions for Gateway tool registration (`initiate_refund`, `check_refund_status`, `get_return_label`) |
| `lambda/order_tracker.py` | Microservice Handler | Lambda handler supporting order queries via API Gateway REST proxy integration |
| `lambda/refund_processor.py`| Microservice Handler | Lambda handler supporting transactional refund operations via direct Gateway invocation |

---

## 3. Implementation Roadmap

The scaffold in `main.py` is structured into modular sections. Implement each section in sequence:

### Section 1: Configuration & Client Initialization
- Configure cloud endpoint identifiers (`GATEWAY_URL`, `KB_ID`, `REGION`, `MEMORY_ID`).
- Initialize `BedrockAgentCoreApp`.
- Instantiate `BedrockModel` using Amazon Nova Lite (`amazon.nova-2-lite-v1:0`).
- Configure `MemoryClient` and `boto3` Bedrock Agent Runtime client.

### Section 2: Knowledge Base RAG Tool
- Implement `search_knowledge_base(query: str) -> str`.
- Query Bedrock Knowledge Base via `boto3` Bedrock Agent Runtime client.
- Parse retrieval response and join text chunks using the delimiter `"\n---\n"`.

### Section 3: Stateful Memory Provider (`MemoryHook`)
- Implement `MemoryHook` extending the Strands `HookProvider`.
- Register callbacks for:
  - `MessageAddedEvent`: Query memory namespaces (`SEMANTIC`, `USER_PREFERENCE`) and inject relevant customer context into the active user turn.
  - `AfterInvocationEvent`: Asynchronously persist the completed user-assistant conversation turn to AgentCore Memory.

### Section 4: Sandboxed Loyalty Discount Tool
- Implement `calculate_loyalty_discount(loyalty_points, tier, order_total, product_category)`.
- Construct deterministic Python arithmetic logic and execute within the `code_session()` sandbox.
- Validate JSON output against structured schemas and provide graceful fallback logic when the sandbox is unreachable.

### Section 5: Gateway MCP Tool Integration
- Initialize `MCPClient` pointing to the `GATEWAY_URL` using `streamable_http_client`.
- Connect to Gateway and dynamically discover exposed microservice tools (`order_tracker` and `refund_processor`).

### Section 6: Main Invocation Entrypoint
- Implement the `@app.entrypoint async def invoke(payload, context)`.
- Extract inbound parameters: `prompt`, `customer_id`, and `session_id`.
- Assemble `Agent` with models, tools, and hooks, returning the synthesized response text.

---

## 4. Microservice Tool Interface Specifications

### 4.1 Order Tracking Tool Contract (`order-tracker`)
- **Transport**: AgentCore Gateway via API Gateway REST Proxy
- **Interface Routes**:
  - `GET /orders/{order_id}`: Retrieves order status, items, tracking number, carrier, and estimated delivery date.
  - `GET /customers/{customer_id}/orders`: Lists order history for a customer ID.
  - `GET /customers/{customer_id}`: Retrieves customer tier, address, and contact metadata.

### 4.2 Refund Processing Tool Contract (`refund-processor`)
- **Transport**: AgentCore Gateway via Direct Lambda Invocation
- **Registered Tools**:

| Tool Name | Input Parameters | Return Contract |
|---|---|---|
| `initiate_refund` | `order_id`: string, `reason`: string, `amount`: number | `{"refund_id": "REF-...", "status": "APPROVED", "amount": float, "estimated_days": 3}` |
| `check_refund_status` | `refund_id`: string | `{"refund_id": "REF-...", "status": "PROCESSING", "created_date": string}` |
| `get_return_label` | `order_id`: string | `{"tracking_number": "TRK...", "carrier": "UPS", "label_url": string, "expiry": string}` |

---

## 5. Local Setup & Execution Workflow

### 5.1 Prerequisites
- Python 3.12+ installed
- [uv](https://docs.astral.sh/uv/) package manager installed
- AWS CLI configured with active credentials in `us-east-1`
- Amazon Nova Lite model access granted in Bedrock console

### 5.2 Environment Setup

```powershell
# Navigate to starter directory
cd D:\AI-Support-agent\starter

# Create virtual environment and install dependencies
uv sync

# Add project dependencies if required
uv add strands-agents strands-agents-tools bedrock-agentcore bedrock-agentcore-starter-toolkit
```

### 5.3 Local Testing

To test the scaffold locally via CLI before cloud deployment:

```powershell
uv run python -c "from main import invoke; import asyncio; print(asyncio.run(invoke({'prompt': 'Hello, what can you help me with?', 'customer_id': 'CUST-123'})))"
```

---

## 6. Cloud Deployment Pipeline

Once implementation is complete and verified locally, deploy to Amazon Bedrock AgentCore:

```powershell
# 1. Configure the AgentCore runtime specification
agentcore configure --entrypoint main.py --name customer_support_agent

# 2. Deploy the containerized runtime to Bedrock AgentCore
agentcore deploy

# 3. Invoke the deployed endpoint
agentcore invoke '{\"prompt\": \"Can you track order ORD-001?\", \"customer_id\": \"CUST-123\"}' -s dev-test-session-001
```
