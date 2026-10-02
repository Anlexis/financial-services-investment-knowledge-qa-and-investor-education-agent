"""AgentCore Platform v1.0"""

# Manifest entry point. config/agent.yaml declares module: "src.graph" and
# class: "InvestmentKnowledgeQAAgent", and AgentRegistry resolves the agent with
# getattr(import_module("src.graph"), "InvestmentKnowledgeQAAgent"). Re-export the
# class here so that lookup succeeds; without it the package imports cleanly but
# the registry load fails with AttributeError at runtime.

from .graph import InvestmentKnowledgeQAAgent

__all__ = ["InvestmentKnowledgeQAAgent"]
