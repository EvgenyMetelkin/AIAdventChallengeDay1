"""
Tests for Agent class with User integration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agent import Agent
from user import User
import httpx


@pytest.fixture
def mock_user():
    """Create a mock User with agents and history."""
    user = User(
        user_id="test_user_001",
        name="Test User",
        preferences={"STYLE": "formal", "CONSTRAINTS": "", "CONTEXT": ""},
        working_memory=[],
        agents={
            "agent001": {
                "name": "default",
                "created": "2024-01-01",
                "history": []
            }
        },
        current_agent_id="agent001"
    )
    # Mock save methods to avoid filesystem access
    user.save_agents = MagicMock()
    user.save_working_memory = MagicMock()
    user.save_preferences = MagicMock()
    return user


@pytest.fixture
def agent_with_user(mock_user):
    """Create an Agent with a mock User."""
    return Agent(
        api_key="test_key",
        base_url="https://fake.api",
        verbose=False,
        user=mock_user
    )


class TestAgentSendMessage:
    """Tests for Agent.send_message()."""

    @pytest.mark.asyncio
    async def test_send_message_success(self, agent_with_user):
        """Successful message send with valid response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello, human!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            response = await agent_with_user.send_message("Hi")
            assert response == "Hello, human!"
            # Check history was updated
            history = agent_with_user.user.get_current_history()
            assert len(history) >= 2
            assert history[-2]["role"] == "user"
            assert history[-2]["content"] == "Hi"
            assert history[-1]["role"] == "assistant"
            assert history[-1]["content"] == "Hello, human!"

    @pytest.mark.asyncio
    async def test_send_message_http_error(self, agent_with_user):
        """HTTP error handling."""
        error_response = MagicMock()
        error_response.json.return_value = {"error": {"message": "Invalid API key"}}
        error_response.status_code = 401

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=AsyncMock(), response=error_response
            )
            with pytest.raises(Exception, match="HTTP error 401: Invalid API key"):
                await agent_with_user.send_message("Hi")

    @pytest.mark.asyncio
    async def test_send_message_timeout(self, agent_with_user):
        """Timeout error handling."""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")
            with pytest.raises(Exception, match="timed out"):
                await agent_with_user.send_message("Hi")

    @pytest.mark.asyncio
    async def test_send_message_network_error(self, agent_with_user):
        """Network error handling."""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.RequestError("Connection refused")
            with pytest.raises(Exception, match="Network error"):
                await agent_with_user.send_message("Hi")

    @pytest.mark.asyncio
    async def test_send_message_no_user(self):
        """Agent without user should raise exception."""
        agent = Agent(api_key="test_key")
        with pytest.raises(Exception, match="No user selected"):
            await agent.send_message("Hi")

    @pytest.mark.asyncio
    async def test_send_message_system_prompt(self, agent_with_user):
        """System prompt from preferences is included."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = mock_response
            await agent_with_user.send_message("Hi")
            
            # Check that system prompt was in the request
            call_args = mock_post.call_args
            payload = call_args[1]["json"]
            messages = payload["messages"]
            assert messages[0]["role"] == "system"
            assert "STYLE" in messages[0]["content"]


class TestAgentStreaming:
    """Tests for Agent.send_message_stream()."""

    @pytest.mark.asyncio
    async def test_stream_success(self, agent_with_user):
        """Streaming tokens are yielded correctly."""
        # Simulate streaming response lines
        stream_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
            'data: {"choices":[{"delta":{"content":", "}}]}\n',
            'data: {"choices":[{"delta":{"content":"world!"}}]}\n',
            'data: [DONE]\n',
        ]

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=AsyncMock())

        async def _aiter_lines():
            for line in stream_lines:
                yield line
        mock_response.aiter_lines.side_effect = _aiter_lines

        mock_client = AsyncMock()
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            tokens = []
            async for token in agent_with_user.send_message_stream("Hi"):
                tokens.append(token)

            assert tokens == ["Hello", ", ", "world!"]

    @pytest.mark.asyncio
    async def test_stream_no_user(self):
        """Streaming without user raises exception."""
        agent = Agent(api_key="test_key")
        with pytest.raises(Exception, match="No user selected"):
            async for _ in agent.send_message_stream("Hi"):
                pass


class TestAgentResetConversation:
    """Tests for Agent.reset_conversation()."""

    def test_reset_conversation(self, agent_with_user):
        """Reset clears history and saves."""
        agent_with_user.user.agents[agent_with_user.user.current_agent_id]['history'] = [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": "response"}
        ]
        agent_with_user.reset_conversation()
        history = agent_with_user.user.get_current_history()
        assert history == []
        agent_with_user.user.save_agents.assert_called()

    def test_reset_no_user(self):
        """Reset without user raises exception."""
        agent = Agent(api_key="test_key")
        with pytest.raises(Exception, match="No user selected"):
            agent.reset_conversation()


class TestAgentSendWithoutHistory:
    """Tests for Agent.send_message_without_history()."""

    @pytest.mark.asyncio
    async def test_send_without_history(self, agent_with_user):
        """Message sent without affecting conversation history."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Summary"}}],
            "usage": {}
        }
        mock_response.raise_for_status = MagicMock()

        # Add some history first
        agent_with_user.user.agents["agent001"]["history"] = [
            {"role": "user", "content": "old msg"},
            {"role": "assistant", "content": "old reply"}
        ]

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            response = await agent_with_user.send_message_without_history("Make summary")
            assert response == "Summary"
            # History should NOT include the new message
            history = agent_with_user.user.get_current_history()
            assert len(history) == 2  # unchanged


class TestAgentInfo:
    """Tests for Agent.get_agent_info()."""

    def test_get_agent_info(self, agent_with_user):
        """Agent info returns correct structure."""
        info = agent_with_user.get_agent_info()
        assert info["agent_id"] is not None
        assert info["model"] == "gpt-3.5-turbo"  # default
        assert info["user"] is not None
        assert info["has_user"] is True


class TestUserMethods:
    """Tests for User class methods."""

    def test_get_system_prompt(self, mock_user):
        """System prompt is generated from preferences."""
        prompt = mock_user.get_system_prompt()
        assert "# System Instructions" in prompt
        assert "## STYLE" in prompt
        assert "formal" in prompt

    def test_get_system_prompt_empty(self):
        """Empty preferences produce empty prompt."""
        user = User(
            user_id="test",
            name="Test",
            preferences={"STYLE": "", "CONSTRAINTS": "", "CONTEXT": ""},
            agents={"a1": {"name": "d", "created": "", "history": []}},
            current_agent_id="a1"
        )
        assert user.get_system_prompt() == ""

    def test_add_agent(self, mock_user):
        """Adding an agent creates a new entry."""
        mock_user.save_agents.reset_mock()
        new_id = mock_user.add_agent("test_agent")
        assert new_id in mock_user.agents
        assert mock_user.agents[new_id]["name"] == "test_agent"
        assert mock_user.agents[new_id]["history"] == []
        mock_user.save_agents.assert_called()

    def test_delete_agent_last(self, mock_user):
        """Cannot delete the last agent."""
        # Only one agent exists
        assert len(mock_user.agents) == 1
        agent_id = list(mock_user.agents.keys())[0]
        result = mock_user.delete_agent(agent_id)
        assert result is False

    def test_delete_agent_switch(self, mock_user):
        """Deleting current agent switches to another."""
        mock_user.add_agent("second")
        mock_user.current_agent_id = list(mock_user.agents.keys())[0]
        first_id = mock_user.current_agent_id
        second_id = [k for k in mock_user.agents.keys() if k != first_id][0]
        
        result = mock_user.delete_agent(first_id)
        assert result is True
        assert mock_user.current_agent_id == second_id
        assert first_id not in mock_user.agents

    def test_reset_current_history(self, mock_user):
        """Reset clears history for current agent."""
        mock_user.agents[mock_user.current_agent_id]["history"] = [
            {"role": "user", "content": "test"}
        ]
        mock_user.reset_current_history()
        assert mock_user.get_current_history() == []

    def test_to_dict(self, mock_user):
        """to_dict returns correct structure."""
        d = mock_user.to_dict()
        assert d["user_id"] == "test_user_001"
        assert d["name"] == "Test User"
        assert "agents" in d
        assert "current_agent_id" in d
        assert d["current_agent_id"] == "agent001"
