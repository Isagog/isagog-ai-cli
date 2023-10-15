"""

Interface to Isagog KG service

"""

import logging

import requests
import os

from typing import Type, TypeVar

from rdflib import RDFS

from kg_model import Individual, Entity, Assertion

log = logging.getLogger("isagog-cli")

E = TypeVar('E', bound='Entity')


class KnowledgeBase(object):
    """
    A KG proxy
    """

    def __init__(self, route: str, dataset: str = None):
        """

        :param route: the service's endpoint route
        :param dataset: the dataset name
        """
        assert route
        self.route = route
        self.dataset = dataset

    def fetch_entity(self,
                     id: str,
                     entity_type: Type[E] = Entity,
                     limit=None) -> E | None:
        """
        Gets all individual entity data from the kg

        :param id: the entity identifier
        :param entity_type: the entity type (default: Entity)
        :param limit: limit of the number of assertions fetched (default: no limit)
        """

        assert id

        if not issubclass(entity_type, Entity):
            raise ValueError(f"{entity_type} not an Entity")

        params = f"id={id}&expand=true"
        if self.dataset:
            params += f"&dataset={self.dataset}"

        if limit:
            params += f"&limit={str(limit)}"

        res = requests.get(
            url=self.route,
            params=params,
            headers={"Accept": "application/json"},
        )
        if res.ok:
            log.debug("Fetched %s", id)
            return entity_type(res.json())
        else:
            log.error("Couldn't fetch %s due to %s", id, res.reason)
            return None

    def query_assertions(self,
                         subject_id: str,
                         properties: list[str],
                         dataset: str = None,
                         ) -> list[Assertion]:  # todo: why is this a list and not a dict?
        """
        Returns entity properties

        :param subject_id:
        :param dataset: the dataset to fetch
        :param properties: the queried properties
        :return: a list of dictionaries { property: values }
        """
        assert (subject_id and properties)

        req = {
            "subject": subject_id,
            "clauses": [{
                         "property": str(prop),
                         "optional": True,
                         "project": True
                        } for prop in properties]
            }

        if dataset:
            req["dataset"] = dataset

        res = requests.post(
            url=self.route,
            json=req,
            headers={"Accept": "application/json"},
            timeout=30
        )

        if res.ok:
            res_list = res.json()
            if len(res_list) == 0:
                log.warning("void attribute query")
                return []
            else:
                res_attrib_list = res_list[0].get('attributes', OSError("malformed response"))

                def __get_values(prop: str) -> str:
                    try:
                        record = next(item for item in res_attrib_list if item['id'] == prop)
                        return record.get('values', OSError("malformed response"))
                    except StopIteration:
                        raise OSError("incomplete response: %s not found", prop)

                return [Assertion(predicate=prop, values=__get_values(f"<{prop}>")) for prop in properties]
        else:
            log.warning("query of entity %s failed due to %s", subject_id, res.reason)
            return []

    def search_named_individuals(self,
                                 references: dict[str, str],
                                 dataset: str = None) -> list[Individual]:
        """
        Retrieves named entities
        :param dataset:
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

            if dataset:
                req["dataset"] = dataset

            res = requests.post(
                url=self.route,
                json=req,
                headers={"Accept": "application/json"},
                timeout=30
            )

            if res.ok:
                entities.extend([Individual(r) for r in res.json()])

        return entities
