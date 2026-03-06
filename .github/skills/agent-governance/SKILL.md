---
name: agent-governance
description: |
  Patterns and techniques for adding governance, safety, and trust controls to AI agent systems. Use this skill when:
  - Building AI agents that call external tools (APIs, databases, file systems)
  - Implementing policy-based access controls for agent tool usage
  - Adding semantic intent classification to detect dangerous prompts
  - Creating trust scoring systems for multi-agent workflows
  - Building audit trails for agent actions and decisions
  - Enforcing rate limits, content filters, or tool restrictions on agents
  - Working with any agent framework (PydanticAI, CrewAI, OpenAI Agents, LangChain, AutoGen)
---

# Agent Governance Patterns

Patterns for adding safety, trust, and policy enforcement to AI agent systems.

## Overview

Governance patterns ensure AI agents operate within defined boundaries — controlling which tools they can call, what content they can process, how much they can do, and maintaining accountability through audit trails.

## Key Patterns

### 1. Governance Policy
Define what an agent is allowed to do as a composable, serializable policy object.

### 2. Semantic Intent Classification
Detect dangerous intent in prompts before they reach the agent, using pattern-based signals.

### 3. Tool-Level Governance Decorator
Wrap individual tool functions with governance checks.

### 4. Trust Scoring
Track agent reliability over time with decay-based trust scores for multi-agent systems.

### 5. Audit Trail
Append-only audit log for all agent actions — critical for compliance and debugging.

## When to Use

- **Agents with tool access**: Any agent that calls external tools (APIs, databases, shell commands)
- **Multi-agent systems**: Agents delegating to other agents need trust boundaries
- **Production deployments**: Compliance, audit, and safety requirements
- **Sensitive operations**: Financial transactions, data access, infrastructure management

## Core Components

- **Policy Objects**: Allowlists, blocklists, pattern matching, rate limits
- **Intent Classifiers**: Pre-flight threat detection before tool execution
- **Governance Decorators**: Per-tool enforcement and audit logging
- **Trust Registry**: Multi-agent trust scoring with temporal decay
- **Audit Trails**: Immutable logs for compliance and debugging

## Best Practices

- Enforce policies *before* tool execution (pre-flight checks)
- Use declarative policy objects for composability
- Implement temporal decay on trust scores
- Maintain append-only audit trails for compliance
- Combine multiple patterns (policy + intent + trust + audit)
