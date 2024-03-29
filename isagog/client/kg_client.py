"""
Interface to Isagog KG service
"""
import logging
import os
import time
from typing import Type, TypeVar

import requests
from dotenv import load_dotenv

from isagog.model.kg_model import Individual, Entity, Assertion, Ontology, Attribute, Concept, Relation, ID
from isagog.model.kg_query import UnarySelectQuery, DisjunctiveClause, AtomicClause, Comparison, Value

load_dotenv()

KG_DEFAULT_TIMEOUT = int(os.getenv('KG_DEFAULT_TIMEOUT', 60))

E = TypeVar('E', bound='Entity')


class KnowledgeBase(object):
    """
    Interface to knowledge base service
    """

    def __init__(self,
                 route: str,
                 ontology: Ontology = None,
                 dataset: str = None,
                 version: str = None,
                 logger=None):
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
        self.version = version if version else "latest"
        self.logger = logger if logger else logging.getLogger()
        self.logger.info("Isagog KG client (%s) initialized on route %s", hex(id(self)), route)

    def get_entity(self,
                   _id: str,
                   expand: bool = True,
                   entity_type: Type[E] = Entity
                   ) -> E | None:
        """
        Gets the entity by its identifier
        :param _id: the entity identifier
        :param expand: whether to return entity attributes
        :param entity_type: the entity type (default: Entity)
        """

        assert _id

        self.logger.debug("Fetching %s", _id)

        if not issubclass(entity_type, Entity):
            raise ValueError(f"{entity_type} not an Entity")

        expand = "true" if expand else "false"

        params = f"id={_id}&expand={expand}"

        if self.dataset:
            params += f"&dataset={self.dataset}"

        res = requests.get(
            url=self.route,
            params=params,
            headers={"Accept": "application/json"},
        )
        if res.ok:
            self.logger.debug("Fetched %s", _id)
            return entity_type(_id, **res.json())
        else:
            self.logger.error("Couldn't fetch %s due to %s", _id, res.reason)
            return None

    def query_assertions(self,
                         subject: Individual,
                         properties: list[Attribute | Relation],
                         timeout=KG_DEFAULT_TIMEOUT
                         ) -> list[Assertion]:
        """
        Returns specific entity properties

        :param timeout:
        :param subject:
        :param properties: the queried properties
        :return: a list of dictionaries { property: values }
        """
        assert (subject and properties)

        self.logger.debug("Querying assertions for %s", subject.id)

        query = UnarySelectQuery(subject=subject)

        for prop in properties:
            query.add_fetch_clause(predicate=str(prop))

        query_dict = query.to_dict(self.version)

        res = requests.post(
            url=self.route,
            json=query_dict,
            headers={"Accept": "application/json"},
            timeout=timeout
        )

        if res.ok:
            res_list = res.json()
            if len(res_list) == 0:
                self.logger.warning("Void attribute query")
                return []
            else:
                res_attrib_list = res_list[0].get('attributes', OSError("malformed response"))

                def __get_values(_prop: str) -> str:
                    try:
                        record = next(item for item in res_attrib_list if item['id'] == _prop)
                        return record.get('values', OSError("malformed response"))
                    except StopIteration:
                        raise OSError("incomplete response: %s not found", _prop)

                return [Assertion(predicate=prop, values=__get_values(prop)) for prop in properties]
        else:
            self.logger.warning("Query of entity %s failed due to %s", subject, res.reason)
            return []

    def search_individuals(self,
                           kinds: list[Concept] = None,
                           constraints: dict[Attribute, Value] = None,
                           timeout=KG_DEFAULT_TIMEOUT
                           ) -> list[Individual]:
        """
        Retrieves individuals by string search
        :param timeout: the request timeout
        :param kinds: the kinds to search for
        :param constraints: the search constraints
        :return: a list of matching individuals
        """
        assert (kinds or (constraints and len(constraints) > 0))
        self.logger.debug("Searching individuals")
        entities = []
        query = UnarySelectQuery()
        if kinds:
            query.add_kinds(kinds)
        if len(constraints) == 1:
            attribute, value = next(iter(constraints.items()))
            search_clause = AtomicClause(property=attribute, argument=value, method=Comparison.REGEX)
        else:
            search_clause = DisjunctiveClause()
            for attribute, value in constraints.items():
                search_clause.add_atom(property=attribute, argument=value, method=Comparison.REGEX)

        query.clause(search_clause)

        res = requests.post(
            url=self.route,
            json=query.to_dict(self.version),
            headers={"Accept": "application/json"},
            timeout=timeout
        )

        if res.ok:
            entities.extend([Individual(r.get('id'), **r) for r in res.json()])
        else:
            self.logger.error("Search individuals failed: code %d, reason %s", res.status_code, res.reason)

        return entities

    def query_individuals(self,
                          query: UnarySelectQuery,
                          kind: Type[E] = Individual,
                          timeout=KG_DEFAULT_TIMEOUT
                          ) -> list[E]:
        """

        :param query:
        :param kind:
        :param timeout:
        :return:
        """
        start_time = time.time()

        req = query.to_dict(self.version)

        if self.dataset and (self.version == "latest" or self.version > "v1.0.0"):
            req['dataset'] = self.dataset

        res = requests.post(
            url=self.route,
            json=req,
            headers={"Accept": "application/json"},
            timeout=timeout
        )

        if res.ok:
            self.logger.debug("Query individuals successful in %d seconds", time.time() - start_time)
            return [kind(r.get('id'), **r) for r in res.json()]
        elif res.status_code < 500:
            self.logger.warning("query individuals return code %d, reason %s", res.status_code, res.reason)
        else:
            self.logger.error("query individuals return code code %d, reason %s", res.status_code, res.reason)
        return []

    def upsert_individual(self, individual: Individual, auth_token=None) -> bool:
        """
        Updates an individual or insert it if not present; existing properties are preserved

        :param individual: the individual
        :param auth_token:
        :return:
        """
        self.logger.debug("Updating individual %s", individual.id)
        params = {
            'id': individual.id
        }

        if self.dataset and (self.version == "latest" or self.version > "v1.0.0"):
            params['dataset'] = self.dataset

        req = individual.to_dict()

        headers = {"Accept": "application/json"}

        if auth_token:
            headers["Authorization"] = f'Bearer {auth_token}'

        res = requests.patch(
            url=self.route,
            params=params,
            json=req,
            headers=headers
        )

        if res.ok:
            return True
        else:
            raise OSError(f"upsert failed {res.status_code}")

    def delete_individual(self, _id: ID, auth_key=None):
        pass
