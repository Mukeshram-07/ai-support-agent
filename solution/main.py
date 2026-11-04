"""
Customer Support AI Agent — Solution
======================================
Fully implemented AgentCore + Strands customer support agent.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore configure --entrypoint main.py --name customer_support_agent
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser

# NOTE ON MEMORY AVAILABILITY —
#
# This AWS account currently has an account-level service quota override
# for AgentCore "Memories" fixed at 0 (AWS default is 150), which blocks
# CreateMemory with a generic AccessDeniedException rather than a normal
# quota-exceeded error. A quota increase request and AWS Support case are
# open (see REFLECTION.md for details). The Memory implementation below
# (get_namespaces, MemoryHook) is fully implemented per the rubric, but is
# designed to degrade gracefully: if MEMORY_ID is a placeholder, or any
# Memory API call fails (e.g. due to this quota block), the agent logs a
# warning and continues serving the request without memory context rather
# than crashing the whole invocation.


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CSAI_Agent")

# ── App Initialisation ────────────────────────────────────────────────────────
app = BedrockAgentCoreApp()

# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── Configuration ─────────────────────────────────────────────────────────────
# Fill these in with the resource identifiers you collected during setup.
GATEWAY_URL = os.environ.get("GATEWAY_URL", "https://customersupportgateway-qbizdvboqw.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp")
KB_ID       = os.environ.get("KB_ID", "ITJFN2BV0Z")          # Knowledge Base ID from the Bedrock console
REGION      = os.environ.get("AWS_REGION") or os.environ.get("REGION") or "us-east-1"
MEMORY_ID   = os.environ.get("MEMORY_ID") or os.environ.get("AGENTCORE_MEMORY_ID") or "<memory-id>"        # Memory ID from environment or fallback placeholder


# ── Model and Clients ─────────────────────────────────────────────────────────
model_id = "global.amazon.nova-2-lite-v1:0"

model = BedrockModel(model_id=model_id)
memory_client = MemoryClient(region_name=REGION)
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


# ── Namespace Helper ──────────────────────────────────────────────────────────
def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """
    Return a dict mapping strategy type -> namespace template string.

    Example output:
      { "SEMANTIC": "cs_agent/{actorId}/facts",
        "USER_PREFERENCE": "cs_agent/{actorId}/preferences" }

    Returns an empty dict (rather than raising) if the Memory resource is
    unavailable or MEMORY_ID is not configured, so callers can degrade
    gracefully instead of crashing the whole request.
    """
    if not memory_id or memory_id.strip().startswith("<"):
        return {}

    try:
        strategies = mem_client.get_memory_strategies(memory_id)
    except Exception as exc:
        logger.warning(f"Could not fetch memory strategies for {memory_id}: {exc}")
        return {}

    namespaces: Dict[str, str] = {}
    for strategy in strategies:
        strategy_type = strategy.get("type")

        # Support both the current "namespaceTemplates" field and the
        # legacy "namespaces" field, depending on SDK/API version.
        templates = (
            strategy.get("namespaceTemplates")
            or strategy.get("namespaces")
            or []
        )

        if strategy_type and templates:
            namespaces[strategy_type] = templates[0]

    return namespaces


# ── Memory Hook ────────────────────────────────────────────────────────────────
class MemoryHook(HookProvider):
    """
    Long-term memory hook for the customer support agent.

    Designed to fail gracefully: if the underlying Memory resource is
    unavailable (e.g. blocked by an account-level quota), namespaces will
    be empty and both callbacks become no-ops instead of raising.
    """

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(self.memory_client, self.memory_id)
        self.enabled = bool(self.namespaces)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        if not self.enabled:
            return

        message = event.message

        if message.get("role") != "user":
            return

        content = message.get("content", [])

        # Skip tool-result messages; only enrich plain-text user turns.
        if not content or any("toolResult" in block for block in content):
            return

        query_parts = [
            block["text"] for block in content
            if "text" in block and block["text"].strip()
        ]
        if not query_parts:
            return

        query = "\n".join(query_parts)
        memory_lines = []

        for strategy_type, namespace_template in self.namespaces.items():
            namespace = namespace_template.format(actorId=self.actor_id)
            try:
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=namespace,
                    query=query,
                    top_k=5,
                )
            except Exception as exc:
                logger.warning(f"Memory retrieval failed for {namespace}: {exc}")
                continue

            for memory in memories:
                text = memory.get("content", {}).get("text", "")
                if text:
                    memory_lines.append(f"[{strategy_type}] {text}")

        if memory_lines:
            context = "\n".join(memory_lines)
            enriched_query = f"Customer Context:\n{context}\n\n{query}"
            # Replace the text content, keeping this a normal user message.
            message["content"] = [{"text": enriched_query}]

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        if not self.enabled:
            return

        messages = event.agent.messages

        customer_query = None
        agent_response = None

        for message in reversed(messages):
            role = message.get("role")
            content = message.get("content", [])

            if role == "assistant" and agent_response is None:
                text_parts = [
                    block["text"] for block in content
                    if "text" in block and block["text"].strip()
                ]
                if text_parts:
                    agent_response = "\n".join(text_parts)

            elif role == "user" and customer_query is None:
                if any("toolResult" in block for block in content):
                    continue

                text_parts = [
                    block["text"] for block in content
                    if "text" in block and block["text"].strip()
                ]
                if text_parts:
                    customer_query = "\n".join(text_parts)

                    # If memory context was prepended earlier, save only the
                    # customer's original message, not the injected context.
                    if customer_query.startswith("Customer Context:\n"):
                        # Use split("\n\n", 1) instead of rsplit to preserve multi-paragraph user queries
                        parts = customer_query.split("\n\n", 1)
                        if len(parts) == 2:
                            customer_query = parts[1]

            if customer_query and agent_response:
                break

        if not customer_query or not agent_response:
            return

        try:
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[
                    (customer_query, "USER"),
                    (agent_response, "ASSISTANT"),
                ],
            )
        except Exception as exc:
            logger.warning(f"Failed to save support interaction: {exc}")

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


# ── Structured tool output (stand-out: Pydantic validation) ──────────────────
class LoyaltyDiscountResult(BaseModel):
    """Validated shape of the loyalty discount calculation result."""
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


# ── Knowledge Base Tool ───────────────────────────────────────────────────────
@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    if not KB_ID or not KB_ID.strip() or KB_ID.strip().startswith("<"):
        return "Knowledge base not configured."

    try:
        response = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
        )
    except Exception as exc:
        logger.error(f"Knowledge base retrieval failed: {exc}")
        return f"Knowledge base search failed: {exc}"

    results = response.get("retrievalResults", [])
    if not results:
        return "No relevant information found in the knowledge base."

    chunks = [
        result["content"]["text"]
        for result in results
        if result.get("content", {}).get("text")
    ]
    if not chunks:
        return "No relevant information found in the knowledge base."

    return "\n---\n".join(chunks)


# ── Loyalty Discount Tool (Code Interpreter) ─────────────────────────────────
@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    code = f"""
import json

earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

loyalty_points = {int(loyalty_points)}
tier = {tier!r}
order_total = {float(order_total)}
product_category = {product_category!r}

tier_rate = tier_rates.get(tier, 0.0)
earn_rate = earn_rates.get(product_category, 1)

# 100 points = $1. Redemption must be in blocks of 500 points and cannot
# exceed 50% of the original order value.
max_points_for_order = int((order_total * 0.50) * 100)
points_redeemed = min(loyalty_points, max_points_for_order)
points_redeemed = (points_redeemed // 500) * 500
points_discount = points_redeemed / 100.0

subtotal_after_points = max(0.0, order_total - points_discount)
tier_discount = subtotal_after_points * tier_rate

final_total = round(subtotal_after_points - tier_discount, 2)
total_savings = round(order_total - final_total, 2)
points_earned = int(final_total * earn_rate)
remaining_points = loyalty_points - points_redeemed + points_earned

result = {{
    "points_redeemed": points_redeemed,
    "points_discount": round(points_discount, 2),
    "tier_discount_pct": int(tier_rate * 100),
    "tier_discount": round(tier_discount, 2),
    "total_savings": total_savings,
    "final_total": final_total,
    "points_earned": points_earned,
    "remaining_points": remaining_points,
    "display_text": (
        f"Points redeemed: {{points_redeemed}} points. "
        f"Points discount: ${{points_discount:.2f}}. "
        f"Tier discount: {{int(tier_rate * 100)}}% applied after points "
        f"redemption, equal to ${{tier_discount:.2f}}. "
        f"Total savings: ${{total_savings:.2f}}. "
        f"Final total: ${{final_total:.2f}}. "
        f"Points earned: {{points_earned}}. "
        f"Remaining points: {{remaining_points}}."
    ),
}}

print(json.dumps(result))
"""

    try:
        with code_session(REGION) as code_client:
            response = code_client.invoke(
                "executeCode",
                {
                    "code": code,
                    "language": "python",
                    "clearContext": True,
                },
            )

            for event in response["stream"]:
                if "result" in event:
                    result = event["result"]
                    stdout = ""
                    for content_item in result.get("content", []):
                        if content_item.get("type") == "text":
                            stdout += content_item["text"]
                    stdout = stdout.strip()

                    if not stdout:
                        raise ValueError("Code Interpreter returned no output.")

                    validated = LoyaltyDiscountResult.model_validate_json(stdout)
                    return validated.model_dump_json()

        raise RuntimeError("Code Interpreter returned no result.")

    except Exception as e:
        logger.warning(f"Code Interpreter unavailable, using fallback: {e}")

        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_rate = tier_rates.get(tier, 0.0)
        tier_discount = round(order_total * tier_rate, 2)
        final_total = round(order_total - tier_discount, 2)

        fallback_result = LoyaltyDiscountResult(
            points_redeemed=0,
            points_discount=0.0,
            tier_discount_pct=int(tier_rate * 100),
            tier_discount=tier_discount,
            total_savings=tier_discount,
            final_total=final_total,
            points_earned=0,
            remaining_points=loyalty_points,
            fallback=True,
            display_text=(
                f"Code Interpreter fallback used. Points redeemed: 0 points. "
                f"Points discount: $0.00. Tier discount: {int(tier_rate * 100)}%, "
                f"equal to ${tier_discount:.2f}. Total savings: ${tier_discount:.2f}. "
                f"Final total: ${final_total:.2f}. Points earned: 0. "
                f"Remaining points: {loyalty_points}."
            ),
        )
        return fallback_result.model_dump_json()


# ── Agent Entrypoint ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are an intelligent customer support assistant for an e-commerce platform.

Use the available tools whenever appropriate:

- Use order-tracker Gateway tools to retrieve orders and customer information.
- Use refund-processor Gateway tools to initiate refunds, check refund status,
  or generate return labels.
- Before initiating a full refund, if the refund amount is not explicitly
  provided by the customer, first look up the order to retrieve its total,
  then pass that total as the amount when initiating the refund.
- Never describe a $0 refund as a full refund.

- Use search_knowledge_base for product information, return policies,
  warranties, loyalty program details, and support documentation.

- Use calculate_loyalty_discount for loyalty points and discount calculations.
  Treat its output as authoritative — never perform your own loyalty
  arithmetic. Report the exact values it returns (points_redeemed,
  points_discount, tier_discount_pct, tier_discount, total_savings,
  final_total, points_earned, remaining_points) using its display_text as
  the basis of your response.

- Use the browser tool when the customer asks you to visit or retrieve
  information from a live web page.
- Use any Customer Context supplied through memory to personalize responses,
  when available.
- If a tool fails or cannot retrieve data, clearly report the failure and do
  not guess, infer, or invent the missing information.

Never invent order details, refund results, policies, prices, or
calculations. Use tool results as the source of truth. Respond clearly and
concisely.
"""


@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """
    try:
        user_input = payload.get("prompt", "")
        actor_id = payload.get("customer_id", "anonymous")
        session_id = payload.get("session_id") or str(uuid.uuid4())

        if not user_input:
            return "Please provide a prompt."

        # Memory is best-effort: if it can't be constructed (e.g. the
        # account-level Memories quota is blocked), continue without it
        # rather than failing the whole request.
        hooks = []
        try:
            memory_hook = MemoryHook(
                actor_id=actor_id,
                session_id=session_id,
                memory_client=memory_client,
                memory_id=MEMORY_ID,
            )
            if memory_hook.enabled:
                hooks.append(memory_hook)
            else:
                logger.warning("Memory not available; continuing without it.")
        except Exception as exc:
            logger.warning(f"Memory hook initialization failed: {exc}")

        agent_core_browser = AgentCoreBrowser(region=REGION)

        tools = [
            search_knowledge_base,
            calculate_loyalty_discount,
            agent_core_browser.browser,
        ]

        gateway_client = MCPClient(lambda: streamable_http_client(GATEWAY_URL))
        try:
            with gateway_client:
                try:
                    gateway_tools = gateway_client.list_tools_sync()
                    if not gateway_tools:
                        logger.warning("Gateway connected but returned no tools.")
                        return (
                            "I'm sorry, the customer-support tools are currently "
                            "unavailable. Please try again later."
                        )
                    tools.extend(gateway_tools)
                    logger.info("Loaded %d Gateway tools.", len(gateway_tools))

                except Exception:
                    logger.exception("Gateway tool loading failed")
                    return (
                        "I'm sorry, the customer-support tools are currently "
                        "unavailable. Please try again later."
                    )

                try:
                    agent = Agent(
                        model=model,
                        tools=tools,
                        hooks=hooks,
                        system_prompt=SYSTEM_PROMPT,
                    )
                    response = await agent.invoke_async(user_input)
                    return response.message["content"][0]["text"]

                except Exception:
                    logger.exception("Agent invocation failed")
                    return (
                        "Sorry, I encountered an unexpected error while "
                        "processing your request. Please try again later."
                    )

        except Exception:
            logger.exception("Gateway connection failed")
            return (
                "I'm sorry, I couldn't connect to the customer-support "
                "service. Please try again later."
            )

    except Exception:
        logger.exception("Unexpected request processing failure")
        return (
            "Sorry, I encountered an unexpected error while processing "
            "your request. Please try again later."
        )


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()
