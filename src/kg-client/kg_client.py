"""

Interface to Isagog KG service

"""

import logging

import requests
import os

from typing import Type, TypeVar


from kg_model import Individual


graph_endpoint = os.environ.get("ISAGOG_AI_KG_ROUTE", "https://ai.isagog.com/api/kg/graph")
log = logging.getLogger("isagog-cli")

E = TypeVar('E', bound='Entity')


def fetch_entity(id: str,
                 entity_type: Type[E] = Individual,
                 limit=1024) -> E | None:
    """
    Gets all individual entity data from the kg
    :param id: the entity identifier
    :param entity_type: the entity type
    :param limit: limit
    """
    if id is None:
        raise ValueError("Can't fetch None")

    if not issubclass(entity_type, Individual):
        raise ValueError(f"{entity_type} not an Entity")

    res = requests.get(
        url=graph_endpoint,
        params=f"id={id}&expand=true&limit={str(limit)}",
        headers={"Accept": "application/json"},
    )
    if res.ok:
        log.debug("Fetched %s", id)
        return entity_type(res.json())
    else:
        log.error("Couldn't fetch %s due to %s", id, res.reason)
        return None


def query_entity(id: str,
                 properties: list[str],
                 ) -> list[dict]:
    """
    Returns entity properties
    :param id:
    :param properties:
    :return:
    """
    if id is None:
        raise ValueError("Can't fetch None")

    if len(properties) == 0:
        raise ValueError("Void entity query")

    req = {
        "subject": id,
        "clauses": [{"property": prop, "project": True} for prop in properties]
    }

    res = requests.post(
        url=graph_endpoint,
        json=req,
        headers={"Accept": "application/json"},
        timeout=30
    )

    if res.ok:
        res_list = res.json()
        if len(res_list) == 0:
            log.error("void entity query")
            return None
        else:
            res_attrib_list = res_list[0].get('attributes', OSError("malformed response"))

            def __get_attrib(prop: str) -> str:
                try:
                    record = next(item for item in res_attrib_list if item['id'] == prop)
                    return record.get('values', OSError("malformed response"))
                except StopIteration:
                    raise OSError("incomplete response: %s not found", prop)

            return [{prop: __get_attrib(f"<{prop}>")} for prop in properties]
    else:
        log.error("query of entity %s failed due to %s", id, res.reason)
        return None


def search_named_entities(references: dict[str, str]) -> list[Individual]:
    """
    Retrieves named entities
    :param references: a dictionary of "name" (key) : "type", where type is one of PER, LOC, ORG
    :return:
    """
    entities = []
    for name, kind in references.items():
        req = {
            "kinds": [kind],
            "clauses": [
                {
                    "property": "http://www.w3.org/2000/01/rdf-schema#label",
                    "value": name,
                    "method": "regex"
                }
            ]
        }
        res = requests.post(
            url=graph_endpoint,
            json=req,
            headers={"Accept": "application/json"},
            timeout=30
        )

        if res.ok:
            entities.extend([Individual(r) for r in res.json()])

    return entities


