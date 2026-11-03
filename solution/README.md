# Solution — Customer Support AI Agent

This folder contains the completed implementation for the AgentCore + Strands
customer support agent project.

## Contents

- `main.py` — fully implemented agent (all 8 TODO sections completed)
- `product_catalog.txt` — knowledge base source document (uploaded to S3)
- `pyproject.toml` — dependency manifest (managed with `uv`)
- `lambda/order_tracker.py` — deployed as-is to Lambda (`order-tracker`)
- `lambda/refund_processor.py` — deployed as-is to Lambda (`refund-processor`)
- `lambda/lambda_schema` — MCP tool schema for the refund-processor Gateway target
- `screenshots/` — test evidence for 5 of 6 test scenarios + CloudWatch alarm
  + Memory-quota-blocked evidence (see Memory status below)
- `REFLECTION.md` — written reflection (design decision / challenge / production consideration)

## Vector store note

This solution uses **Amazon S3 Vectors** (native S3 vector bucket) as the
Knowledge Base vector store instead of OpenSearch Serverless. This was
selected directly in the Bedrock console KB creation wizard
("Quick create a new vector store" → S3 vector bucket) and required no
separate OpenSearch collection to provision or clean up.

## Memory status — implemented, but not runtime-active in this deployment

AgentCore Memory is **fully implemented** in `main.py` per the rubric
(`get_namespaces`, `MemoryHook` extending `HookProvider` with
`retrieve_customer_context` and `save_support_interaction`, and
`register_hooks`), but is **not active** in the deployed agent used for
this submission's test evidence.

Root cause: the AWS account has an account-level service quota override for
AgentCore "Memories" fixed at **0** (AWS default is 150 — quota code
`L-81002DCC`), which causes every `CreateMemory` call to fail with a
generic `AccessDeniedException` rather than a clear quota error. A quota
increase request and AWS Support case were opened but not resolved before
the submission deadline. See `REFLECTION.md` for the full diagnosis and
`screenshots/memory_quota.png` / `screenshots/blocked_memory.png` for the
Service Quotas console evidence.

The code is written to degrade gracefully: `MEMORY_ID` is left as the
placeholder `"<memory-id>"`, `get_namespaces()` detects this and returns an
empty dict instead of raising, `MemoryHook.enabled` becomes `False`, and the
agent runs normally with all other tools (Gateway, Knowledge Base, Code
Interpreter, Browser) unaffected. If the quota is approved, setting
`MEMORY_ID` to a real Memory ID re-activates memory with no other code
changes required.

## Before deploying

Fill in the config values at the top of `main.py`:

```python
GATEWAY_URL = "https://<alias>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "<your-kb-id>"
REGION      = "us-east-1"
MEMORY_ID   = "<your-memory-id>"   # leave as placeholder if Memory is unavailable
```

## Deploy

```powershell
uv sync
agentcore configure --entrypoint main.py --name customer_support_agent
agentcore deploy
```

The AgentCore Runtime execution role that `agentcore configure` auto-creates
does **not** include permissions for Knowledge Base retrieval or the
Browser tool by default. After deploying, two additional inline policies
were attached to the runtime role (`AmazonBedrockAgentCoreSDKRuntime-...`):

- `KnowledgeBaseRetrieveAccess` — grants `bedrock:Retrieve` scoped to the
  specific Knowledge Base ARN
- `BrowserToolAccess` — grants `bedrock-agentcore:StartBrowserSession`,
  `ConnectBrowserAutomationStream`, and related actions needed by the
  AgentCore Browser tool

Without these, `search_knowledge_base` and the browser tool fail with a
generic "authorization issue" message from the agent rather than a clear
IAM error.

## Test

Use `agentcore invoke` with the `-s`/`--session-id` flag (session IDs must
be 33+ characters) rather than embedding `session_id` in the JSON payload —
the CLI does not accept a `session_id` key inside the payload itself.

```powershell
agentcore invoke '{\"prompt\": \"Can you track order ORD-001?\", \"customer_id\": \"CUST-123\"}' -s test1-order-tracking-session-0001
```

See `REFLECTION.md` for the full list of test commands and outcomes.

## CloudWatch alarm

A metric filter (`CustomerSupportAgentErrors`, pattern `ERROR`) on the
agent's runtime log group feeds a custom metric
(`CustomerSupportAgent/CustomerSupportAgentErrorCount`), which triggers the
`CustomerSupportAgent-HighErrorRate` alarm when more than 5 errors occur in
a 5-minute window. See `screenshots/cloudwatch_alarm.png`.
