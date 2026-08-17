"""
frontend/statements_client.py
=============================
Thin wrapper over the /statements/* backend endpoints. Same pattern as
api_client.py's ApiClient, kept as a separate small client because this
pipeline is independent of the Screener one — different session namespace,
different upload shape (one file OR several).

    from frontend.statements_client import statements_api
    session = statements_api.upload([("MeridianBank.xlsx", file_bytes)])
    review = statements_api.review(session["session_id"])
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
TIMEOUT = 120


class ApiError(Exception):
    pass


class StatementsClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = requests.request(
                method, f"{self.base_url}{path}", timeout=TIMEOUT, **kwargs)
        except requests.exceptions.ConnectionError:
            raise ApiError(
                "Cannot reach the backend. Start it with:\n\n"
                "    uvicorn backend.api.main:app --reload --port 8000"
            ) from None
        except requests.exceptions.Timeout:
            raise ApiError("The backend took too long to respond.") from None

        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("detail") or body.get("error") or response.text
            except ValueError:
                message = response.text[:200]
            raise ApiError(str(message))
        return response

    def is_up(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except ApiError:
            return False

    def formats(self) -> Dict[str, Any]:
        return self._request("GET", "/formats").json()

    def upload(self, files: List[Tuple[str, bytes]]) -> Dict[str, Any]:
        """
        files: list of (filename, raw_bytes). One entry for a workbook,
        several for a CSV set (one per statement).
        """
        payload = [("files", (name, content)) for name, content in files]
        return self._request("POST", "/upload", files=payload).json()

    def sessions(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/sessions").json()["sessions"]

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/sessions/{session_id}").json()

    def compare(self, session_a: str, session_b: str) -> Dict[str, Any]:
        return self._request("GET", "/compare",
                             params={"a": session_a, "b": session_b}).json()

    def review(self, session_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/review/{session_id}").json()

    def narrative(self, session_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/narrative/{session_id}").json()

    def wp514(self, session_id: str) -> Tuple[bytes, str]:
        response = self._request("GET", f"/wp514/{session_id}")
        disposition = response.headers.get("content-disposition", "")
        filename = "WP514.xlsx"
        if "filename=" in disposition:
            filename = disposition.split("filename=")[1].strip('"; ')
        return response.content, filename


statements_api = StatementsClient()