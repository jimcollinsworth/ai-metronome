# Agent Guidelines & Rules: ai-metronome

This document outlines the operational principles, technical constraints, design philosophy, authoring boundaries, and procedures for any LLM coding agent maintaining Jim Collinsworth's project `ai-metronome`.

---

## 1. Mandatory Governance Documents

> [!IMPORTANT]
> The agent is authorized and permitted to maintain the core system, governance, and planning documents:
> 1. `README.md` – Project overview, architecture, developer setup, and directory map.
> 2. `PLANNING.md` – Active backlog, sprint tasks, and near-term milestones.
> 3. `ROADMAP.md` – Long-term discussion of features, brainstorming, creative ideas, and future possibilities.
> 4. `JOURNAL.md` – Chronological project log recording milestones, technical decisions, and changes.
> 5. `AGENTS.md` (and `.agents/agent_rules.md`) – Operational principles, technical constraints, authoring boundaries, and workflow rules.
> 6. `TESTING.md` – Comprehensive test strategy, test suites, execution commands, and verification procedures.
>
> **NO other system design, architecture, walkthrough, or meta documents may be created anywhere in this repository or workspace without first explicitly proposing them to Jim and receiving approval.**

---

## 2. Content Authoring Boundaries & Human Source Rules (Strict)

> [!CAUTION]
> **Source Materials & Business Rules Belong Exclusively to Jim**:
> - Domain data, business rules, core documentation, and proprietary content are owned strictly by the project author.
> - **Zero Unauthorized Content Generation**: The agent must **NEVER draft brand new articles, opinionated business copy, or core domain assets** without explicit instruction.
> - **Mandatory Obvious Placeholder Rule**: When structural scaffolding or missing copy is required, the agent must **ALWAYS use obviously placeholder text** (e.g. `[Placeholder summary]`, `[Feature notes in progress]`) instead of fabricating or generating simulated content, unless explicitly instructed by Jim.
> - The agent must **NEVER create new primary content or domain files** on its own initiative.
> - The agent's role is strictly technical stewardship: maintaining clean code infrastructure, optimizing performance, managing build pipelines, maintaining test suites, and keeping governance documents up to date.

---

## 3. Technical Philosophy & Constraints

1. **Clean & Standard Toolchains**:
   - Pure Python ecosystem managed via `uv` (`.venv/`).
   - Prefer standard, community-accepted build tools and official language package managers.
2. **Minimalist Dependencies**:
   - Keep the dependency footprint light. Favor standard library functions over single-use third-party packages whenever feasible.
3. **Robust Engineering & Test Coverage**:
   - Test-driven development for core algorithms and utilities.
   - Maintain automated unit tests executable via `uv run pytest`.

---

## 4. Multi-Machine Git & Commit Workflow

> [!IMPORTANT]
> **Always Fetch/Pull from Origin Before Any Git Activity**:
> - Jim develops across multiple physical machines.
> - The agent **MUST ALWAYS run `git pull origin <branch>` (or `git fetch origin` followed by rebase/merge) before starting any git commit, branching, or push operations**, and before starting work sessions.
> - This guarantees local branches stay synchronized with remote work, avoiding out-of-date HEADs and unnecessary merge conflicts.
> - Always verify that working trees and tracking branches are clean and up to date before making success assertions or pushing.

- Keep `PLANNING.md` updated as tasks progress.
- Record significant decisions and architectural milestones in `JOURNAL.md`.
