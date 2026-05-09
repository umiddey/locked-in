from __future__ import annotations

import logging
import re
from datetime import date

from notion_client import Client
from notion_client.errors import APIResponseError

from .config import NotionConfig
from .models import NormalizedTask

log = logging.getLogger(__name__)


def _normalize_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _resolve_query_target(client: Client, source_id: str) -> tuple[str, str]:
    """Return ('database'|'data_source', id) for the configured Notion object."""
    if hasattr(client.databases, "query"):
        return ("database", source_id)

    try:
        client.data_sources.retrieve(source_id)
        return ("data_source", source_id)
    except APIResponseError:
        pass

    database = client.databases.retrieve(source_id)

    initial_data_source = database.get("initial_data_source")
    if isinstance(initial_data_source, dict) and initial_data_source.get("id"):
        return ("data_source", initial_data_source["id"])

    data_sources = database.get("data_sources")
    if isinstance(data_sources, list) and data_sources:
        first = data_sources[0]
        if isinstance(first, dict) and first.get("id"):
            return ("data_source", first["id"])

    raise RuntimeError(
        "Could not resolve a queryable Notion data source from the configured tasks_database_id"
    )


def _build_property_filter(config: NotionConfig) -> dict | None:
    filters: list[dict] = []

    if config.status_property and config.select_statuses:
        filters.append(
            {
                "or": [
                    {"property": config.status_property, "status": {"equals": value}}
                    for value in config.select_statuses
                ]
            }
        )

    if config.select_property and config.select_values:
        filters.append(
            {
                "or": [
                    {"property": config.select_property, "select": {"equals": value}}
                    for value in config.select_values
                ]
            }
        )

    if config.multi_select_property and config.multi_select_values:
        filters.append(
            {
                "or": [
                    {
                        "property": config.multi_select_property,
                        "multi_select": {"contains": value},
                    }
                    for value in config.multi_select_values
                ]
            }
        )

    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"and": filters}


def fetch_tasks(config: NotionConfig) -> list[NormalizedTask]:
    """Fetch and normalize tasks from Notion."""
    client = Client(auth=config.token)
    tasks: list[NormalizedTask] = []
    today = date.today().isoformat()
    cursor = None
    query_kind, query_id = _resolve_query_target(client, config.tasks_database_id)

    date_filter = {
        "or": [
            {
                "property": config.date_property,
                "date": {"equals": today},
            },
        ]
    }
    if config.include_no_date:
        date_filter["or"].append(
            {
                "property": config.date_property,
                "date": {"is_empty": True},
            }
        )

    filter_parts = [date_filter]
    property_filter = _build_property_filter(config)
    if property_filter is not None:
        filter_parts.insert(0, property_filter)
    filter_obj = {"and": filter_parts}

    while True:
        if query_kind == "database":
            resp = client.databases.query(
                database_id=query_id,
                filter=filter_obj,
                start_cursor=cursor,
            )
        else:
            resp = client.data_sources.query(
                data_source_id=query_id,
                filter=filter_obj,
                start_cursor=cursor,
            )

        for page in resp.get("results", []):
            props = page.get("properties", {})

            title_prop = props.get(config.title_property, {})
            title = ""
            if title_prop.get("title"):
                title = "".join(
                    rt.get("plain_text", "") for rt in title_prop["title"]
                )

            if not title:
                continue

            due_date = None
            date_prop = props.get(config.date_property, {})
            if date_prop.get("date") and date_prop["date"].get("start"):
                due_date = date_prop["date"]["start"][:10]

            estimate = 30
            est_prop = props.get(config.estimate_property, {})
            if est_prop.get("number") is not None:
                estimate = int(est_prop["number"])

            tasks.append(
                NormalizedTask(
                    id=page["id"],
                    title=title,
                    normalized_key=_normalize_key(title),
                    estimate_minutes=estimate,
                    due_date=due_date,
                )
            )

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    tasks.sort(key=lambda t: (t.due_date is None, t.due_date or "", t.title))
    log.info("Fetched %d tasks from Notion", len(tasks))
    return tasks
