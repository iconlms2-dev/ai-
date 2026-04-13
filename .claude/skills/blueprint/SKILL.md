---
name: blueprint
description: Agentic system design blueprint generator. Interviews the user to understand a task they want to automate, then produces a comprehensive integrated design document (.md file) that serves as a concrete implementation plan for Claude Code. The design document includes task context, workflow definition with LLM vs code boundaries, and implementation spec (folder structure, agent architecture, skills/scripts list, sub-agent design). Trigger on "/blueprint", "blueprint", "에이전트 설계", "설계서 만들어", "agentic workflow design", or any request to design/plan an agent or automation system. Use this skill whenever the user mentions automation design, workflow planning, agent architecture, system blueprinting, multi-step AI workflow planning, or wants to structure any complex task into an agentic system — even if they don't explicitly say "blueprint".
---

# Blueprint

## Overview

Conduct a structured interview to understand the user's automation task, then generate a complete agentic system design document. The deliverable is a single `.md` file ready for use as an implementation reference in Claude Code.

## Before Starting

**Read both reference files before doing anything else.** They contain the document structure and design rules you'll apply in Phase 2. Skip them and the output will be incomplete.

1. Read `references/document-template.md` — the full section-by-section template for the output file
2. Read `references/design-principles.md` — design rules for agent structure, validation, data transfer, skill vs sub-agent
3. *(Optional)* Skim `references/example-blueprint.md` — a fully annotated sample blueprint document for calibration

## Workflow

### Phase 1: Assess & Interview

Evaluate user input against these four areas. **Ask only about gaps.** If all areas are sufficiently clear, skip directly to Phase 2.

| Area | What to assess | Example question |
|------|---------------|------------------|
| **Goal & success criteria** | Is the ultimate goal clear? Can success/failure be judged? | "어떤 결과가 나와야 이 에이전트가 성공했다고 볼 수 있나요?" |
| **Task procedure** | Are input→output steps defined? Are branch conditions known? | "A 이후 B로 갈지 C로 갈지는 어떤 기준으로 판단하나요?" |
| **Agent organization** | Single vs multi-agent preference? Any clear role separations? | "하나의 에이전트가 순차 처리하면 되나요, 아니면 분리할 역할이 있나요?" |
| **Tools & tech** | Any existing tools/APIs in use? If none, suggest options. | "지금 쓰는 도구가 있나요? 없다면 이런 방식들이 가능한데 어떤 게 맞을까요?" |

**Interview rules:**
- Questions must be specific and probing, never generic or formulaic
- If user says "모르겠다" or "알아서 해줘": apply reasonable defaults, state your choice and reasoning, ask only for unavoidable decisions
- Group related questions — never ask more than 3 questions per turn

### Phase 2: Generate Design Document

Once requirements are clear, map interview findings to document sections before writing:

| Interview finding | → Document section |
|---|---|
| Why this is needed, what problem it solves | § 1. 작업 컨텍스트 › 배경 및 목적 |
| What's in scope / out of scope | § 1. 작업 컨텍스트 › 범위 |
| Input format, output format, trigger | § 1. 작업 컨텍스트 › 입출력 정의 |
| Technical constraints, API limits | § 1. 작업 컨텍스트 › 제약조건 |
| Step-by-step process, branching logic | § 2. 워크플로우 정의 |
| What the agent decides vs what code handles | § 2. LLM 판단 vs 코드 처리 구분 |
| What tools/APIs are used | § 3. 스킬/스크립트 목록 |
| Single vs multi-agent preference | § 3. 에이전트 구조 |
| Failure conditions, retry expectations | § 2. 단계별 상세 › 실패 시 처리 |

Fill every section using the template in `references/document-template.md`. Apply design rules from `references/design-principles.md`.

Save as `blueprint-<task-name>.md` in the current working directory.

**Output rules:**
- CLAUDE.md, AGENT.md, skill file contents are **NOT written** — only their names and roles
- Implementation spec covers structure and responsibilities, not code or prompts
- Every workflow step must have: success criteria, validation method, failure handling
- **Always include a "스킬 생성 규칙" section** in every blueprint document. All skills defined in this document must be created via `skill-creator` at implementation time — direct manual authoring of SKILL.md is prohibited (see `references/design-principles.md` › Skill Creation Standards for the exact section text). The document **must contain the literal string `skill-creator`** — the structural validator checks for this and will fail without it.

**Completeness check before saving** — confirm each item is filled:
- [ ] Every workflow step has success criteria + validation method + failure handling
- [ ] LLM vs script responsibility table is filled
- [ ] Folder structure is defined
- [ ] "스킬 생성 규칙" section is present and mentions `skill-creator`
- [ ] No table cell left blank or "TBD"

### Phase 2.5: Validate Document

After saving, run the structural validation script before presenting the document to the user.

Do not assume a relative path from the target project — run the script from the **currently installed blueprint skill path**.

```bash
# When installed globally (normal usage):
python ~/.claude/skills/blueprint/scripts/validate_blueprint_doc.py ./blueprint-<task-name>.md

# When working inside the skill repository itself (development/testing only):
python .claude/skills/blueprint/scripts/validate_blueprint_doc.py ./blueprint-<task-name>.md
```

If validation fails, fix the document and run again. This script checks structure only (required sections, step fields, and implementation/workflow section presence) — it does not check content quality.

If the script is not found (e.g., first install or missing file), skip script validation and manually verify the Phase 2 completeness checklist instead:
- [ ] Every workflow step has success criteria + validation method + failure handling
- [ ] LLM vs script responsibility table is filled
- [ ] Folder structure is defined
- [ ] "스킬 생성 규칙" section is present and mentions `skill-creator`
- [ ] No table cell left blank or "TBD"

### Phase 3: Review

After presenting the document, summarize the key design decisions made during the interview:

- Agent structure choice (single vs multi) and the reason
- Any tradeoffs locked in (e.g., "LLM judges step X because rule-based detection was too fragile")
- Any constraints that shaped the design

Then ask: "Do these decisions match your intent? Let me know if there's anything you'd like to change."

Apply any requested changes and re-confirm.

## References

- **`references/document-template.md`**: Full template for the output design document (all sections, formats, tables)
- **`references/design-principles.md`**: Design rules for folder structure, agent architecture, validation patterns, failure handling, data transfer, and skill vs sub-agent distinctions
