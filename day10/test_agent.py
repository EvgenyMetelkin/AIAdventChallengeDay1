import pytest
from unittest.mock import AsyncMock, patch
from agent import Agent
import httpx

@pytest.mark.asyncio
async def test_send_message_success():
    agent = Agent(api_key="test_key", base_url="https://fake.api", verbose=False)
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello, human!"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    mock_response.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        response = await agent.send_message("Hi")
        assert response == "Hello, human!"
        assert len(agent.conversation_history) == 2
        assert agent.conversation_history[0]["role"] == "user"
        assert agent.conversation_history[1]["role"] == "assistant"

@pytest.mark.asyncio
async def test_send_message_http_error():
    agent = Agent(api_key="test_key")
    error_response = AsyncMock()
    error_response.json.return_value = {"error": {"message": "Invalid API key"}}
    error_response.status_code = 401

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=AsyncMock(), response=error_response
        )
        with pytest.raises(Exception, match="HTTP error 401: Invalid API key"):
            await agent.send_message("Hi")

@pytest.mark.asyncio
async def test_reset_conversation():
    agent = Agent(api_key="test_key")
    agent.conversation_history = [{"role": "user", "content": "test"}]
    agent.reset_conversation()
    assert agent.conversation_history == []