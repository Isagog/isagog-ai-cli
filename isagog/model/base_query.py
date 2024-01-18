import random
import re
from enum import Enum
from typing import Protocol

from rdflib import URIRef


class Comparison(Enum):
    EXACT = "exact_match"
    KEYWORD = "keyword_search"
    REGEX = "regex"
    SIMILARITY = "similarity"
    GREATER = "greater_than"
    LESSER = "lesser_than"
    ANY = "any"


class Identifier(URIRef):
    """
    Must be an uri string, possibly prefixed

    """

    @staticmethod
    def is_valid_id(id_string):
        try:
            if id_string.startswith('?'):
                return False
            URIRef(id_string)
            return True
        except Exception:
            return False

    def __new__(cls, value: str | URIRef):
        return super().__new__(cls, value)


class Variable(str):
    """
    Can be an uri or a variable name
    """

    @staticmethod
    def is_valid_variable_value(var_string):
        try:
            Variable(var_string)
            return True
        except ValueError:
            return False

    @staticmethod
    def is_valid_variable_id(var_string):
        return var_string.startswith('?')

    def __new__(cls, value=None):

        if not value:
            value = random.randint(0, 1000000)  # assume that conflicts are negligible
        if not (isinstance(value, str) or isinstance(value, int)):
            raise ValueError(f"Bad variable type {value}")
        if isinstance(value, int):
            return super().__new__(cls, f'?{hex(value)}')

        if value.startswith("?"):
            pattern = r'^[a-zA-Z0-9_?]+$'
            if re.match(pattern, value):
                return super().__new__(cls, value)
            else:
                raise ValueError(f"Bad variable name {value}")

        pattern = r'^[a-zA-Z0-9_]+$'
        if re.match(pattern, value):
            return super().__new__(cls, "?" + value)
        else:
            raise ValueError(f"Bad variable name {value}")


class Value(str):
    """
    Can be a string or a number
    """

    def __init__(self, value):
        if isinstance(value, str) and ((value.startswith("<") and value.endswith(">")) or value.startswith("?")):
            raise ValueError(f"Bad value string {value}")
        self.value = value

    def __str__(self) -> str:
        return str(self.value)


class Clause(object):

    def __init__(self,
                 subject: Identifier | Variable | str = None,
                 optional=False):
        self.subject = subject
        self.optional = optional

    def to_sparql(self) -> str:
        """
        Deprecated, use a SPARQL generator instead
        :return:
        """
        pass

    def to_dict(self, **kwargs) -> dict:
        pass

    def is_defined(self) -> bool:
        return self.subject is not None

    def from_dict(self, data: dict, **kwargs):
        pass


class Query(object):

    def add(self, clause: Clause | list = None, **kwargs):
        """
        Add one or more clauses to the query
        :param clause: one or more clauses
        :param kwargs: @AtomicClause parameters, and / or options
        :return:
        """
        pass


class Generator(Protocol):

    def __init__(self, language: str, version: str = None):
        self.language = language
        self.version = version

    def generate_query(self, query: Query, **kwargs) -> str:
        pass

    def generate_clause(self, clause: Clause, **kwargs) -> str:
        pass
