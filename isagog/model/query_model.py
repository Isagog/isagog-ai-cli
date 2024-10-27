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

from pydantic import BaseModel, Field, model_validator, field_validator
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


# class Identifier(BaseModel):
#     value: N3String
#
#     def __init__(self, value: Union[str, URIRef]) -> None:
#         super().__init__()
#         self.value = N3String(value)
#
#     def __str__(self) -> str:
#         return self.value
#
#     @classmethod
#     def __validate__(cls, value: Any) -> Any:
#         if isinstance(value, (str, URIRef)):
#             return cls(value=value)
#         return value
#
#     @field_validator('value')
#     def validate_value(cls, v: str) -> str:
#         if not v:  # se vuoi verificare che non sia vuota
#             raise ValueError("Identifier cannot be empty")
#         return v


ID = N3String


class Variable(BaseModel):
    symbol: str

    @classmethod
    @field_validator('symbol', mode='before')
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
        return self.symbol

    model_config = {
        "frozen": True
    }



def VAR(value: str, constr: Value = None) -> Variable:
    if constr:
        return ConstraintVariable(symbol=value, constraint=constr)
    return Variable(symbol=value)

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

class ConstraintVariable(Variable):
    constraint: Value

# Predefined identifiers
RDF_TYPE = ID(RDF.type)
RDFS_LABEL = ID(RDFS.label)
OWL_CLASS = ID(OWL.Class)
OWL_INDIVIDUAL = ID(OWL.NamedIndividual)


Subject = Union[ID, Variable]
Property = ID
Argument = Union[Value,ID, Variable]

class Clause(BaseModel, ABC):
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
        return self._subject() is not None

    class Config:
        arbitrary_types_allowed = True

class AtomicClause(Clause):
    subject: Subject = Field(default_factory=lambda: Variable(symbol="_SUBJVAR"))
    property: ID = Field(default_factory=lambda: ID(""))
    argument: Argument = Field(default_factory=lambda: Value(value=""))
    operator: Comparison = Field(default=Comparison.ANY)
    project: bool = True
    optional: bool = False

    def arg_variable(self) -> bool:
        return isinstance(self.argument, Variable)

    @model_validator(mode='after')
    def validate_argument_variable(cls, values):
        if values.argument is None:
            raise ValueError("Argument must be set")
        return values

    def _subject(self) -> Optional[Subject]:
        return self.subject

    def _property(self) -> Optional[Property]:
        return self.property

    def _argument(self) -> Optional[Argument]:
        return self.argument

    def n3(self) -> str:
        return f"{self.subject.n3()} {self.property.n3()} {self.argument.n3()}"

    class Config:
        arbitrary_types_allowed = True

    def model_dump(self, **kwargs) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "property": self.property,
            "argument": self.argument,
            "operator": self.operator.value,
            "optional": self.optional,
            "project": self.project
        }

class CompositeClause(Clause):
    components: List[Clause] = Field(default_factory=list)
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
        # if clause.subject is None:
        #     clause.subject = self.subject
        # elif clause.subject != self.subject:
        #     raise Exception("Component clause must have same subject")
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
    class Config:
        arbitrary_types_allowed = True


class ConjunctiveClause(CompositeClause):
    op: str = "AND"

    def n3(self) -> str:
        return f"{' . '.join([c.n3() for c in self.components])}"

    class Config:
        arbitrary_types_allowed = True


class DisjunctiveClause(CompositeClause):
    op: str = "OR"

    class Config:
        arbitrary_types_allowed = True





class Generator(Protocol):
    def __init__(self, language: str, version: str = None):
        self.language = language
        self.version = version

    def generate_query(self, query: SelectQuery, **kwargs) -> str:
        pass

    def generate_clause(self, clause: Clause, **kwargs) -> str:
        pass

AnyClause = Union[AtomicClause, ConjunctiveClause, DisjunctiveClause]

class Select(CompositeClause):

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

    def _new_select(self,
                  property: Property,
                  operation: Comparison,
                  argument: Argument,
                  subject: Subject = None):
        subj = self.last()._subject() if subject is None else subject
        new_atom = AtomicClause(subject=subj,
                                property=property,
                                operator=operation,
                                argument=argument)
        new_select = Select().add(new_atom)
        return new_select

    def where(self,
              property: Property,
              argument: Argument,
              subject: Subject = VAR(_SUBJVAR),
              operation: Comparison = Comparison.ANY,
              optional: bool = False,
              project: bool = True) -> 'Select':
        new_clause = AtomicClause(subject=subject,
                                  property=property,
                                  operator=operation,
                                  argument=argument,
                                  optional=optional,
                                  project=project)
        self.components.append(new_clause)
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
            subject=subject,
            optional=optional,
            project=project)
        last_component = self.last()
        if isinstance(last_component, AtomicClause):
            self.components.append(new_atom)
        elif isinstance(last_component, CompositeClause):
            last_component.add(new_atom)
        else:
            raise Exception("Malformed select: did you forget a 'where'?")
        return self

    def or_where(self,
                  operation: Comparison,
                  argument: Argument,
                  property: Property = None,
                  subject: Subject = None,
                  optional: bool = False,
                  project: bool = False) -> 'Select':
        new_atom = self._new_atom(operation, argument, property, subject, optional, project)
        last_component = self.last()
        if isinstance(last_component, AtomicClause):
            self.components = [DisjunctiveClause(components=[last_component, new_atom])]
        elif isinstance(last_component, CompositeClause):
            last_component.add(new_atom)
        else:
            raise Exception(f"Unexpected clause type: {type(self.last())}")
        return self


    def and_where_select(self,
                  property: Property,
                  operation: Comparison,
                  argument: Argument,
                  subject: Subject = None) -> 'Select':

        return self._new_select(property, operation,argument,subject)

    class Config:
        arbitrary_types_allowed = True



class SelectQuery(BaseModel):
    prefixes: List[Tuple[str, str]] = Field(default_factory=lambda: DEFAULT_PREFIXES.copy())
    select: Select = Field(default_factory=Select)
    graph: str = "defaultGraph"
    limit: int = -1
    lang: str = "en"
    min_score: Optional[float] = None


    def add_prefix(self, prefix: str, uri: str) -> None:
        if not any(existing_prefix == prefix for existing_prefix, _ in self.prefixes):
            self.prefixes.append((prefix, uri))


    def project_clauses(self) -> List[AtomicClause]:
        def _project_clauses(c: Clause, _clauses: List[AtomicClause]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                _clauses.append(c)
            elif isinstance(c, (ConjunctiveClause, DisjunctiveClause)):
                for sc in c.components:
                    _project_clauses(sc, _clauses)

        project_clauses = []
        for c in self.select.components:
            _project_clauses(c, project_clauses)
        return project_clauses

    def project_vars(self) -> set[str]:
        def _project_vars(c: Clause, _vars: List[str]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                if c.arg_variable():
                    _vars.append(c.argument.symbol)
            elif isinstance(c, CompositeClause):
                for sc in c.components:
                    _project_vars(sc, _vars)

        _vars = []
        for c in self.select.components:
            _project_vars(c, _vars)
        return set(_vars)

    def has_return_vars(self) -> bool:
        return len(self.project_vars()) > 0

    def sort_clauses(self) -> 'SelectQuery':
        clauses = sorted(self.select.components, key=lambda clause: clause.optional)
        for clause in clauses:
            if isinstance(clause, CompositeClause):
                clause.components = sorted(clause.components, key=lambda c: c.optional)
        self.select.components = clauses
        return self

    def generate(self, generator: Generator) -> str:
        return generator.generate_query(self)

    def model_dump(self, **kwargs) -> dict:
        return {
            "prefixes": self.prefixes,
            "select": [c.model_dump(**kwargs) for c in self.select.components],
            "graph": self.graph,
            "limit": self.limit,
            "lang": self.lang,
            "min_score": self.min_score
        }


class UnarySelectQuery(SelectQuery):
    subject: Subject = VAR(_SUBJVAR)
    kind: Optional[Union[ID,List[ID]]] = None
    prefixes: Optional[Dict] = None

    @model_validator(mode='after')
    def setup(self) -> 'UnarySelectQuery':
        kinds = [OWL_INDIVIDUAL]
        if self.kind:
            if isinstance(self.kind, ID):
                kinds.append(self.kind)
            elif isinstance(self.kind, list):
                kinds.extend(self.kind)
            else:
                raise ValueError("Invalid kind")

        self.select.where(subject=self.subject,
                   property=RDF_TYPE,
                   operation=Comparison.EXACT,
                   argument=kinds.pop())
        for kind in kinds:
            # Add RDF type clause for the first kind
            self.select.and_where(subject=self.subject,
                property=RDF_TYPE,
                argument=kind,
                operation=Comparison.EXACT,
                project=False
            )
        return self




