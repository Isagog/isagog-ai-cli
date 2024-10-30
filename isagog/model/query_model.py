"""
    A model for knowledge graph queries
    The model is based on a triple query language (subject, property, argument)
    (c) Isagog S.r.l. 2024, MIT License
"""
from __future__ import annotations

import re
import string
from abc import abstractmethod, ABC
from enum import Enum
import random
from typing import  List, Union, Optional, Any, Dict
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator, field_validator
from rdflib import RDF, RDFS, OWL, URIRef

from isagog.model.kg_model import N3String, N3Serializable

DEFAULT_PREFIXES = [
    ("rdf", "http://www.w3.org/2000/01/rdf-schema"),
    ("rdfs", "http://www.w3.org/2001/XMLSchema"),
    ("text", "http://jena.apache.org/text")
]

_SUBJVAR:str = '?i'
_KINDVAR:str = '?k'
_SCOREVAR:str = '?score'


class META_PROPERTIES(str, Enum):
    IN = "IN"

class Comparison(str, Enum):
    EXACT = "exact_match"
    KEYWORD = "keyword_search"
    REGEX = "regex"
    SIMILARITY = "similarity"
    EQUAL = "equal"
    GREATER = "greater_than"
    GREATER_EQUAL = "greater_equal"
    LESSER = "lesser_than"
    LESSER_EQUAL = "lesser_equal"
    NOT_EXISTS = "not_exists"
    ANY = "any"

def is_uri(string: str) -> bool:
    parsed = urlparse(string)
    return bool(parsed.scheme) and bool(parsed.netloc)

def is_variable(string: str) -> bool:
    return string.startswith('?')


class Identifier(BaseModel, N3Serializable):
    id: N3String

    def __str__(self) -> str:
        return self.id

    def n3(self):
        return self.id.n3()

    @classmethod
    @field_validator('id')
    def validate_value(cls, v: str) -> str:
        if not v:
            raise ValueError("Identifier cannot be empty")
        return v

    @staticmethod
    def new(value: Union[str, URIRef]) -> Identifier:
        return Identifier(id=N3String(value))


class Variable(BaseModel, N3Serializable):
    symbol: str = Field(default_factory=lambda: ''.join(random.choices(string.ascii_letters, k=4)))
    constraint: Optional[Value] = None

    @classmethod
    @field_validator('symbol', mode='before')
    def validate_variable(cls, symbol: Any) -> str:
        if not isinstance(symbol, str):
            raise ValueError(f"Expected string, got {type(symbol)}")
        if not symbol.startswith('?'):
            symbol = f"?{symbol}"
        pattern = r'^[a-zA-Z0-9_?]+$'
        if not re.match(pattern, symbol):
            raise ValueError(f"Invalid symbol name {symbol}")
        return symbol

    def __str__(self) -> str:
        return self.symbol

    model_config = {
        "frozen": True
    }

    def n3(self) -> str:
        return self.symbol

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Variable:
        return cls(symbol=values.get("symbol"))

    @staticmethod
    def new(value: str, constr: Union[str, int, float] = None) -> Variable:
        if constr:
            return Variable(symbol=value, constraint=Value.new(constr))
        return Variable(symbol=value)


class Value(BaseModel, N3Serializable):
    value: Union[str, int, float]

    @classmethod
    @field_validator('value', mode='before')
    def validate_value(cls, value: Any) -> Union[str, int, float]:
        if isinstance(value, str):
            if urlparse(value).scheme or value.startswith('?'):
                raise ValueError(f"Invalid value string {value}")
        elif not isinstance(value, (int, float)):
            raise ValueError(f"Expected string, int, or float, got {type(value)}")
        return value

    def __str__(self) -> str:
        return str(self.value)

    model_config = {
        "frozen": True
    }

    def n3(self) -> str:
        if isinstance(self.value, str):
            return f'"{self.value}"'
        return str(self.value)


    @staticmethod
    def new(value: Union[str, int, float]) -> Value:
        return Value(value=value)


# Predefined identifiers
RDF_TYPE = Identifier.new(RDF.type)
RDFS_LABEL = Identifier.new(RDFS.label)
OWL_CLASS = Identifier.new(OWL.Class)
OWL_INDIVIDUAL = Identifier.new(OWL.NamedIndividual)


Subject = Union[Identifier, Variable]
Property = Identifier
Argument = Union[Value,Identifier, Variable]

class Clause(BaseModel):
    optional: bool = False

    @abstractmethod
    def _subject(self) -> Optional[Subject]:
        pass

    @abstractmethod
    def _property(self) -> Optional[Property]:
        pass

    @abstractmethod
    def _argument(self) -> Optional[Argument]:
        pass

    def is_defined(self) -> bool:
        return all([self._subject(), self._property(), self._argument()])


class AtomicClause(Clause):
    property: Identifier = Field(...)
    subject: Subject = Field(default_factory=lambda: Variable.new(_SUBJVAR))
    argument: Argument = Field(default_factory=lambda: Value.new(""))
    operator: Comparison = Field(default=Comparison.ANY)
    project: bool = True
    optional: bool = False

    def n3(self) -> str:
        return f"{self.subject.n3()} {self.property.n3()} {self.argument.n3()}"

    def _subject(self) -> Optional[Subject]:
        return self.subject

    def _property(self) -> Optional[Property]:
        return self.property

    def _argument(self) -> Optional[Argument]:
        return self.argument

    def arg_variable(self) -> Optional[Variable]:
        if isinstance(self.argument, Variable):
            return self.argument
        return None

    def subj_variable(self) -> Optional[Variable]:
        if isinstance(self.subject, Variable):
            return self.subject
        return None

class CompositeClause(Clause):
    clauses: List[AnyClause] = Field(default_factory=list)
    op: str = None

    @classmethod
    @field_validator('clauses', mode='before')
    def validate_components(cls, value: Any) -> List[Clause]:
        if not isinstance(value, list):
            raise ValueError(f"Expected list, got {type(value)}")
        if not value:
            return value
        subject = value[0].subject
        if not all(clause.subject == subject for clause in value):
            raise ValueError("All clauses in composite must have the same subject")
        return value

    def add(self, clause: Clause) -> 'CompositeClause':
        self.clauses.append(clause)
        return self

    def first(self) -> Optional[Clause]:
        if self.clauses:
            return self.clauses[0]
        else:
            return None

    def last(self) -> Optional[Clause]:
        if self.clauses:
            return self.clauses[-1]
        else:
            return None

    def _subject(self) -> Optional[Subject]:
        last = self.last()
        if last:
            return last._subject()
        else:
            return None

    def _property(self) -> Optional[Property]:
        last = self.last()
        if last:
            return last._property()
        else:
            return None

    def _argument(self) -> Optional[Argument]:
        last = self.last()
        if last:
            return last._argument()
        else:
            return None


class ConjunctiveClause(CompositeClause):
    op: str = "AND"



class DisjunctiveClause(CompositeClause):
    op: str = "OR"


AnyClause = Union[AtomicClause, CompositeClause, ConjunctiveClause, DisjunctiveClause]

class Select(ConjunctiveClause):

    def add_prefix(self, prefix: str, uri: str) -> None:
        if not any(existing_prefix == prefix for existing_prefix, _ in self.prefixes):
            self.prefixes.append((prefix, uri))


    def _new_atom(self,
                  operation: Comparison,
                  argument: Argument,
                  property: Property = None,
                  subject: Subject = None,
                  optional: bool = False,
                  project: bool = False) -> AtomicClause:

        subj = self.last()._subject() if subject is None else subject
        if subj is None:
            raise ValueError("Subject must be specified")
        prop = self.last()._property() if property is None else property
        if prop is None:
            raise ValueError("Property must be specified")
        new_atom = AtomicClause(subject=subj,
                                property=prop,
                                operator=operation,
                                argument=argument,
                                optional=optional,
                                project=project)
        return new_atom



    def where(self,
              property: Property,
              argument: Argument,
              subject: Subject = Variable.new(_SUBJVAR),
              operation: Comparison = Comparison.ANY,
              optional: bool = False,
              project: bool = True) -> 'Select':
        new_clause = self._new_atom(subject=subject,
                                  property=property,
                                  operation=operation,
                                  argument=argument,
                                  optional=optional,
                                  project=project)
        self.clauses.append(new_clause)
        return self

    def and_where(self,
                  property: Property,
                  argument: Argument,
                  operation: Comparison = Comparison.ANY,
                  subject: Subject = None,
                  optional: bool = False,
                  project: bool = False) -> 'Select':
        new_atom = self._new_atom(
            operation=operation,
            argument=argument,
            property=property,
            subject=subject if subject else self.last()._subject(),
            optional=optional,
            project=project)
        if not self.clauses:
            raise Exception("Illegal call to and_where")
        self.clauses.append(new_atom)
        return self

    def and_select(self, select: Select) -> 'Select':
        if not self.clauses:
            raise Exception("Illegal call to and_select")
        self.clauses.append(select)
        return self

    def or_where(self,
                 property: Property,
                 argument: Argument,
                 operation: Comparison = Comparison.ANY,
                 subject: Subject = None,
                 optional: bool = False,
                 project: bool = False) -> 'Select':
        if not self.clauses:
            raise Exception("Illegal call to or_where")
        new_atom = self._new_atom(operation, argument, property, subject, optional, project)
        if len(self.clauses) == 1:
            last = self.clauses.pop()
            self.clauses.append(DisjunctiveClause(clauses=[last, new_atom]))
        else:
            conj = ConjunctiveClause(clauses=self.clauses)
            disj = DisjunctiveClause(clauses=[conj, new_atom])
            self.clauses = [disj]
        return self

    def or_select(self, select: Select) -> 'Select':
        if not self.clauses:
            raise Exception("Illegal call to or_select")
        if len(self.clauses) == 1:
            last = self.clauses.pop()
            self.clauses.append(DisjunctiveClause(clauses=[last, select]))
        else:
            conj = ConjunctiveClause(clauses=self.clauses)
            disj = DisjunctiveClause(clauses=[conj, select])
            self.clauses = [disj]
        return self


    def project_vars(self) -> set[str]:
        def _project_vars(c: Clause, _vars: List[str]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                if c.arg_variable():
                    _vars.append(str(c.argument.symbol))
                if c.subj_variable():
                    _vars.append(str(c.subject.symbol))
            elif isinstance(c, CompositeClause):
                for sc in c.clauses:
                    _project_vars(sc, _vars)

        _vars = []
        for c in self.clauses:  # Usiamo clauses invece di select.components
            _project_vars(c, _vars)
        return set(_vars)

    def sort_clauses(self) -> 'Select':
        self.clauses = sorted(self.clauses, key=lambda clause: clause.optional)
        for clause in self.clauses:
            if isinstance(clause, CompositeClause):
                clause.clauses = sorted(clause.clauses, key=lambda c: c.optional)
        return self


class UnaryQuery(Select):
        """
        Unary query
        """
        prefixes: Optional[Dict] = None
        graph: str = "defaultGraph"
        subject: Subject = Variable.new(_SUBJVAR)
        kind: Optional[Union[Identifier, List[Identifier]]] = None
        limit: int = -1
        lang: str = "en"
        min_score: Optional[float] = None

        @model_validator(mode='after')
        def setup(self) -> 'UnaryQuery':

            self.where(
                subject=self.subject,
                property=RDF_TYPE,
                operation=Comparison.EXACT,
                argument=OWL_INDIVIDUAL,
                project=True
            )
            if self.kind:
                if isinstance(self.kind, Identifier):
                    self.and_where(
                        subject=self.subject,
                        property=RDF_TYPE,
                        operation=Comparison.EXACT,
                        argument=self.kind
                    )
                elif isinstance(self.kind, list):
                    self.and_where(
                        subject=self.subject,
                        property=RDF_TYPE,
                        operation=Comparison.EXACT,
                        argument=self.kind.pop(0)
                    )
                    for kind in self.kind:
                        self.or_where(
                            subject=self.subject,
                            property=RDF_TYPE,
                            argument=kind,
                            operation=Comparison.EXACT,
                            project=False
                        )
                else:
                    raise ValueError("Invalid kind")

            return self

        def is_scored(self) -> bool:
            return self.min_score is not None

        def has_disjunctive_clauses(self) -> bool:
            return any(isinstance(clause, DisjunctiveClause) for clause in self.clauses)

        def has_conjunctive_clauses(self) -> bool:
            return any(isinstance(clause, ConjunctiveClause) for clause in self.clauses)

        def atom_clauses(self) -> List[AtomicClause]:
            def _atom_clauses(c: Clause, _clauses: List[AtomicClause]) -> None:
                if isinstance(c, AtomicClause):
                    _clauses.append(c)
                elif isinstance(c, CompositeClause):
                    for sc in c.clauses:
                        _atom_clauses(sc, _clauses)

            atom_clauses = []
            for c in self.clauses:
                _atom_clauses(c, atom_clauses)
            return atom_clauses

        def conjunctive_clauses(self) -> List[ConjunctiveClause]:
            return [clause for clause in self.clauses if isinstance(clause, ConjunctiveClause)]

        def disjunctive_clauses(self) -> List[DisjunctiveClause]:
            return [clause for clause in self.clauses if isinstance(clause, DisjunctiveClause)]


        def to_dict(self, **kwargs) -> dict:
            return self.model_dump()



class Generator(ABC):
    def __init__(self, language: str, version: str = None):
        self.language = language
        self.version = version

    @abstractmethod
    def generate_query(self, query: UnaryQuery, **kwargs) -> str:
        pass

    @abstractmethod
    def generate_clause(self, clause: Clause, **kwargs) -> str:
        pass

