# Reflection

## Design decision

For the loyalty discount tool, I validate the Code Interpreter's output against a Pydantic model (`LoyaltyDiscountResult`) instead of trusting the raw stdout string. The Code Interpreter prints JSON from sandboxed Python, with no guarantee every field is present or correctly typed. Parsing with `model_validate_json(...)` means malformed output raises immediately and falls through to the tier-only fallback, rather than handing the agent a broken discount breakdown. The system prompt also tells the model to treat the tool's `display_text` as authoritative and never recompute the arithmetic itself, since loyalty math involves exact rules (floor to nearest 500, 50% cap, tier percentages) that an LLM restating in its own words could get wrong.

## Challenge encountered

The biggest challenge was AgentCore Memory. My primary AWS account has an account-level quota override for AgentCore "Memories" fixed at 0 (AWS default is 150), so every `CreateMemory` call failed with a generic `AccessDeniedException` instead of a normal quota error. I confirmed this via the Service Quotas console (quota code L-81002DCC) and via boto3 in two regions; list/read operations worked fine, ruling out an IAM problem. I opened an AWS Support case and quota increase request, both still pending.

I tried a Udacity lab account where Memory worked, but `agentcore deploy` failed instantly during CodeBuild provisioning with no compute allocated — a lab-specific restriction (confirmed by a separate `cloudshell:CreateEnvironment` denial). Falling back to a local Docker/Podman build surfaced two real bugs instead: `pyproject.toml` required Python ≥3.13 while the Dockerfile used 3.12, and setuptools' package discovery failed because the project folder held non-package directories (`lambda/`, `screenshots/`) alongside `main.py`. Fixing both was the real fix — back on my personal account, `agentcore deploy` then succeeded immediately.

Since the quota is still unresolved, I implemented the full Memory system (`get_namespaces`, `MemoryHook` with both callbacks, `register_hooks`) per spec, but made it degrade gracefully: if `MEMORY_ID` is a placeholder or any call fails, the hook disables itself and the agent keeps serving requests with all other tools intact.

## Production consideration

IAM scoping for the Runtime execution role needs more care than the toolkit's auto-generated policy gives. During testing, both `search_knowledge_base` and the Browser tool failed with vague "authorization issue" messages, because the auto-created role had no `bedrock:Retrieve` permission on the Knowledge Base, nor `bedrock-agentcore:StartBrowserSession` for the Browser tool. I added both as scoped inline policies afterward. In production, this argues for a reviewed, custom execution role or automated policy checks in CI per tool path, so permission gaps surface before a real customer hits them mid-conversation.
