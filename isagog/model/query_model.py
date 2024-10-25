"""
    A model for knowledge graph queries
    The model is based on a triple query language (subject, property, argument)
    (c) Isagog S.r.l. 2024, MIT License
"""
from __future__ import annotations

import logging
import random
import re
from enum import Enum
from typing import Protocol, List, Tuple, Union, Optional, ClassVar, Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator, field_validator
from rdflib import RDF, RDFS, OWL, URIRef

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
    value: str

    @field_validator('value', mode='before')
    def validate_identifier(cls, value: Any) -> str:
        try:
            if isinstance(value, str):
                if value.startswith('?'):
                    raise ValueError("Identifier cannot be a variable")
                URIRef(value)
                return value
            raise ValueError(f"Expected string, got {type(value)}")
        except Exception as e:
            raise ValueError(f"Invalid identifier: {e}")

    def __str__(self) -> str:
        return self.value

    def n3(self) -> str:
        return URIRef(self.value).n3()

    model_config = {
        "frozen": True
    }

class Variable(BaseModel):
    value: str

    @field_validator('value', mode='before')
    def validate_variable(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Expected string, got {type(value)}")
        if not value.startswith('?'):
            value = f"?{value}"
        pattern = r'^[a-zA-Z0-9_?]+$'
        if not re.match(pattern, value):
            raise ValueError(f"Invalid variable name {value}")
        return value

    def __str__(self) -> str:
        return self.value

    model_config = {
        "frozen": True
    }

class Value(BaseModel):
    value: Union[str, int, float]

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

# Predefined identifiers
RDF_TYPE = Identifier(value=str(RDF.type))
RDFS_LABEL = Identifier(value=str(RDFS.label))
OWL_CLASS = Identifier(value=str(OWL.Class))

class BaseClause(BaseModel):
    subject: Optional[Union[Identifier, Variable]] = None
    optional: bool = False

    def is_defined(self) -> bool:
        return self.subject is not None

    model_config = {
        "extra": "forbid"
    }

class AtomicClause(BaseClause):
    property: Identifier
    argument: Optional[Union[Value, Identifier, Variable]] = None
    variable: Optional[Variable] = None
    method: Comparison = Comparison.ANY
    project: bool = True
    type: ClassVar[str] = "atomic"

    @model_validator(mode='after')
    def validate_argument_variable(self) -> 'AtomicClause':
        if self.argument is None and self.variable is None:
            raise ValueError("Either argument or variable must be set")
        return self

    def n3(self) -> str:
        subj = self.subject.n3() if isinstance(self.subject, Identifier) else str(self.subject)
        pred = self.property.n3() if isinstance(self.property, Identifier) else f"<{self.property}>"
        if self.argument:
            val = self.argument.n3() if isinstance(self.argument, Identifier) else str(self.argument)
        elif self.variable:
            val = str(self.variable)
        else:
            raise ValueError("Invalid clause")
        return f"{subj} {pred} {val}"

class CompositeClause(BaseClause):
    clauses: List[BaseClause] = Field(default_factory=list)

class ConjunctiveClause(CompositeClause):
    type: ClassVar[str] = "conjunction"

class DisjunctiveClause(CompositeClause):
    type: ClassVar[str] = "union"

    @field_validator('clauses', mode='before')
    def validate_union_clauses(cls, value: Any) -> List[BaseClause]:
        if not isinstance(value, list):
            raise ValueError(f"Expected list, got {type(value)}")
        if not value:
            return value
        subject = value[0].subject
        if not all(clause.subject == subject for clause in value):
            raise ValueError("All clauses in union must have the same subject")
        return value

class Generator(Protocol):
    def __init__(self, language: str, version: str = None):
        self.language = language
        self.version = version

    def generate_query(self, query: SelectQuery, **kwargs) -> str:
        pass

    def generate_clause(self, clause: BaseClause, **kwargs) -> str:
        pass

class SelectQuery(BaseModel):
    prefixes: List[Tuple[str, str]] = Field(default_factory=lambda: DEFAULT_PREFIXES.copy())
    clauses: List[Union[AtomicClause, ConjunctiveClause, DisjunctiveClause]] = Field(default_factory=list)
    graph: str = "defaultGraph"
    limit: int = -1
    lang: str = "en"
    min_score: Optional[float] = None

    model_config = {
        "extra": "forbid",
        "validate_assignment": True
    }

    def add_prefix(self, prefix: str, uri: str) -> None:
        if not any(existing_prefix == prefix for existing_prefix, _ in self.prefixes):
            self.prefixes.append((prefix, uri))

    def add(self, clauses: Union[BaseClause, List[BaseClause]], **kwargs) -> None:
        if isinstance(clauses, list):
            clause_type = kwargs.get('type', 'conjunction')
            if clause_type == 'conjunction':
                list_clause = ConjunctiveClause(
                    clauses=clauses,
                    optional=kwargs.get('optional', False)
                )
            elif clause_type == 'union':
                list_clause = DisjunctiveClause(
                    subject=kwargs.get('subject'),
                    clauses=clauses
                )
            else:
                raise ValueError('unknown list clause type')
            self.clauses.append(list_clause)
        elif isinstance(clauses, AtomicClause) and clauses.method == Comparison.KEYWORD:
            self.clauses.insert(0, clauses)
        else:
            self.clauses.append(clauses)

    def clause(
        self,
        property: Union[Identifier, str],
        subject: Optional[Union[Identifier, Variable, str]] = None,
        argument: Optional[Union[str, int, float, Value, Identifier, Variable]] = None,
        variable: Optional[Union[Variable, str]] = None,
        method: Comparison = Comparison.ANY,
        project: bool = True,
        optional: bool = False
    ) -> 'SelectQuery':
        if isinstance(property, str):
            property = Identifier(value=property)
        
        if isinstance(subject, str):
            subject = Variable(value=subject) if subject.startswith('?') else Identifier(value=subject)
            
        if argument and not isinstance(argument, (Value, Identifier, Variable)):
            argument = Value(value=argument)
            
        if variable and not isinstance(variable, Variable):
            variable = Variable(value=variable)

        atomic_clause = AtomicClause(
            property=property,
            subject=subject,
            argument=argument,
            variable=variable,
            method=method,
            project=project,
            optional=optional
        )
        self.add(atomic_clause)
        return self

    def project_clauses(self) -> List[AtomicClause]:
        def _project_clauses(c: BaseClause, _clauses: List[AtomicClause]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                _clauses.append(c)
            elif isinstance(c, (ConjunctiveClause, DisjunctiveClause)):
                for sc in c.clauses:
                    _project_clauses(sc, _clauses)

        project_clauses = []
        for c in self.clauses:
            _project_clauses(c, project_clauses)
        return project_clauses

    def project_vars(self) -> set[str]:
        def _project_vars(c: BaseClause, _vars: List[str]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                if c.variable and not c.argument:
                    _vars.append(str(c.variable))
                elif isinstance(c.argument, Variable):
                    _vars.append(str(c.argument))
                if isinstance(c.subject, Variable):
                    _vars.append(str(c.subject))
            elif isinstance(c, (ConjunctiveClause, DisjunctiveClause)):
                for sc in c.clauses:
                    _project_vars(sc, _vars)

        _vars = []
        for c in self.clauses:
            _project_vars(c, _vars)
        return set(_vars)

    def has_return_vars(self) -> bool:
        return len(self.project_vars()) > 0

    def sort_clauses(self) -> 'SelectQuery':
        self.clauses = sorted(self.clauses, key=lambda clause: clause.optional)
        for clause in self.clauses:
            if isinstance(clause, CompositeClause):
                clause.clauses = sorted(clause.clauses, key=lambda c: c.optional)
        return self

    def generate(self, generator: Generator) -> str:
        return generator.generate_query(self)

    def to_dict(self, **kwargs) -> dict:
        return self.model_dump(**kwargs)

class UnarySelectQuery(SelectQuery):
    subject: Union[Identifier, Variable] = Field(default_factory=lambda: Variable(value=_SUBJVAR))
    kinds: Optional[List[str]] = None

    @model_validator(mode='after')
    def setup_kinds(self) -> 'UnarySelectQuery':
        if self.kinds:
            # Add RDF type clause for the first kind
            self.add(AtomicClause(
                subject=self.subject,
                property=RDF_TYPE,
                argument=Identifier(value=self.kinds[0]),
                method=Comparison.EXACT,
                project=False
            ))

            # Add union clause for additional kinds
            if len(self.kinds) > 1:
                kind_union = DisjunctiveClause(subject=self.subject)
                for kind in self.kinds[1:]:
                    kind_union.add_atom(
                        property=RDF_TYPE,
                        argument=Identifier(value=kind),
                        method=Comparison.EXACT
                    )
                self.add(kind_union)
        return self

    def clause(
        self,
        property: Union[Identifier, str],
        subject: Optional[Union[Identifier, Variable, str]] = None,
        argument: Optional[Union[str, int, float, Value, Identifier, Variable]] = None,
        variable: Optional[Union[Variable, str]] = None,
        method: Comparison = Comparison.ANY,
        project: bool = True,
        optional: bool = False
    ) -> 'UnarySelectQuery':
        if subject is None:
            subject = self.subject
        super().clause(
            property=property,
            subject=subject,
            argument=argument,
            variable=variable,
            method=method,
            project=project,
            optional=optional
        )
        return self

    def add_match_clause(
        self,
        predicate: Identifier,
        argument: Union[str, int, float, Value, Identifier],
        method: Comparison = Comparison.EXACT,
        project: bool = False,
        optional: bool = False
    ) -> None:
        if not isinstance(argument, (Value, Identifier)):
            argument = Value(value=argument)
        self.add(AtomicClause(
            subject=self.subject,
            property=predicate,
            argument=argument,
            method=method,
            project=project,
            optional=optional
        ))

    def add_fetch_clause(
        self,
        predicate: Identifier,
        variable: Optional[Variable] = None
    ) -> None:
        if variable is None:
            variable = Variable(value=str(random.randint(0, 1000000)))
        self.add(AtomicClause(
            subject=self.subject,
            property=predicate,
            variable=variable,
            method=Comparison.ANY,
            project=True,
            optional=True
        ))

    def get_kinds(self) -> List[Identifier]:
        return [c.argument for c in self.atom_clauses()
                if isinstance(c, AtomicClause) and
                c.property == RDF_TYPE and
                isinstance(c.argument, Identifier)]

    def is_scored(self) -> bool:
        return any(isinstance(c, AtomicClause) and c.method == Comparison.KEYWORD
                  for c in self.clauses)

    @classmethod
    def new(cls, data: dict) -> 'UnarySelectQuery':
        return cls.model_validate(data)

