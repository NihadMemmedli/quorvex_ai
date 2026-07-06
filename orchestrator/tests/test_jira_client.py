from __future__ import annotations

import base64

import httpx
import pytest

from orchestrator.services.jira_client import JiraClient, summarize_jira_response


def test_jira_client_defaults_to_cloud_basic_auth_header():
    client = JiraClient(
        base_url="https://company.atlassian.net",
        email="user@example.com",
        api_token="cloud-token",
    )

    encoded = base64.b64encode(b"user@example.com:cloud-token").decode()
    assert client._auth_header == f"Basic {encoded}"


def test_jira_client_uses_bearer_auth_for_data_center_pat():
    client = JiraClient(
        base_url="https://jira.company.local",
        email="",
        api_token="data-center-token",
        auth_mode="data_center_pat",
    )

    assert client._auth_header == "Bearer data-center-token"


def test_jira_client_unknown_auth_mode_falls_back_to_cloud_basic():
    client = JiraClient(
        base_url="https://company.atlassian.net",
        email="user@example.com",
        api_token="cloud-token",
        auth_mode="unknown",
    )

    encoded = base64.b64encode(b"user@example.com:cloud-token").decode()
    assert client._auth_header == f"Basic {encoded}"


def test_summarize_jira_html_error_extracts_title_and_reference():
    body = """
    <html>
      <head><title>JIRA &mdash; Internal Server Error</title></head>
      <body>
        <p>Error reference: c8684536-131e-4326-84ff-4313304ded50</p>
      </body>
    </html>
    """

    assert summarize_jira_response(500, body, "text/html") == (
        "Jira API 500: JIRA &mdash; Internal Server Error "
        "(error reference: c8684536-131e-4326-84ff-4313304ded50)"
    )


def test_summarize_jira_text_error_compacts_long_body():
    body = "bad\n\nrequest " + ("x" * 700)

    message = summarize_jira_response(400, body, "text/plain")

    assert message.startswith("Jira API 400: bad request ")
    assert len(message) < 530


@pytest.mark.asyncio
async def test_jira_client_retries_basic_401_with_bearer_pat():
    seen_auth_headers: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization", ""))
        if len(seen_auth_headers) == 1:
            return httpx.Response(401, text="<html><title>Unauthorized (401)</title></html>")
        return httpx.Response(200, json={"displayName": "Data Center User"})

    client = JiraClient(
        base_url="https://jira.company.local",
        email="user@example.com",
        api_token="data-center-token",
    )
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Authorization": client._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        result = await client.test_connection()
    finally:
        await client.close()

    encoded = base64.b64encode(b"user@example.com:data-center-token").decode()
    assert seen_auth_headers == [f"Basic {encoded}", "Bearer data-center-token"]
    assert result == {"displayName": "Data Center User"}
    assert client.auth_mode == "data_center_pat"
    assert client.used_bearer_fallback is True


@pytest.mark.asyncio
async def test_jira_client_does_not_open_circuit_for_repeated_401s():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="<html><title>Unauthorized (401)</title></html>")

    client = JiraClient(
        base_url="https://jira.company.local",
        email="user@example.com",
        api_token="bad-token",
    )
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Authorization": client._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        for _ in range(6):
            with pytest.raises(Exception) as exc_info:
                await client.test_connection()
            assert "Circuit" not in str(exc_info.value)
            assert "Jira API 401" in str(exc_info.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_jira_client_retries_basic_html_500_with_bearer_pat():
    seen_auth_headers: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization", ""))
        if len(seen_auth_headers) == 1:
            return httpx.Response(
                500,
                text="<html><head><title>JIRA &mdash; Internal Server Error</title></head></html>",
                headers={"Content-Type": "text/html;charset=UTF-8"},
            )
        return httpx.Response(200, json={"displayName": "Data Center User"})

    client = JiraClient(
        base_url="https://jira.company.local",
        email="user@example.com",
        api_token="data-center-token",
    )
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Authorization": client._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        result = await client.test_connection()
    finally:
        await client.close()

    assert seen_auth_headers[1] == "Bearer data-center-token"
    assert result == {"displayName": "Data Center User"}
    assert client.auth_mode == "data_center_pat"
