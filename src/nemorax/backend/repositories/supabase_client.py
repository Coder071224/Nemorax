"""Minimal Supabase REST client for persistent app data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from nemorax.backend.core.errors import PersistenceError
from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import SupabaseSettings


logger = get_logger("nemorax.supabase_persistence")


FilterValue = str | int | float | bool | None


class SupabasePersistenceClient:
    def __init__(
        self,
        config: SupabaseSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self._config.configured

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        key = self._config.service_role_key or ""
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    @staticmethod
    def _filter_value(value: FilterValue, *, operator: str) -> str:
        if value is None:
            return "is.null" if operator == "eq" else f"{operator}.null"
        if isinstance(value, bool):
            encoded = "true" if value else "false"
        else:
            encoded = str(value)
        return f"{operator}.{encoded}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_payload: Any = None,
        prefer: str | None = None,
    ) -> Any:
        if not self.configured:
            raise PersistenceError("Supabase persistence is not configured.")

        base_url = self._config.url.rstrip("/")
        url = f"{base_url}{path}"
        try:
            with httpx.Client(timeout=self._config.timeout_seconds, transport=self._transport) as client:
                response = client.request(
                    method,
                    url,
                    headers=self._headers(prefer=prefer),
                    params=dict(params or {}),
                    json=json_payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or str(exc)
            logger.warning("Supabase request failed %s %s (%s)", method, path, detail)
            raise PersistenceError("Supabase persistence request failed.") from exc
        except httpx.HTTPError as exc:
            logger.warning("Supabase request transport error %s %s (%s)", method, path, exc)
            raise PersistenceError("Supabase persistence is unavailable.") from exc

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("Supabase returned non-JSON payload for %s %s", method, path)
            raise PersistenceError("Supabase returned an invalid response.") from exc

    def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Mapping[str, tuple[str, FilterValue] | FilterValue] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": columns}
        if filters:
            for column, value in filters.items():
                if isinstance(value, tuple):
                    operator, operand = value
                else:
                    operator, operand = "eq", value
                params[column] = self._filter_value(operand, operator=operator)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)

        payload = self._request("GET", f"/rest/v1/{table}", params=params)
        if payload is None:
            return []
        if not isinstance(payload, list):
            logger.warning("Supabase select returned unexpected payload for table=%s", table)
            raise PersistenceError("Supabase returned an invalid query payload.")
        return [row for row in payload if isinstance(row, dict)]

    def select_one(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Mapping[str, tuple[str, FilterValue] | FilterValue] | None = None,
        order: str | None = None,
    ) -> dict[str, Any] | None:
        rows = self.select(table, columns=columns, filters=filters, order=order, limit=1)
        return rows[0] if rows else None

    def insert(
        self,
        table: str,
        payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        returning: str = "representation",
    ) -> list[dict[str, Any]]:
        rows_payload: Any = payload
        prefer = f"return={returning}"
        raw = self._request("POST", f"/rest/v1/{table}", json_payload=rows_payload, prefer=prefer)
        if raw is None:
            return []
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        raise PersistenceError("Supabase returned an invalid insert payload.")

    def upsert(
        self,
        table: str,
        payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        on_conflict: str,
        returning: str = "representation",
    ) -> list[dict[str, Any]]:
        prefer = f"resolution=merge-duplicates,return={returning}"
        raw = self._request(
            "POST",
            f"/rest/v1/{table}",
            params={"on_conflict": on_conflict},
            json_payload=payload,
            prefer=prefer,
        )
        if raw is None:
            return []
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        raise PersistenceError("Supabase returned an invalid upsert payload.")

    def update(
        self,
        table: str,
        payload: Mapping[str, Any],
        *,
        filters: Mapping[str, tuple[str, FilterValue] | FilterValue],
        returning: str = "representation",
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        for column, value in filters.items():
            if isinstance(value, tuple):
                operator, operand = value
            else:
                operator, operand = "eq", value
            params[column] = self._filter_value(operand, operator=operator)
        raw = self._request(
            "PATCH",
            f"/rest/v1/{table}",
            params=params,
            json_payload=dict(payload),
            prefer=f"return={returning}",
        )
        if raw is None:
            return []
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        raise PersistenceError("Supabase returned an invalid update payload.")

    def delete(
        self,
        table: str,
        *,
        filters: Mapping[str, tuple[str, FilterValue] | FilterValue],
        returning: str = "representation",
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        for column, value in filters.items():
            if isinstance(value, tuple):
                operator, operand = value
            else:
                operator, operand = "eq", value
            params[column] = self._filter_value(operand, operator=operator)
        raw = self._request(
            "DELETE",
            f"/rest/v1/{table}",
            params=params,
            prefer=f"return={returning}",
        )
        if raw is None:
            return []
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        raise PersistenceError("Supabase returned an invalid delete payload.")

    def rpc(self, function_name: str, payload: Mapping[str, Any]) -> Any:
        return self._request("POST", f"/rest/v1/rpc/{function_name}", json_payload=dict(payload))
