---
description: 코드 리뷰어 에이전트로 최근 변경사항 리뷰
---

code-reviewer 에이전트를 사용하여 최근 코드 변경사항을 리뷰합니다.

1. git diff로 변경된 파일 확인 (커밋 안 된 변경사항)
2. 변경된 파일이 없으면 마지막 커밋의 diff 사용
3. .claude/agents/code-reviewer.md의 리뷰 체크리스트에 따라 Agent 도구로 code-reviewer 에이전트를 호출하여 리뷰 수행
4. 리뷰 결과를 사용자에게 보고
5. "수정 필요" 판정이면 수정할지 사용자에게 확인
