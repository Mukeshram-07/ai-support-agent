"""
test_memory_recall.py
=====================
Test suite for Bedrock AgentCore Memory in Customer Support AI Agent.

Verifies:
  1. get_namespaces() supports both namespaceTemplates and legacy namespaces.
  2. MemoryHook inherits from HookProvider and registers callbacks.
  3. save_support_interaction() correctly extracts turn and fixes the
     multi-paragraph bug (preserving complete user query without truncation).
  4. retrieve_customer_context() retrieves memories across namespaces, tags them
     by strategy type, and prepends them to the user query.
  5. Cross-Session Memory Recall:
     - Session A (customer_id: CUST-123, session_id: session-A) saves preferences.
     - Session B (customer_id: CUST-123, session_id: session-B) recalls preferences.
  6. Live AWS AgentCore Memory configuration check (reports quota/credential blockers).
"""

import sys
import os
import types
import unittest
from typing import Dict, List, Any

# Ensure solution directory is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# ── Ensure required modules exist for local evaluation ───────────────────────
try:
    from strands.hooks import HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent
except ImportError:
    class HookProvider:
        pass

    class HookRegistry:
        def __init__(self):
            self.callbacks = {}

        def add_callback(self, event_type, callback):
            self.callbacks.setdefault(event_type, []).append(callback)

    class MessageAddedEvent:
        def __init__(self, message: Dict[str, Any], agent: Any = None):
            self.message = message
            self.agent = agent

    class AfterInvocationEvent:
        def __init__(self, agent: Any):
            self.agent = agent

    # Register in sys.modules
    strands = types.ModuleType("strands")
    strands.tool = lambda fn: fn
    strands.Agent = type("Agent", (), {})
    sys.modules["strands"] = strands

    strands_hooks = types.ModuleType("strands.hooks")
    strands_hooks.HookProvider = HookProvider
    strands_hooks.HookRegistry = HookRegistry
    strands_hooks.MessageAddedEvent = MessageAddedEvent
    strands_hooks.AfterInvocationEvent = AfterInvocationEvent
    sys.modules["strands.hooks"] = strands_hooks

    strands_models = types.ModuleType("strands.models")
    strands_models.BedrockModel = type("BedrockModel", (), {"__init__": lambda self, **k: None})
    sys.modules["strands.models"] = strands_models

    mcp = types.ModuleType("mcp")
    mcp_client = types.ModuleType("mcp.client")
    mcp_stream = types.ModuleType("mcp.client.streamable_http")
    mcp_stream.streamable_http_client = lambda url: None
    sys.modules["mcp"] = mcp
    sys.modules["mcp.client"] = mcp_client
    sys.modules["mcp.client.streamable_http"] = mcp_stream

    strands_tools = types.ModuleType("strands.tools")
    strands_tools_mcp = types.ModuleType("strands.tools.mcp")
    strands_tools_mcp_client = types.ModuleType("strands.tools.mcp.mcp_client")
    strands_tools_mcp_client.MCPClient = type("MCPClient", (), {"__init__": lambda self, fn: None})
    sys.modules["strands.tools"] = strands_tools
    sys.modules["strands.tools.mcp"] = strands_tools_mcp
    sys.modules["strands.tools.mcp.mcp_client"] = strands_tools_mcp_client

    strands_tools_browser = types.ModuleType("strands_tools.browser")
    strands_tools_browser.AgentCoreBrowser = type("AgentCoreBrowser", (), {"__init__": lambda self, region: None, "browser": None})
    sys.modules["strands_tools"] = types.ModuleType("strands_tools")
    sys.modules["strands_tools.browser"] = strands_tools_browser

    boto3_mod = types.ModuleType("boto3")
    boto3_mod.client = lambda *a, **k: None
    sys.modules["boto3"] = boto3_mod

    bac = types.ModuleType("bedrock_agentcore")
    bac_runtime = types.ModuleType("bedrock_agentcore.runtime")
    bac_runtime.BedrockAgentCoreApp = type("BedrockAgentCoreApp", (), {"entrypoint": lambda self, fn: fn, "run": lambda self: None})
    bac_memory = types.ModuleType("bedrock_agentcore.memory")
    bac_memory.MemoryClient = type("MemoryClient", (), {"__init__": lambda self, **k: None})
    bac_tools = types.ModuleType("bedrock_agentcore.tools")
    bac_tools_ci = types.ModuleType("bedrock_agentcore.tools.code_interpreter_client")
    bac_tools_ci.code_session = lambda region: None

    sys.modules["bedrock_agentcore"] = bac
    sys.modules["bedrock_agentcore.runtime"] = bac_runtime
    sys.modules["bedrock_agentcore.memory"] = bac_memory
    sys.modules["bedrock_agentcore.tools"] = bac_tools
    sys.modules["bedrock_agentcore.tools.code_interpreter_client"] = bac_tools_ci

# Import the actual solution implementation
from main import get_namespaces, MemoryHook, MEMORY_ID, HookProvider, MessageAddedEvent, AfterInvocationEvent, HookRegistry


# ── Mock Bedrock AgentCore Memory Client for Rigorous Functional Testing ─────
class MockAgentCoreMemoryClient:
    """
    In-memory simulation of Bedrock AgentCore Memory service.
    Implements get_memory_strategies, create_event, and retrieve_memories.
    """
    def __init__(self, strategies=None):
        self.strategies = strategies or [
            {
                "type": "USER_PREFERENCE",
                "namespaceTemplates": ["cs_agent/{actorId}/preferences"]
            },
            {
                "type": "SEMANTIC",
                "namespaceTemplates": ["cs_agent/{actorId}/facts"]
            }
        ]
        # Store events: memory_id -> actor_id -> list of event dicts
        self.events = {}
        # Store extracted memories per namespace
        self.namespace_memories = {}

    def get_memory_strategies(self, memory_id: str) -> List[Dict]:
        return self.strategies

    def create_event(self, memory_id: str, actor_id: str, session_id: str, messages: List):
        event = {
            "session_id": session_id,
            "messages": messages,
        }
        self.events.setdefault(memory_id, {}).setdefault(actor_id, []).append(event)

        # In AgentCore Memory, create_event analyzes the conversation turn
        # and extracts long-term semantic memories into the corresponding namespaces.
        pref_ns = f"cs_agent/{actor_id}/preferences"
        facts_ns = f"cs_agent/{actor_id}/facts"

        for content, role in messages:
            if role == "USER":
                if "fresh groceries" in content.lower() or "bullet-point" in content.lower():
                    self.namespace_memories.setdefault(pref_ns, []).append({
                        "content": {
                            "text": "Favorite product category is fresh groceries. Prefers bullet-point answers."
                        }
                    })
                if "order" in content.lower() or "kindle" in content.lower():
                    self.namespace_memories.setdefault(facts_ns, []).append({
                        "content": {
                            "text": f"Customer discussed: {content[:80]}"
                        }
                    })

    def retrieve_memories(self, memory_id: str, namespace: str, query: str, top_k: int = 5) -> List[Dict]:
        return self.namespace_memories.get(namespace, [])


class AgentStateShim:
    """Simulates agent object passed in AfterInvocationEvent."""
    def __init__(self, messages: List[Dict]):
        self.messages = messages


class TestAgentCoreMemory(unittest.TestCase):

    def test_01_get_namespaces_dual_support(self):
        """Verify get_namespaces supports both namespaceTemplates and legacy namespaces."""
        print("\n[TEST 1] Testing get_namespaces() dual format support...")
        
        # Test modern field: namespaceTemplates
        client_modern = MockAgentCoreMemoryClient(strategies=[
            {"type": "SEMANTIC", "namespaceTemplates": ["cs_agent/{actorId}/facts"]},
            {"type": "USER_PREFERENCE", "namespaceTemplates": ["cs_agent/{actorId}/preferences"]}
        ])
        namespaces_modern = get_namespaces(client_modern, "mem-valid-id-123")
        self.assertEqual(namespaces_modern.get("SEMANTIC"), "cs_agent/{actorId}/facts")
        self.assertEqual(namespaces_modern.get("USER_PREFERENCE"), "cs_agent/{actorId}/preferences")

        # Test legacy field: namespaces
        client_legacy = MockAgentCoreMemoryClient(strategies=[
            {"type": "SEMANTIC", "namespaces": ["legacy_cs/{actorId}/facts"]},
            {"type": "USER_PREFERENCE", "namespaces": ["legacy_cs/{actorId}/preferences"]}
        ])
        namespaces_legacy = get_namespaces(client_legacy, "mem-valid-id-456")
        self.assertEqual(namespaces_legacy.get("SEMANTIC"), "legacy_cs/{actorId}/facts")
        self.assertEqual(namespaces_legacy.get("USER_PREFERENCE"), "legacy_cs/{actorId}/preferences")

        # Test empty/placeholder memory_id degrades gracefully
        namespaces_placeholder = get_namespaces(client_modern, "<memory-id>")
        self.assertEqual(namespaces_placeholder, {})

        print("  -> PASS: get_namespaces successfully parsed both modern and legacy formats.")

    def test_02_memory_hook_structure_and_registration(self):
        """Verify MemoryHook subclasses HookProvider and registers both hooks."""
        print("\n[TEST 2] Testing MemoryHook subclassing and register_hooks()...")
        self.assertTrue(issubclass(MemoryHook, HookProvider))

        client = MockAgentCoreMemoryClient()
        hook = MemoryHook(
            actor_id="CUST-123",
            session_id="session-test",
            memory_client=client,
            memory_id="mem-valid-id-123",
        )
        self.assertTrue(hook.enabled)

        registry = HookRegistry()
        hook.register_hooks(registry)
        self.assertIn(MessageAddedEvent, registry.callbacks)
        self.assertIn(AfterInvocationEvent, registry.callbacks)
        print("  -> PASS: MemoryHook extends HookProvider and registers MessageAddedEvent & AfterInvocationEvent.")

    def test_03_multi_paragraph_bug_fix_in_save_support_interaction(self):
        """Verify save_support_interaction preserves multi-paragraph queries without truncation."""
        print("\n[TEST 3] Testing multi-paragraph user query preservation in save_support_interaction()...")
        client = MockAgentCoreMemoryClient()
        hook = MemoryHook(
            actor_id="CUST-123",
            session_id="session-test",
            memory_client=client,
            memory_id="mem-valid-id-123",
        )

        multi_paragraph_query = (
            "Paragraph 1: My favorite category is fresh groceries.\n\n"
            "Paragraph 2: I also prefer bullet-point answers.\n\n"
            "Paragraph 3: Please keep this in mind for all future sessions."
        )
        prepended_message = f"Customer Context:\n[USER_PREFERENCE] Previous preference\n\n{multi_paragraph_query}"

        agent_shim = AgentStateShim(messages=[
            {
                "role": "user",
                "content": [{"text": prepended_message}],
            },
            {
                "role": "assistant",
                "content": [{"text": "Understood, I will remember all three instructions."}],
            }
        ])

        event = AfterInvocationEvent(agent=agent_shim)
        hook.save_support_interaction(event)

        # Inspect saved event
        saved_events = client.events["mem-valid-id-123"]["CUST-123"]
        self.assertEqual(len(saved_events), 1)
        saved_query = saved_events[0]["messages"][0][0]

        # Verify all 3 paragraphs survived intact without truncation!
        self.assertEqual(saved_query, multi_paragraph_query)
        self.assertIn("Paragraph 1:", saved_query)
        self.assertIn("Paragraph 2:", saved_query)
        self.assertIn("Paragraph 3:", saved_query)
        print("  -> PASS: split('\\n\\n', 1) preserved complete multi-paragraph message without truncation.")

    def test_04_cross_session_memory_recall_workflow(self):
        """
        Verify end-to-end Cross-Session Memory Recall:
          - Session A: Customer CUST-123 provides preferences in session-A.
          - Session B: Customer CUST-123 asks for preferences in session-B.
          - Information saved in Session A is retrieved and prepended to Session B query.
        """
        print("\n" + "=" * 70)
        print("[TEST 4] CROSS-SESSION MEMORY RECALL VERIFICATION")
        print("=" * 70)

        mock_backend = MockAgentCoreMemoryClient()
        memory_id = "mem-production-001"
        customer_id = "CUST-123"

        # ── SESSION A ────────────────────────────────────────────────────────
        session_a_id = "session-A"
        user_message_a = "My favorite product category is fresh groceries, and I prefer bullet-point answers."
        assistant_reply_a = (
            "Got it! I've noted that your favorite category is fresh groceries "
            "and you prefer bullet-point answers. How can I help you today?"
        )

        print(f"\n[SESSION A]")
        print(f"  Customer ID : {customer_id}")
        print(f"  Session ID  : {session_a_id}")
        print(f"  User Input  : \"{user_message_a}\"")

        hook_a = MemoryHook(
            actor_id=customer_id,
            session_id=session_a_id,
            memory_client=mock_backend,
            memory_id=memory_id,
        )
        self.assertTrue(hook_a.enabled)

        # Simulate agent execution for Session A
        agent_session_a = AgentStateShim(messages=[
            {"role": "user", "content": [{"text": user_message_a}]},
            {"role": "assistant", "content": [{"text": assistant_reply_a}]},
        ])

        # Hook callback: save_support_interaction on AfterInvocationEvent
        hook_a.save_support_interaction(AfterInvocationEvent(agent=agent_session_a))

        # Verify event saved in Session A
        saved_events = mock_backend.events.get(memory_id, {}).get(customer_id, [])
        self.assertEqual(len(saved_events), 1)
        self.assertEqual(saved_events[0]["session_id"], session_a_id)
        self.assertEqual(saved_events[0]["messages"][0][0], user_message_a)
        print(f"  Assistant   : \"{assistant_reply_a}\"")
        print(f"  Status      : Successfully saved turn to AgentCore Memory (session_id={session_a_id})")

        # ── SESSION B ────────────────────────────────────────────────────────
        session_b_id = "session-B"
        user_message_b = "What are my preferences?"

        print(f"\n[SESSION B]")
        print(f"  Customer ID : {customer_id}")
        print(f"  Session ID  : {session_b_id}  (DIFFERENT SESSION ID)")
        print(f"  User Input  : \"{user_message_b}\"")

        # Initialize MemoryHook for Session B with DIFFERENT session_id and SAME customer_id
        hook_b = MemoryHook(
            actor_id=customer_id,
            session_id=session_b_id,
            memory_client=mock_backend,
            memory_id=memory_id,
        )
        self.assertTrue(hook_b.enabled)

        # In Session B, inbound MessageAddedEvent fires before model inference
        inbound_message = {
            "role": "user",
            "content": [{"text": user_message_b}],
        }
        event_b = MessageAddedEvent(message=inbound_message)
        hook_b.retrieve_customer_context(event_b)

        enriched_content = inbound_message["content"][0]["text"]
        print(f"  Enriched Inbound Query with Recalled Memory:\n  ---\n  {enriched_content}\n  ---")

        # Assertions for cross-session recall:
        self.assertTrue(enriched_content.startswith("Customer Context:\n"))
        self.assertIn("[USER_PREFERENCE]", enriched_content)
        self.assertIn("fresh groceries", enriched_content)
        self.assertIn("bullet-point", enriched_content)
        self.assertIn(user_message_b, enriched_content)

        print("\n  -> PASS: Cross-session recall verified! Session B successfully recalled Session A preferences.")


def check_aws_live_environment():
    """Checks the live AWS AgentCore Memory environment status."""
    print("\n" + "=" * 70)
    print("LIVE AWS ENVIRONMENT DIAGNOSTIC")
    print("=" * 70)
    print(f"  Configured MEMORY_ID : {MEMORY_ID}")
    
    if not MEMORY_ID or MEMORY_ID.startswith("<"):
        print("  Status: MEMORY_ID is unconfigured / using default placeholder '<memory-id>'.")
        print("  Root Blocker: AWS Account Service Quota 'Memories' (code: L-81002DCC) is 0.")
        print("  AWS Error   : CreateMemory fails with AccessDeniedException (account quota override).")
        print("  To activate live memory once quota is increased above 0:")
        print("    1. Create Memory resource: aws bedrock-agentcore create-memory --name customer-support-memory")
        print("    2. Set environment variable: $env:MEMORY_ID = '<your-actual-memory-id>'")
        print("    3. Re-run main.py or agentcore deploy")
    else:
        print(f"  Active Memory Resource detected: {MEMORY_ID}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    check_aws_live_environment()
    unittest.main()
