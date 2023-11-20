"""
Interface to Isagog KG service
"""

import logging
from typing import Type, TypeVar, Any

import requests

from isagog.model.kg_query import UnarySelectQuery, UnionClause, AtomClause, Comparison, Value
from isagog.model.kg_model import Individual, Entity, Assertion, Ontology, Attribute, Concept, Relation

log = logging.getLogger("isagog-cli")

E = TypeVar('E', bound='Entity')


class KnowledgeBase(object):
    """
    Interface to knowledge base service
    """

    def __init__(self,
                 route: str,
                 ontology: Ontology = None,
                 dataset: str = None,
                 version: str = "latest"):
        """

        :param route: the service's endpoint route
        :param ontology: the kb ontology
        :param dataset: the dataset name; if None, uses the service's default
        :param version: the service's version identifier
        """
        assert route
        self.route = route
        self.dataset = dataset
        self.ontology = ontology
        self.version = version

    def fetch_entity(self,
                     _id: str,
                     expand: bool = False,
                     preview: bool = False,
                     entity_type: Type[E] = Entity
                     ) -> E | None:
        """
        Gets all individual entity data from the kg

        :param _id: the entity identifier
        :param preview:
        :param expand:
        :param entity_type: the entity type (default: Entity)
        """

        assert _id

        if not issubclass(entity_type, Entity):
            raise ValueError(f"{entity_type} not an Entity")

        expand = "true" if expand else "false"

        preview = "true" if (preview and expand == "false") else "false"

        params = f"id={_id}&expand={expand}&preview={preview}"

        if self.dataset:
            params += f"&dataset={self.dataset}"

        res = requests.get(
            url=self.route,
            params=params,
            headers={"Accept": "application/json"},
        )
        if res.ok:
            log.debug("Fetched %s", _id)
            return entity_type(_id, **res.json())
        else:
            log.error("Couldn't fetch %s due to %s", _id, res.reason)
            return None

    def query_assertions(self,
                         subject: Individual,
                         properties: list[Attribute | Relation]
                         ) -> list[Assertion]:
        """
        Returns entity properties, if any

        :param subject:
        :param properties: the queried properties
        :return: a list of dictionaries { property: values }
        """
        assert (subject and properties)

        query = UnarySelectQuery(subject=subject)

        for prop in properties:
            query.add_fetch_clause(predicate=str(prop))

        res = requests.post(
            url=self.route,
            json=query.to_dict(self.version),
            headers={"Accept": "application/json"},
            timeout=30
        )

        if res.ok:
            res_list = res.json()
            if len(res_list) == 0:
                log.warning("Void attribute query")
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
            log.warning("Query of entity %s failed due to %s", subject, res.reason)
            return []

    def search_individuals(self,
                           kinds: list[Concept] = None,
                           search_values: dict[Attribute, Value] = None,
                           ) -> list[Individual]:
        """
        Retrieves individuals by string search
        :param kinds:
        :param search_values:
        :return:
        """
        assert (kinds or (search_values and len(search_values) > 0))
        entities = []
        query = UnarySelectQuery()
        if kinds:
            query.add_kinds(kinds)
        if len(search_values) == 1:
            attribute, value = next(iter(search_values.items()))
            search_clause = AtomClause(property=attribute, argument=value, method=Comparison.REGEX)
        else:
            search_clause = UnionClause()
            for attribute, value in search_values.items():
                search_clause.add_clause(property=attribute, argument=value, method=Comparison.REGEX)

        query.add(search_clause)

        res = requests.post(
            url=self.route,
            json=query.to_dict(self.version),
            headers={"Accept": "application/json"},
            timeout=30
        )

        if res.ok:
            entities.extend([Individual(r.get('id'), **r) for r in res.json()])
        else:
            log.error("Search individuals failed: code %d, reason %s", res.status_code, res.reason)

        return entities

    def query_individual(self,
                         query: UnarySelectQuery,
                         kind: Type[E] = Individual,
                         ) -> list[E]:

        req = query.to_dict(self.version)

        if self.dataset and (self.version == "latest" or self.version > "v1.0.0"):
            req['dataset'] = self.dataset

        res = requests.post(
            url=self.route,
            json=req,
            headers={"Accept": "application/json"},
            timeout=30
        )

        if res.ok:
            return [kind(r.get('id'), **r) for r in res.json()]
        else:
            log.error("Search individuals failed: code %d, reason %s", res.status_code, res.reason)
            return []
