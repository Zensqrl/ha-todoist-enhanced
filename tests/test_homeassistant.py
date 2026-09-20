"""Use real HA config entries, service schemas and authenticated WebSockets."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todoist_enhanced.api import TodoistAuthError
from custom_components.todoist_enhanced.const import DOMAIN
from custom_components.todoist_enhanced.models import TodoistProject


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_api():
    with (
        patch(
            "custom_components.todoist_enhanced.api.TodoistEnhancedApi", autospec=True
        ) as factory,
        patch("custom_components.todoist_enhanced.TodoistEnhancedApi", factory),
    ):
        api = factory.return_value
        api.validate_token = AsyncMock()
        api.get_projects = AsyncMock(return_value=[TodoistProject("p", "Home")])
        api.get_sections = AsyncMock(return_value=[])
        api.get_saved_filters = AsyncMock(return_value=[])
        api.get_labels = AsyncMock(return_value=[{"id": "l", "name": "Any label"}])
        api.get_shared_labels = AsyncMock(return_value=[])
        api.get_tasks = AsyncMock(
            return_value=[
                {
                    "id": "t",
                    "content": "Task",
                    "project_id": "p",
                    "labels": ["Any label"],
                    "priority": 4,
                }
            ]
        )
        yield api


async def setup_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"api_token": "fixture-secret"}, title="Todoist Enhanced"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_setup_service_catalog_mapping_and_unload(hass, mock_api):
    from homeassistant.helpers import entity_registry as er

    native = MockConfigEntry(domain="todoist", data={})
    native.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "todo", "todoist", f"{native.entry_id}-p", config_entry=native
    )
    entry = await setup_entry(hass)
    result = await hass.services.async_call(
        DOMAIN, "get_tasks", {}, blocking=True, return_response=True
    )
    assert result["tasks"][0]["display_priority"] == 1
    assert "fixture-secret" not in str(result)
    catalogs = await hass.services.async_call(
        DOMAIN, "get_catalogs", {}, blocking=True, return_response=True
    )
    assert catalogs["data"]["projects"][0]["native_todo_entities"] == [entity.entity_id]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]
    assert registry.async_get(entity.entity_id) is not None


async def test_websocket_roundtrip_and_schema(hass, mock_api, hass_ws_client):
    await setup_entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/tasks"})
    result = await client.receive_json()
    assert result["success"] and result["result"]["tasks"][0]["labels"] == ["Any label"]
    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/tasks", "filter": "today", "project_id": "p"}
    )
    result = await client.receive_json()
    assert not result["success"]
    await client.send_json({"id": 3, "type": f"{DOMAIN}/catalogs"})
    result = await client.receive_json()
    assert result["result"]["data"]["labels"] == [{"id": "l", "name": "Any label"}]


async def test_config_flow_invalid_token_and_success(hass, mock_api):
    mock_api.validate_token.side_effect = TodoistAuthError("Rejected")
    with patch(
        "custom_components.todoist_enhanced.config_flow.TodoistEnhancedApi",
        return_value=mock_api,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"api_token": "bad"}
        )
    assert result["errors"] == {"base": "invalid_auth"}
    mock_api.validate_token.side_effect = None
    with (
        patch(
            "custom_components.todoist_enhanced.async_setup_entry", return_value=True
        ),
        patch(
            "custom_components.todoist_enhanced.config_flow.TodoistEnhancedApi",
            return_value=mock_api,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": "valid"}
        )
    assert result["type"] == "create_entry"


async def test_auth_failure_reauth(hass, mock_api):
    mock_api.validate_token.side_effect = TodoistAuthError("Rejected")
    entry = MockConfigEntry(domain=DOMAIN, data={"api_token": "invalid"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_non_admin_service_cannot_mutate(hass, mock_api, hass_read_only_user):
    await setup_entry(hass)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "complete_task",
            {"task_id": "t"},
            context=Context(user_id=hass_read_only_user.id),
            blocking=True,
            return_response=True,
        )
    mock_api.close_task.assert_not_called()


async def test_reload_creates_fresh_runtime(hass, mock_api):
    entry = await setup_entry(hass)
    original = entry.runtime_data
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data is not original
    assert entry.state is ConfigEntryState.LOADED


async def test_service_first_failure_and_stale_cache(hass, mock_api):
    from custom_components.todoist_enhanced.api import TodoistUnavailableError

    entry = await setup_entry(hass)
    mock_api.get_tasks.side_effect = TodoistUnavailableError("Offline")
    result = await hass.services.async_call(
        DOMAIN,
        "get_tasks",
        {"force_refresh": True},
        blocking=True,
        return_response=True,
    )
    assert result["tasks"] and result["stale"] and result["outcome"] == "error"
    entry.runtime_data.backend._cache.clear()
    result = await hass.services.async_call(
        DOMAIN, "get_tasks", {}, blocking=True, return_response=True
    )
    assert result["tasks"] is None and not result["complete"]


async def test_setup_network_retry(hass, mock_api):
    from custom_components.todoist_enhanced.api import TodoistUnavailableError

    mock_api.validate_token.side_effect = TodoistUnavailableError("Offline")
    entry = MockConfigEntry(domain=DOMAIN, data={"api_token": "fixture"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
