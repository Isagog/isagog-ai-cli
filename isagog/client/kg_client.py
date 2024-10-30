"""
Interface to the Isagog Knoledge Graph service
(c) Isagog S.r.l. 2024, MIT License
"""
import logging
import os
import time
from typing import Type, TypeVar, Optional, List

# import requests
import httpx
from dotenv import load_dotenv

from isagog.model.kg_model import Individual, Assertion, Attribute, Relation, ID, KnowledgeObject
from isagog.model.query_model import UnaryQuery, Identifier, Variable

load_dotenv()

KG_DEFAULT_TIMEOUT = int(os.getenv('KG_DEFAULT_TIMEOUT', 120))

# Type variable for the Entity hierarchy
E = TypeVar('E', bound='Entity')

AUTH_TOKEN_KEY = os.getenv('ISAGOG_AUTH_TOKEN_KEY', 'X-Isagog-API-Token')
AUTH_TOKEN_VALUE = os.getenv('ISAGOG_AUTH_TOKEN_VALUE')


class KnowledgeBase(object):
    """
    Interface to knowledge base service
    """

    def __init__(self,
                 route: str,
                 dataset: str = None,
                 logger=None):
        """

        :param route: the service's endpoint route
        :param dataset: the dataset name; if None, uses the service's default

        """
        assert route
        self.route = route
        self.dataset = dataset
        self.logger = logger if logger else logging.getLogger()
        self.logger.info("Isagog KG client (%s) initialized on route %s", hex(id(self)), route)

    def get_knowledge(self,
                   id: ID,
                   expand: bool = True,
                   type: Type[E] = KnowledgeObject,
                   **kwargs
                   ) -> E | None:
        """
        Gets the knowledge object by its identifier
        :param id: the entity identifier
        :param expand: whether to return attributes
        :param entity_type: the entity type (default: Entity)
        """

        assert id

        self.logger.debug("Fetching %s", id)

        if not issubclass(type, KnowledgeObject):
            raise ValueError(f"{type} not a KnowledgeObject")

        expand = "true" if expand else "false"

        params = f"id={id}&expand={expand}"

        headers = {"Accept": "application/json"}

        if AUTH_TOKEN_VALUE:
            headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE

        if self.dataset:
            params += f"&dataset={self.dataset}"
        try:
            res = httpx.get(
                url=self.route,
                params=params,
                headers=headers,
            )
            res.raise_for_status()
            self.logger.debug("Fetched %s", id)
            return type(id=id, **res.json())
        except httpx.ConnectError:
            self.logger.error("Failed to connect to the host %s.", self.route)
            return None
        except httpx.RequestError as exc:
            self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
            return None
        except httpx.TimeoutException:
            self.logger.error("The request timed out from %s.", self.route)
            return None
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
            return None
        except Exception as exc:
            self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
            return None

    def query_assertions(self,
                         subject: Individual,
                         properties: list[Attribute | Relation],
                         **kwargs
                         ) -> list[Assertion]:
        """
        Returns specific entity properties

        :param timeout:
        :param subject:
        :param properties: the queried properties
        :return: a list of dictionaries { property: values }
        """
        assert (subject and properties)

        if not isinstance(subject, Individual):
            raise ValueError(f"{subject} not an Individual")

        if not all(isinstance(prop, (Attribute, Relation)) for prop in properties):
            raise ValueError(f"{properties} not all Attributes or Relations")

        self.logger.debug("Querying assertions for %s", subject)

        query = UnaryQuery(subject=subject.id)

        for prop in properties:
            query.and_where(property=Identifier.new(prop.id),
                            argument=Variable.new(f"?{prop.id}"))  #add_fetch_clause(predicate=str(prop.id))

        headers = {"Accept": "application/json"}

        if AUTH_TOKEN_VALUE:
            headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE

        query_dict = query.to_dict()

        timeout = kwargs.get('timeout', KG_DEFAULT_TIMEOUT)

        try:
            res = httpx.post(
                url=self.route,
                json=query_dict,
                headers=headers,
                timeout=timeout
            )
            res.raise_for_status()

            res_list = res.json()
            if len(res_list) == 0:
                self.logger.warning("Void attribute query")
                return []
            else:
                res_attrib_list = res_list[0].get('attributes', None)
                if res_attrib_list is None:
                    raise Exception("Malformed response from attribute query")
                def __get_values(_prop: str) -> str:
                    try:
                        record = next(item for item in res_attrib_list if item['id'] == _prop)
                        values = record.get('values', None)
                        if values is None:
                            raise Exception("Malformed response from attribute query")
                    except StopIteration:
                        # raise OSError("incomplete response: %s not found", _prop)
                        return None

                return [Assertion(predicate=prop, values=__get_values(prop)) for prop in properties]

        except httpx.ConnectError:
            self.logger.error("Failed to connect to the host %s.", self.route)
            return []
        except httpx.RequestError as exc:
            self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
            return []
        except httpx.TimeoutException:
            self.logger.error("The request timed out from %s.", self.route)
            return []
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
            return []
        except Exception as exc:
            self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
            return []


    def query_individuals(self,
                          query: UnaryQuery,
                          **kwargs
                          ) -> Optional[List[Individual]]:
        """


        :param query: the query
        :return: a list of individuals of the specified kind
        """
        start_time = time.time()

        req = query.model_dump()

        if self.dataset and (self.version == "latest" or self.version > "v1.0.0"):
            req['dataset'] = self.dataset

        headers = {"Accept": "application/json"}

        if AUTH_TOKEN_VALUE:
            headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE

        timeout = kwargs.get('timeout', KG_DEFAULT_TIMEOUT)

        try:
            res = httpx.post(
                url=self.route,
                json=req,
                headers=headers,
                timeout=timeout
            )
            res.raise_for_status()
            self.logger.debug("Query individuals done in %d seconds", time.time() - start_time)
            return [Individual(id=r.get('id'), **r) for r in res.json()]

        except httpx.ConnectError:
            self.logger.error("Failed to connect to the host %s.", self.route)
            return []
        except httpx.RequestError as exc:
            self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
            return []
        except httpx.TimeoutException:
            self.logger.error("The request timed out from %s.", self.route)
            return []
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
            return []
        except Exception as exc:
            self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
            return []

    def upsert_individual(self, individual: Individual, **kwargs) -> bool:
        """
        Updates an individual or insert it if not present; existing properties are preserved

        :param individual: the individual

        :return:
        """
        if individual.need_update():

            self.logger.debug("Updating individual %s", individual.id)

            params = {'id': individual.id}
            if self.dataset:
                params['dataset'] = self.dataset

            req = [ass.to_dict() for ass in individual.get_assertions()]

            headers = {"Accept": "application/json"}

            if AUTH_TOKEN_VALUE:
                headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE

            try:
                res = httpx.patch(
                    url=self.route,
                    params=params,
                    json=req,
                    headers=headers
                )
                res.raise_for_status()
                individual.updated()
                return True
            except httpx.ConnectError:
                self.logger.error("Failed to connect to the host %s.", self.route)
                return False
            except httpx.RequestError as exc:
                self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
                return False
            except httpx.TimeoutException:
                self.logger.error("The request timed out from %s.", self.route)
                return False
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
                return False
            except Exception as exc:
                self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
                return False

        else:
            self.logger.warning("Individual %s doesn't need update", individual.id)

    def delete_individual(self, _id: ID, **kwargs):
        pass
