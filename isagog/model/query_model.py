"""
    A model for knowledge graph queries
    The model is based on a triple query language (subject, property, argument)
    (c) Isagog S.r.l. 2024, MIT License
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Protocol, List, Tuple, Union, Optional, Any, Dict
from urllib.parse import urlparse
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, model_validator, field_validator, computed_field
from rdflib import RDF, RDFS, OWL, URIRef

from isagog.model.kg_model import N3String

DEFAULT_PREFIXES = [
    ("rdf", "http://www.w3.org/2000/01/rdf-schema"),
    ("rdfs", "http://www.w3.org/2001/XMLSchema"),
    ("text", "http://jena.apache.org/text")
]

_SUBJVAR = 'i'
_KINDVAR = 'k'
_SCOREVAR = 'score'

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


class Identifier(BaseModel):
    id: N3String

    def __str__(self) -> str:
        return self.id

    def n3(self):
        return self.id.n3()

    @field_validator('id')
    def validate_value(cls, v: str) -> str:
        if not v:
            raise ValueError("Identifier cannot be empty")
        return v

    @staticmethod
    def new(value: Union[str, URIRef]) -> Identifier:
        return Identifier(id=N3String(value))


class Variable(BaseModel):
    variable: str
    constraint: Optional[Value] = None

    @classmethod
    @field_validator('variable', mode='before')
    def validate_variable(cls, symbol: Any) -> str:
        if not isinstance(symbol, str):
            raise ValueError(f"Expected string, got {type(symbol)}")
        if not symbol.startswith('?'):
            symbol = f"?{symbol}"
        pattern = r'^[a-zA-Z0-9_?]+$'
        if not re.match(pattern, symbol):
            raise ValueError(f"Invalid variable name {symbol}")
        return symbol

    def __str__(self) -> str:
        return self.variable

    model_config = {
        "frozen": True
    }

    def model_dump(self, **kwargs) -> dict[str, Any]:
        return {
            "variable": self.variable
        }

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Variable:
        return cls(variable=values.get("variable"))

    @staticmethod
    def new(value: str, constr: Union[str, int, float] = None) -> Variable:
        if constr:
            return Variable(variable=value, constraint=Value.new(constr))
        return Variable(variable=value)





class Value(BaseModel):
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


class AtomicClause(Clause):
    subject: Subject = Field(default_factory=lambda: Variable.new(_SUBJVAR))
    property: Identifier = Field(default_factory=lambda: Identifier.new(""))
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

class CompositeClause(Clause):
    components: List[AnyClause] = Field(default_factory=list)
    op: str = None

    @classmethod
    @field_validator('components', mode='before')
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
        self.components.append(clause)
        return self

    def first(self) -> Optional[Clause]:
        if self.components:
            return self.components[0]
        else:
            return None

    def last(self) -> Optional[Clause]:
        if self.components:
            return self.components[-1]
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

    def n3(self) -> str:
        return f"{' . '.join([c.n3() for c in self.components])}"



class DisjunctiveClause(CompositeClause):
    op: str = "OR"


AnyClause = Union[AtomicClause, ConjunctiveClause, DisjunctiveClause]

class SelectQuery(BaseModel):
    prefixes: List[Tuple[str, str]] = Field(default_factory=lambda: DEFAULT_PREFIXES.copy())
    clauses: List[AnyClause] = Field(default_factory=list)
    graph: str = "defaultGraph"
    limit: int = -1
    lang: str = "en"
    min_score: Optional[float] = None


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


    def last(self) -> Optional[Clause]:
        if self.clauses:
            return self.clauses[-1]
        else:
            return None


    def where(self,
              property: Property,
              argument: Argument,
              subject: Subject = Variable.new(_SUBJVAR),
              operation: Comparison = Comparison.ANY,
              optional: bool = False,
              project: bool = True) -> 'SelectQuery':
        new_clause = AtomicClause(subject=subject,
                                  property=property,
                                  operator=operation,
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
                  project: bool = False) -> 'SelectQuery':
        new_atom = self._new_atom(
            operation=operation,
            argument=argument,
            property=property,
            subject=subject if subject else self.last()._subject(),
            optional=optional,
            project=project)
        last_component = self.last()
        if isinstance(last_component, AtomicClause):
            self.clauses.append(new_atom)
        elif isinstance(last_component, CompositeClause):
            last_component.add(new_atom)
        else:
            raise Exception("Malformed select: did you forget a 'where'?")
        return self

    def or_where(self,
                 property: Property,
                 argument: Argument,
                 operation: Comparison = Comparison.ANY,
                 subject: Subject = None,
                 optional: bool = False,
                 project: bool = False) -> 'SelectQuery':
        new_atom = self._new_atom(operation, argument, property, subject, optional, project)
        last_component = self.last()
        if isinstance(last_component, AtomicClause):
            self.clauses.append(DisjunctiveClause(components=[last_component, new_atom]))
        elif isinstance(last_component, CompositeClause):
            last_component.add(new_atom)
        else:
            raise Exception(f"Unexpected clause type: {type(self.last())}")
        return self

    def project_clauses(self) -> List[AtomicClause]:
        def _project_clauses(c: Clause, _clauses: List[AtomicClause]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                _clauses.append(c)
            elif isinstance(c, (ConjunctiveClause, DisjunctiveClause)):
                for sc in c.components:
                    _project_clauses(sc, _clauses)

        project_clauses = []
        for c in self.clauses:  # Usiamo clauses invece di select.components
            _project_clauses(c, project_clauses)
        return project_clauses

    def project_vars(self) -> set[str]:
        def _project_vars(c: Clause, _vars: List[str]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                if c.arg_variable():
                    _vars.append(c.argument.variable)
            elif isinstance(c, CompositeClause):
                for sc in c.components:
                    _project_vars(sc, _vars)

        _vars = []
        for c in self.clauses:  # Usiamo clauses invece di select.components
            _project_vars(c, _vars)
        return set(_vars)

    def sort_clauses(self) -> 'SelectQuery':
        self.clauses = sorted(self.clauses, key=lambda clause: clause.optional)
        for clause in self.clauses:
            if isinstance(clause, CompositeClause):
                clause.components = sorted(clause.components, key=lambda c: c.optional)
        return self


class UnarySelectQuery(SelectQuery):
    subject: Subject = Variable.new(_SUBJVAR)
    kind: Optional[Union[Identifier, List[Identifier]]] = None
    prefixes: Optional[Dict] = None

    @model_validator(mode='after')
    def setup(self) -> 'UnarySelectQuery':
        kinds = [OWL_INDIVIDUAL]
        if self.kind:
            if isinstance(self.kind, Identifier):
                kinds.append(self.kind)
            elif isinstance(self.kind, list):
                kinds.extend(self.kind)
            else:
                raise ValueError("Invalid kind")

        self.clauses = []

        # Add first RDF type clause
        self.clauses.append(AtomicClause(
            subject=self.subject,
            property=RDF_TYPE,
            operator=Comparison.EXACT,
            argument=kinds.pop()
        ))

        # Add additional RDF type clauses
        for kind in kinds:
            self.clauses.append(AtomicClause(
                subject=self.subject,
                property=RDF_TYPE,
                argument=kind,
                operator=Comparison.EXACT,
                project=False
            ))

        return self





class Generator(Protocol):
    def __init__(self, language: str, version: str = None):
        self.language = language
        self.version = version

    def generate_query(self, query: SelectQuery, **kwargs) -> str:
        pass

    def generate_clause(self, clause: Clause, **kwargs) -> str:
        pass

