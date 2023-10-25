"""

Interface to Isagog KG service

"""

import logging
from typing import Type, TypeVar

import requests

from isagog.model.kb_query import UnarySelectQuery, UnionClause
from isagog.model.kg_model import Individual, Entity, Assertion, Ontology, Attribute

#from kg-client import UnarySelectQuery, UnionClause
#from kg_model import Individual, Entity, Assertion, Ontology, Attribute

log = logging.getLogger("isagog-cli")

E = TypeVar('E', bound='Entity')


class KnowledgeBase(object):
    """
    A KG proxy
    """

    def __init__(self,
                 route: str,
                 ontology: Ontology = None,
                 dataset: str = None):
        """

        :param route: the service's endpoint route
        :param dataset: the dataset name; if None, uses the service's default
        """
        assert route
        self.route = route
        self.dataset = dataset

    def fetch_entity(self,
                     id: str,
                     entity_type: Type[E] = Entity
                     ) -> E | None:
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
                         properties: list[str]
                         ) -> list[Assertion]:  # todo: why is this a list and not a dict?
        """
        Returns entity properties

        :param subject_id:
        :param dataset: the dataset to fetch
        :param properties: the queried properties
        :return: a list of dictionaries { property: values }
        """
        assert (subject_id and properties)

        # req = {
        #     "subject": subject_id,
        #     "clauses": [{
        #         "property": str(prop),
        #         "optional": True,
        #         "project": True
        #     } for prop in properties]
        # }
        #
        # if self.dataset:
        #     req["dataset"] = self.dataset

        query = UnarySelectQuery(subject=subject_id)

        for prop in properties:
            query.add_fetch_clause(predicate=str(prop))

        print(query.to_sparql())

        res = requests.post(
            url=self.route,
            json=query.to_dict(),
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
            log.warning("Query of entity %s failed due to %s", subject_id, res.reason)
            return []

    # def search_named_individuals(self,
    #                              references: dict[str, str]) -> list[Individual]:
    #    entities = []
    #    for name, kind in references.items():
    #        req = {
    #            "kinds": [kind],
    #            "clauses": [
    #                {
    #                    "property": "http://www.w3.org/2000/01/rdf-schema#label",
    #                    "value": name,
    #                    "method": "regex"
    #                }
    #            ]
    #        }
    #
    #        if self.dataset:
    #            req["dataset"] = self.dataset
    #
    #        res = requests.post(
    #            url=self.route,
    #            json=req,
    #            headers={"Accept": "application/json"},
    #            timeout=30
    #        )
    #
    #        if res.ok:
    #            entities.extend([Individual(r) for r in res.json()])
    #        else:
    #            log.error("Search individuals failed: code %d, reason %s", res.status_code, res.reason)
    #
    #    return entities

    def search_individuals(self,
                           kinds: list[str] = None,
                           search_values: dict[Attribute, str] = None,
                           ) -> list[Individual]:
        """
        Retrieves individuals by string search
        :param kinds:
        :param search_values:
        :return:
        """
        assert (kinds or search_values)
        entities = []
        query = UnarySelectQuery()
        if kinds:
            query.add_kinds(kinds)
        if search_values:
            search_clauses = UnionClause()
            for attribute, value in search_values.items():
                search_clauses.add_constraint(predicate=attribute, argument=value, method="regex")
                # req = {
                #     "kinds": [kind],
                #     "clauses": [
                #         {
                #             "property": "http://www.w3.org/2000/01/rdf-schema#label",
                #             "value": name,
                #             "method": "regex"
                #         }
                #     ]
                # }

        res = requests.post(
            url=self.route,
            json=query.to_dict(),
            headers={"Accept": "application/json"},
            timeout=30
        )

        if res.ok:
            entities.extend([Individual(r.get('id'), **r) for r in res.json()])
        else:
            log.error("Search individuals failed: code %d, reason %s", res.status_code, res.reason)

        return entities