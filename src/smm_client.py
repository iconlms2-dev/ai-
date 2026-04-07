"""
SMMClient — SMM 패널 좋아요 자동 구매 클라이언트

SMM 패널 API를 통해 YouTube 댓글에 좋아요를 자동 구매한다.
표준 SMM 패널 API (https://smmpanel.com/api) 호환.
"""

import os
import requests
from typing import Dict, Optional, List


class SMMClient:
    """SMM 패널 API 클라이언트."""

    def __init__(self):
        self.api_key = os.getenv("SMM_API_KEY", "")
        self.api_url = os.getenv("SMM_API_URL", "https://smmpanel.com/api/v2")
        self.enabled = os.getenv("SMM_ENABLED", "false").lower() == "true"
        self.default_service_id = int(os.getenv("SMM_LIKE_SERVICE_ID", "4001"))
        self.default_quantity = int(os.getenv("SMM_LIKE_QUANTITY", "20"))

    def _request(self, action: str, **params) -> Dict:
        """SMM API에 요청을 보낸다."""
        if not self.api_key:
            return {"error": "SMM API 키가 설정되지 않았습니다."}

        payload = {
            "key": self.api_key,
            "action": action,
            **params,
        }
        try:
            resp = requests.post(self.api_url, data=payload, timeout=30)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def get_balance(self) -> Dict:
        """잔액을 조회한다."""
        return self._request("balance")

    def get_services(self) -> List[Dict]:
        """사용 가능한 서비스 목록을 조회한다."""
        result = self._request("services")
        if isinstance(result, list):
            return result
        return []

    def order_likes(
        self,
        comment_url: str,
        quantity: Optional[int] = None,
        service_id: Optional[int] = None,
    ) -> Dict:
        """댓글에 좋아요를 주문한다.

        Returns:
            {"order": order_id} 또는 {"error": message}
        """
        if not self.enabled:
            return {"error": "SMM이 비활성화되어 있습니다."}

        return self._request(
            "add",
            service=service_id or self.default_service_id,
            link=comment_url,
            quantity=quantity or self.default_quantity,
        )

    def check_order(self, order_id: str) -> Dict:
        """주문 상태를 확인한다."""
        return self._request("status", order=order_id)

    def check_orders(self, order_ids: List[str]) -> Dict:
        """여러 주문의 상태를 확인한다."""
        if not order_ids:
            return {}
        return self._request("status", orders=",".join(str(i) for i in order_ids))
