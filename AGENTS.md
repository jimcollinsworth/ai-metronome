# `AGENTS.md` — Universal Agent Guidelines & Operating Rules

This document outlines the operational principles, technical constraints, design philosophy, authoring boundaries, and versioning procedures for any LLM coding agent working on `ai-metronome`.

---

## 1. Mandatory Governance Documents

> [!IMPORTANT]
> The agent is authorized and permitted to maintain the core system, governance, and planning documents:
> 1. `README.md` – Project overview, architecture, developer setup, build instructions, and directory map.
> 2. `PLANNING.md` – Active backlog, sprint tasks, and near-term milestones.
> 3. `ROADMAP.md` – Long-term vision, feature backlog, brainstorming, creative ideas, and technical proposals.
> 4. `JOURNAL.md` – Chronological project log recording milestones, architectural decision records (ADRs), and technical changes.
> 5. `AGENTS.md` (and `.agents/agent_rules.md`) – Operational principles, technical constraints, authoring boundaries, and workflow rules.
> 6. `TESTING.md` – Comprehensive test strategy, test suites, execution commands, and verification procedures.
>
> **NO other system design, architecture, walkthrough, or meta documents may be created anywhere in this repository or workspace without first explicitly proposing them to Jim and receiving approval.**

---

## 2. Content & Core Logic Ownership Rules (Strict)

> [!CAUTION]
> **Source Materials Belong Exclusively to the Project Owner**:
> - Domain data, business rules, core documentation, and proprietary content are owned strictly by Jim.
> - **Zero Unauthorized Content Generation**: The agent must **NEVER draft brand new articles, opinionated business copy, or core domain assets** without explicit instruction.
> - **Mandatory Obvious Placeholder Rule**: When structural scaffolding or missing copy is required, the agent must **ALWAYS use obviously placeholder text** (e.g. `[Placeholder summary]`, `[Feature notes in progress]`) instead of fabricating or generating simulated content, unless explicitly instructed by Jim.
> - The agent must **NEVER create new primary content or domain files** on its own initiative.
> - The agent's role is strictly technical stewardship: maintaining clean code infrastructure, optimizing performance, managing build pipelines, maintaining test suites, and keeping governance documents up to date.

---

## 3. Technical Philosophy & Constraints

1. **Clean & Standard Toolchains**:
   - Prefer standard, community-accepted build tools and official language package managers (`uv`).
   - Avoid non-standard dependency wrappers or unnecessary global installations.
2. **Minimalist Dependencies**:
   - Keep the dependency footprint light. Favor standard library functions over single-use third-party packages whenever feasible.
3. **Robust Engineering & Test Coverage**:
   - Maintain clean modular architecture and unit tests under `tests/`.

---

## 4. Multi-Machine Git & Commit Workflow

> [!IMPORTANT]
> **Always Fetch/Pull from Origin Before Any Git Activity**:
> - Jim develops across multiple physical machines.
> - The agent **MUST ALWAYS run `git pull origin <branch>` (or `git fetch origin` followed by rebase/merge) before starting any git commit, branching, or push operations**, and before starting work sessions.
> - This guarantees local branches stay synchronized with remote work, avoiding out-of-date HEADs and unnecessary merge conflicts.
> - Always verify that working trees and tracking branches are clean and up to date before making success assertions or pushing.

- Active tasks and sprint status live in `PLANNING.md`.
- Architectural decisions and technical log entries are recorded in `JOURNAL.md`.
