# Blueprint Worked Example

This file contains an annotated reference blueprint for the n8n workflow automation agent system.
It is a calibration sample — not intended for direct validation. Read the annotations below before studying the document.

---

## What to notice in this example

**1. Constraints are specific (§1)**
The "constraints" section often gets filled in vaguely. This example documents real tool limitations upfront (Google Forms Trigger not supported, Execute Command prohibited) and links each constraint to its handling in the relevant workflow step. Good constraints prevent implementers from being surprised.

**2. The flow diagram has explicit branching (§2 overall flow)**
Both decision points appear in the diagram: "create new" vs "modify existing", and "deploy directly to n8n" vs "export JSON fallback". A linear flow diagram with no branching weakens the design document's value.

**3. Every step has success criteria + validation method + failure handling (§2 step detail)**
Even Step 1 (environment check) specifies "success criteria: deployment mode is clearly determined" and "validation method: rule-based". Never omit these fields for steps that seem trivial — they matter most during implementation.

**4. The single-agent choice is explicitly justified (§3 agent structure)**
If you chose a single agent, write at least one sentence explaining why multi-agent was rejected. This example: "Each step depends on the result of the previous step. Maintaining consistent context matters more than role separation."

**5. §4 Key Design Decisions is a section not in the template**
The template is a minimum structure. Important decisions that emerge during design (fallback strategy, prohibited pattern mapping, GWS resource selection criteria) should be captured in a new section. Without this section, "why was it designed this way?" becomes unanswerable later.

---

## 원문 설계서

---

# n8n 워크플로우 디자이너 에이전트 시스템 설계서

> 작성일: 2026-03-14
> 목적: Claude Code 구현 참조용 계획서

---

## 1. 작업 컨텍스트

### 배경 및 목적
사용자가 자연어로 원하는 자동화 워크플로우를 묘사하면, 이를 분석하여 상세 SOP를 작성하고, 최종적으로 n8n 워크플로우를 생성·배포하는 에이전트 시스템. Google Workspace 연동이 필요한 경우 gws 스킬을 활용하여 문서/시트/폼 등을 직접 생성하거나 사용자에게 URL을 요청한다.

### 범위
- 포함: 범용 n8n 워크플로우 설계, SOP 문서 생성, Google Workspace 리소스 연동, n8n 배포 또는 JSON 내보내기
- 제외: 워크플로우 실행 테스트(사용자가 직접 수행), n8n 서버 설치/관리, 로컬 파일 I/O 기반 시나리오

### 입출력 정의

| 항목 | 내용 |
|------|------|
| **입력** | 사용자의 자연어 워크플로우 설명 (채팅 입력) |
| **출력** | (1) SOP 문서 (.md), (2) n8n 워크플로우 (n8n 인스턴스 등록 또는 .json 파일) |
| **트리거** | 사용자가 슬래시 커맨드(`/n8n-workflow`)로 호출 |

### 제약조건
- n8n Execute Command 노드 사용 금지 (n8n 2.0부터 기본 비활성화) → Code 노드로 대체
- 로컬 파일 읽기/쓰기 시나리오 금지 → Google Drive, HTTP Request 등 대안 제시
- n8n MCP 미설치 또는 API 미설정 시 직접 배포 불가 → JSON 파일 내보내기로 폴백
- Google Workspace 연동 시 사용자 PC에 gws 스킬이 유저 스코프로 설치되어 있음을 전제
- **언어**: 입출력 모두 한국어 고정 (SOP, 에이전트 응답, 질문 등 모두 한국어)
- **복잡도 제한**: 노드 20개 초과 시 경고 + 분할 제안 (사용자가 결정)
- **Google Forms Trigger 미지원**: n8n에 Google Forms Trigger 노드가 없으므로, 구글 폼 응답 수신이 필요한 경우 반드시 Google Sheets Trigger(새 행 추가 감지)로 대체해야 한다.

### 용어 정의

| 용어 | 정의 |
|------|------|
| SOP | Standard Operating Procedure. 워크플로우의 업무 프로세스를 단계별로 기술한 문서 |
| n8n MCP | n8n 인스턴스와 통신하는 MCP 서버. 워크플로우 CRUD, 검증, 실행 등을 제공 |
| gws 스킬 | Google Workspace(Docs, Sheets, Slides, Forms 등) 조작을 위한 Claude Code 스킬 |
| 폴백 | n8n 직접 배포가 불가능할 때 JSON 파일로 대체 출력하는 방식 |

---

## 2. 워크플로우 정의

### 전체 흐름도

```
[사용자 입력] → [Step 1: 환경 점검] → [신규/수정?]
                                        ↙         ↘
                              [신규 생성]         [기존 수정]
                                  ↓                   ↓
                    [Step 2: 요구사항 분석       [Step 2M: 기존 워크플로우
                     & SOP 생성]                 로드 & 수정 분석]
                                  ↓                   ↓
                              [Step 3: GWS 리소스 준비]
                                         ↓
                              [Step 4: 사용자 컨펌]
                                         ↓
                              [Step 5: n8n 워크플로우 생성]
                                         ↓
                                    [배포 가능?]
                                    ↙         ↘
                   [Step 6a: n8n 배포]   [Step 6b: JSON 내보내기]
```

### LLM 판단 vs 코드 처리 구분

| LLM이 직접 수행 | 스크립트/도구로 처리 |
|----------------|---------------------|
| 사용자 요구사항 분석 및 모호성 식별 | n8n MCP를 통한 워크플로우 등록/검증 |
| SOP 문서 작성 | gws CLI를 통한 Google 문서 생성 |
| 워크플로우 구조 설계 (노드 구성, 연결 로직) | JSON 스키마 검증 |
| GWS 리소스 필요 여부 판단 | 파일 시스템 쓰기 (JSON 내보내기) |
| 대안 제시 (로컬 파일 I/O 요청 시) | n8n MCP 연결 상태 확인 |

### 단계별 상세

#### Step 1: 환경 점검

- **처리 주체**: 에이전트 (CLAUDE.md)
- **입력**: 없음 (시스템 환경 자동 탐지)
- **처리 내용**:
  1. n8n MCP 설치 여부 확인: `~/.claude.json` 또는 프로젝트 `.mcp.json`에서 n8n-mcp 설정 탐색
  2. n8n MCP가 없거나 API 키 미설정 시: JSON 내보내기 모드로 전환
  3. n8n MCP가 있으면 `n8n_health_check` 호출하여 연결 상태 확인
  4. 결과를 내부 상태로 저장: `deployMode = "n8n" | "json"`
- **출력**: 배포 모드 결정 (`deployMode`)
- **성공 기준**: 배포 모드가 명확히 결정됨
- **검증 방법**: 규칙 기반 (deployMode 값 존재 여부)
- **실패 시 처리**: n8n 연결 실패 → 자동으로 JSON 모드 전환, 사용자에게 알림

#### Step 2: 요구사항 분석 & SOP 생성

- **처리 주체**: 에이전트 (CLAUDE.md)
- **입력**: 사용자의 자연어 워크플로우 설명
- **처리 내용**:
  1. 사용자 입력을 분석하여 트리거, 데이터 소스, 처리 로직, 출력/액션, 분기 조건, 에러 처리 파악
  2. 모호한 부분은 `AskUserQuestion`으로 역질문 (최대 3회, 한 번에 최대 3개)
  3. 사용자가 "알아서 해줘"라고 하면 합리적 기본값 적용 후 SOP에 명시
  4. 프로젝트 하위에 새 폴더 생성: `./workflows/<workflow-name>/`
  5. SOP 문서 작성: `./workflows/<workflow-name>/SOP.md`
- **출력**: `./workflows/<workflow-name>/SOP.md`
- **성공 기준**: SOP 문서가 생성되고 트리거, 데이터 소스, 처리 로직, 출력, 분기 조건이 모두 명시됨
- **검증 방법**: LLM 자기 검증 (SOP의 각 섹션이 비어있지 않고 논리적으로 완결되는지)
- **실패 시 처리**: 에스컬레이션 (사용자에게 추가 정보 요청)

#### Step 2M: 기존 워크플로우 수정 (수정 모드 시)

- **처리 주체**: 에이전트 (CLAUDE.md) + n8n MCP
- **입력**: 사용자의 수정 요청
- **처리 내용**:
  1. `n8n_list_workflows`로 워크플로우 목록 가져오기
  2. `AskUserQuestion`으로 수정할 워크플로우 선택
  3. `n8n_get_workflow`로 현재 JSON 로드
  4. 변경사항을 SOP에 기록
- **출력**: 수정 대상 워크플로우 JSON + 변경사항이 반영된 SOP
- **성공 기준**: 기존 워크플로우가 로드되고 수정 요구사항이 명확히 정리됨
- **검증 방법**: 규칙 기반 (워크플로우 JSON 로드 확인 + 변경사항 목록 존재)
- **실패 시 처리**: n8n MCP 불가 시 사용자에게 기존 workflow.json 파일 경로 요청

#### Step 3: GWS 리소스 준비

- **처리 주체**: 에이전트 (CLAUDE.md) + gws 스킬
- **입력**: Step 2에서 작성된 SOP 문서
- **처리 내용**:
  1. SOP를 분석하여 Google Workspace 리소스 필요 여부 판단
  2. 필요 시 사용자에게 선택지 제시: 기존 URL 제공 vs 에이전트가 직접 생성
  3. GWS 리소스가 불필요하면 이 단계를 스킵
- **출력**: GWS 리소스 URL 목록 (SOP 문서에 업데이트)
- **성공 기준**: 필요한 모든 GWS 리소스의 URL이 확보됨
- **검증 방법**: 규칙 기반 (SOP에 명시된 모든 GWS 리소스에 대응하는 URL 존재)
- **실패 시 처리**: 에스컬레이션 (gws 스킬 오류 시 사용자에게 수동 URL 제공 요청)

#### Step 4: 사용자 컨펌

- **처리 주체**: 에이전트 (CLAUDE.md)
- **입력**: 완성된 SOP 문서
- **처리 내용**: 완성된 SOP를 제시, 수정 요청 시 SOP 수정 후 재확인 (최대 3회)
- **출력**: 컨펌된 최종 SOP
- **성공 기준**: 사용자가 SOP를 명시적으로 승인
- **검증 방법**: 사람 검토
- **실패 시 처리**: 사용자 피드백 반영 후 재제시

#### Step 5: n8n 워크플로우 생성

- **처리 주체**: 에이전트 (CLAUDE.md) + n8n MCP/스킬
- **입력**: 컨펌된 SOP, 배포 모드(`deployMode`)
- **처리 내용**:
  1. `n8n-workflow-patterns` 스킬로 적합한 아키텍처 패턴 선택
  2. 필요한 노드 유형 결정 및 파라미터 설정
  3. 복잡도 체크: 노드 20개 초과 시 분할 제안
  4. `deployMode`에 따라 Step 6a 또는 Step 6b로 분기
- **출력**: n8n 워크플로우 JSON 구조 (메모리 내)
- **성공 기준**: 유효한 n8n 워크플로우 JSON이 구성됨
- **검증 방법**: `n8n_validate_workflow` → `n8n_autofix_workflow` (MCP 가용 시) / `validate_workflow` + `validate_node` (JSON 모드)
- **실패 시 처리**: 검증 실패 → 자동 재시도 (최대 3회)

#### Step 6a: n8n 배포 (deployMode = "n8n")

- **처리 주체**: 에이전트 + n8n MCP
- **입력**: 검증된 워크플로우 JSON
- **처리 내용**: `n8n_create_workflow`로 등록 (수정 시 `n8n_update_full_workflow`)
- **출력**: n8n 인스턴스에 등록된 워크플로우 + 최종 요약
- **성공 기준**: 워크플로우가 정상 등록되고 워크플로우 ID가 반환됨
- **검증 방법**: 규칙 기반 (n8n API 응답의 워크플로우 ID 존재)
- **실패 시 처리**: Step 6b로 폴백

#### Step 6b: JSON 내보내기 (deployMode = "json" 또는 6a 실패 시)

- **처리 주체**: 에이전트
- **입력**: 워크플로우 JSON 구조
- **처리 내용**: n8n import 호환 JSON 파일 생성, 저장 경로: `./workflows/<workflow-name>/workflow.json`
- **출력**: `./workflows/<workflow-name>/workflow.json` + 최종 요약
- **성공 기준**: 유효한 n8n 워크플로우 JSON 파일이 생성됨
- **검증 방법**: 스키마 검증 (n8n 워크플로우 JSON 필수 필드 존재)
- **실패 시 처리**: 자동 재시도 (최대 2회)

### 상태 전이

| 상태 | 전이 조건 | 다음 상태 |
|------|----------|----------|
| 시작 | 사용자가 `/n8n-workflow` 호출 | 환경 점검 |
| 환경 점검 | MCP 확인 완료 + 신규 요청 | 요구사항 분석 |
| 환경 점검 | MCP 확인 완료 + 수정 요청 | 기존 워크플로우 수정 |
| 요구사항 분석 | SOP 완성 | GWS 리소스 준비 |
| 기존 워크플로우 수정 | 로드 + 변경사항 정리 완료 | GWS 리소스 준비 |
| GWS 리소스 준비 | 모든 리소스 URL 확보 (또는 불필요) | 사용자 컨펌 |
| 사용자 컨펌 | 승인 | n8n 워크플로우 생성 |
| 사용자 컨펌 | 수정 요청 | 요구사항 분석 (SOP 수정) |
| n8n 워크플로우 생성 | JSON 유효 + deployMode="n8n" | n8n 배포 |
| n8n 워크플로우 생성 | JSON 유효 + deployMode="json" | JSON 내보내기 |
| n8n 배포 | 성공 | 완료 |
| n8n 배포 | 실패 | JSON 내보내기 (폴백) |
| JSON 내보내기 | 파일 생성 완료 | 완료 |

---

## 3. 구현 스펙

### 폴더 구조

```
/n8n-workflow
  ├── CLAUDE.md
  ├── /.claude
  │   └── /skills
  │       └── /n8n-workflow-designer
  │           ├── SKILL.md
  │           └── /references
  │               ├── sop-template.md
  │               └── constraints.md
  ├── /workflows
  │   └── /<workflow-name>
  │       ├── SOP.md
  │       └── workflow.json      # (JSON 모드 시)
  └── /docs
```

### CLAUDE.md 핵심 섹션 목록

- **프로젝트 개요**: n8n 워크플로우 디자이너 에이전트의 역할 정의
- **외부 의존성**: n8n MCP, n8n 스킬, gws 스킬의 역할과 호출 조건
- **제약조건**: Execute Command 노드 금지, 로컬 파일 I/O 금지, 폴백 규칙
- **워크플로우 절차**: 6단계 워크플로우 요약 (상세는 SKILL.md에 위임)

### 에이전트 구조

**구조 선택**: 단일 에이전트

**선택 근거**: 워크플로우가 순차적이며 각 단계가 이전 단계의 결과에 의존한다. 역할 분리보다 일관된 맥락 유지가 더 중요하다. n8n MCP와 gws 스킬은 외부 도구로 호출하므로 별도 서브에이전트가 불필요하다.

#### 메인 에이전트 (CLAUDE.md)
- **역할**: 전체 워크플로우 오케스트레이션 (Step 1~6 전체 담당)

### 스킬/스크립트 목록

| 이름 | 유형 | 역할 | 트리거 조건 |
|------|------|------|-----------|
| `n8n-workflow-designer` | 스킬 | 워크플로우 설계 전체 프로세스 | 사용자가 `/n8n-workflow` 호출 |
| `n8n-mcp-tools-expert` | 외부 스킬 | n8n MCP 도구 사용 마스터 가이드 | Step 5~6 시작 시 |
| `n8n-workflow-patterns` | 외부 스킬 | 5가지 아키텍처 패턴 제공 | Step 5 워크플로우 구조 설계 시 |
| `n8n-node-configuration` | 외부 스킬 | 노드별 필수 필드 가이드 | Step 5 노드 파라미터 설정 시 |
| `n8n-validation-expert` | 외부 스킬 | 검증 에러 해석 | Step 5 검증 루프 에러 발생 시 |
| `gws-docs` / `gws-sheets` / `gws-slides` / `gws-forms` | 외부 스킬 | Google Workspace 리소스 생성 | Step 3 GWS 연동 시 |

### 스킬 생성 규칙

이 설계서에 정의된 모든 스킬은 구현 시 반드시 `skill-creator` 스킬(`/skill-creator`)을 사용하여 생성할 것.
직접 SKILL.md를 수동 작성하지 말 것 — 규격 불일치 및 트리거 실패의 원인이 됨.

### 주요 산출물 파일

| 파일 | 형식 | 생성 단계 | 용도 |
|------|------|----------|------|
| `./workflows/<name>/SOP.md` | Markdown | Step 2 | 워크플로우 업무 프로세스 상세 기술 |
| `./workflows/<name>/workflow.json` | JSON | Step 6b | n8n 수동 임포트용 파일 (JSON 모드 시) |

---

## 4. 핵심 설계 결정 사항

> 이 섹션은 템플릿에 없는 추가 섹션이다. 복잡한 설계에서 의사결정 근거를 남겨야 할 때 자유롭게 추가한다.

### 4.1 환경 적응형 배포 전략

n8n MCP의 가용 여부에 따라 배포 경로가 자동 결정된다:
- MCP 사용 가능: 직접 배포 → 실패 시 JSON 폴백
- MCP 사용 불가: 처음부터 JSON 내보내기 모드

이를 통해 n8n MCP가 없는 환경에서도 에이전트가 유용하게 동작한다.

### 4.2 금지 패턴과 대안 매핑

| 금지 패턴 | 대안 |
|-----------|------|
| Execute Command 노드 | Code 노드 (JavaScript/Python) |
| 로컬 파일 읽기 | Google Drive 다운로드, HTTP Request |
| 로컬 파일 쓰기 | Google Drive 업로드, Google Sheets |
| Google Forms Trigger | Google Sheets Trigger (폼 응답 연결 시트 새 행 감지) |

### 4.3 GWS 리소스 판단 기준

| 감지 패턴 | 제안 GWS 리소스 |
|-----------|----------------|
| 데이터 수집/설문 | Google Forms + Sheets |
| 데이터 저장/집계 | Google Sheets |
| 보고서/문서 생성 | Google Docs |
| 파일 저장/공유 | Google Drive |
