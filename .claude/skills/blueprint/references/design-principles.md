# Design Principles for Agentic Systems

## Folder Structure

```
/project-root
  ├── CLAUDE.md                        # Main agent instructions
  ├── /.claude
  │   ├── /skills/<skill-name>
  │   │   ├── SKILL.md
  │   │   ├── /scripts                 # Deterministic tools
  │   │   └── /references              # (optional) domain knowledge, API guides
  │   └── /agents/<subagent-name>
  │       └── AGENT.md
  ├── /output                          # Artifacts
  └── /docs                            # (optional) reference documents
```

## Agent vs Script Responsibility

| Agent handles directly | Script handles |
|------------------------|----------------|
| Classification, decision-making, priority judgment | File I/O, data parsing |
| Quality evaluation, qualitative analysis | External API calls |
| Context-based inference | Iteration, aggregation |
| Natural language generation/summarization | Static analysis, test execution |

## Validation Patterns

Every workflow step must define success criteria. Choose validation type by output nature:

| Validation type | Applies to | Example |
|-----------------|-----------|---------|
| **Schema validation** | Structured outputs | Required fields present, type check |
| **Rule-based** | Quantitative criteria | Item count, character count, required sections |
| **LLM self-validation** | Qualitative outputs | Summary quality, tone, completeness |
| **Human review** | High-risk final outputs | External documents, decisions |

## Failure Handling

| Pattern | When to use |
|---------|-------------|
| **Auto retry** | Validation failure is simple omission/format error (specify max retries) |
| **Escalation** | High judgment uncertainty or ambiguous criteria → ask human |
| **Skip + log** | Optional step with no flow impact → record reason in log |

## Agent Structure Choice

**Single agent** (default):
- Workflow is simple and instructions are short

**Sub-agent separation** (when needed):
- Context window optimization required — instructions too long to always load
- Clearly distinct independent task blocks requiring different domain knowledge

## Sub-agent Design Rules

- CLAUDE.md (main agent) acts as orchestrator
- Sub-agents must NOT call each other directly — coordinate through main
- AGENT.md must specify: role, trigger condition, input/output, referenced skills

## Data Transfer Patterns

| Pattern | When to use |
|---------|------------|
| **File-based** | Data is large or structured → `/output/step1_result.json` |
| **Prompt inline** | Data is small and simple |

Recommendation: Store intermediate outputs in `/output/` and pass only file paths.

## Skill vs Sub-agent

| Skill | Sub-agent |
|-------|-----------|
| Tool/function unit (small) | Role/responsibility unit (large) |
| Shareable across multiple agents | Specific to one workflow |
| Examples: `file-parser`, `api-caller` | Examples: `code-reviewer`, `report-generator` |

## Skill Creation Standards

블루프린트로 설계된 모든 시스템에서 구현 단계에서 반드시 **`skill-creator` 스킬**을 사용하여 스킬을 생성·검증해야 한다. 설계서에 스킬이 포함되어 있는지 여부와 무관하게, 스킬을 구현할 때 직접 SKILL.md를 손으로 작성하는 것은 금지된다. 규격 불일치 및 트리거 실패를 방지하기 위한 필수 규칙이다.

### 왜 skill-creator를 거쳐야 하는가

- **SKILL.md frontmatter 규격**: `name`, `description` 필수 필드 + 트리거 정확도를 위한 description 최적화가 필요
- **폴더 구조 규격**: `SKILL.md` + `scripts/`, `references/`, `assets/` 구조를 준수해야 함
- **Progressive disclosure**: SKILL.md 본문 500줄 이내, 대용량 참조는 `references/`로 분리
- **Description 최적화**: skill-creator의 description optimization 루프를 거쳐야 트리거 정확도가 보장됨
- **테스트 검증**: 테스트 프롬프트 실행 → 평가 → 개선 루프를 통해 스킬 품질 확보

### 설계서에 포함할 내용

블루프린트 문서의 **구현 스펙 > 스킬/스크립트 목록** 또는 별도 섹션에 아래 내용을 명시:

```markdown
## 스킬 생성 규칙

이 설계서에 정의된 모든 스킬은 구현 시 반드시 `skill-creator` 스킬(`/skill-creator`)을 사용하여 생성할 것.
직접 SKILL.md를 수동 작성하지 말 것 — 규격 불일치 및 트리거 실패의 원인이 됨.

skill-creator가 보장하는 규격:
1. SKILL.md frontmatter (name, description) 필수 필드 준수
2. description의 트리거 정확도 최적화 (eval 기반 optimization loop)
3. 폴더 구조 (SKILL.md + scripts/ + references/) 규격 준수
4. 테스트 프롬프트 실행 및 품질 검증 완료
```
