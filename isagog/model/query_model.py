"""
    A model for knowledge graph queries
    The model is based on a triple query language (subject, property, argument)
    (c) Isagog S.r.l. 2024, MIT License
"""
from __future__ import annotations

import re
from isagog.model.kg_model import N3String
from enum import Enum
from typing import Protocol, List, Tuple, Union, Optional, ClassVar, Any
from urllib.parse import urlparse
from abc import ABC, abstractmethod

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
            elif isinstance(value, (URIRef, N3String)):
                return str(value)
            elif isinstance(value, Identifier):
                return value.value
            raise ValueError(f"Unexpected type for Identifier {type(value)}")
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
OWL_INDIVIDUAL = Identifier(value=str(OWL.NamedIndividual))


Subject = Union[Identifier, Variable]
Property = Identifier
Argument = Union[Value,Identifier, Variable]

class BaseClause(BaseModel, ABC):
    # subject: Optional[Subject] = None
    optional: bool = False

    @abstractmethod
    def subject(self) -> Optional[Subject]:
        pass

    def is_defined(self) -> bool:
        return self.subject() is not None

    model_config = {
        "extra": "forbid"
    }


class AtomicClause(BaseClause):
    subject: Optional[Subject] = None
    property: Identifier
    argument: Argument
    #variable: Optional[Variable] = None
    operator: Comparison = Comparison.ANY
    project: bool = True
    optional: bool = False
    type: ClassVar[str] = "atomic"

    def arg_variable(self) -> bool:
        return isinstance(self.argument, Variable)

    # @model_validator(mode='after')
    # def validate_argument_variable(self) -> 'AtomicClause':
    #     if self.argument is None and self.variable is None:
    #         raise ValueError("Either argument or variable must be set")
    #     return self

    def n3(self) -> str:
        # subj = self.subject.n3() if isinstance(self.subject, Identifier) else str(self.subject)
        # pred = self.property.n3() if isinstance(self.property, Identifier) else f"<{self.property}>"
        # if self.argument:
        #     val = self.argument.n3() if isinstance(self.argument, Identifier) else str(self.argument)
        # elif self.variable:
        #     val = str(self.variable)
        # else:
        #     raise ValueError("Invalid clause")
        return f"{self.subject.n3()} {self.property.n3()} {self.argument.n3()}"

class CompositeClause(BaseClause):
    components: List[BaseClause] = Field(default_factory=list)

    def add(self, clause: BaseClause) -> 'CompositeClause':
        self.components.append(clause)
        return self

    def first(self) -> Optional[BaseClause]:
        if self.components:
            return self.components[0]
        else:
            return None

    def last(self) -> Optional[BaseClause]:
        if self.components:
            return self.components[-1]
        else:
            return None

class ConjunctiveClause(CompositeClause):
    type: ClassVar[str] = "conjunction"

class DisjunctiveClause(CompositeClause):
    type: ClassVar[str] = "union"

    @field_validator('components', mode='before')
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

AnyClause = Union[AtomicClause, ConjunctiveClause, DisjunctiveClause]

class Select(CompositeClause):


    def _new_atom(self,
                  operation: Comparison,
                  argument: Argument,
                  property: Property = None,
                  subject: Subject = None,
                  optional: bool = False,
                  project: bool = False) -> AtomicClause:
        subj = self.last().subject if subject is None else subject
        assert subj is not None
        prop = self.last().property if property is None else property
        assert prop is not None
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
        subj = self.last().subject if subject is None else subject
        new_atom = AtomicClause(subject=subj,
                                property=property,
                                operator=operation,
                                argument=argument)
        new_select = Select().add(new_atom)
        return new_select


    def and_where(self,
                  operation: Comparison,
                  argument: Argument,
                  property: Property = None,
                  subject: Subject = None,
                  optional: bool = False,
                  project: bool = False) -> 'Select':
        new_atom = self._new_atom(operation, argument, property, subject, optional, project)
        last_component = self.last()
        if isinstance(last_component, AtomicClause):
            self.components = [ConjunctiveClause(components=[last_component, new_atom])]
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



class SelectQuery(BaseModel):
    prefixes: List[Tuple[str, str]] = Field(default_factory=lambda: DEFAULT_PREFIXES.copy())
    select: Select = Field(default_factory=Select)
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

    def where(self,
              subject: Subject,
              property: Property,
              operation: Comparison,
              argument: Argument,
              optional: bool = False,
              project: bool = False) -> 'Select':
        new_clause = AtomicClause(subject=subject,
                                  property=property,
                                  operator=operation,
                                  argument=argument,
                                  optional=optional,
                                  project=project)
        self.select.components.append(new_clause)
        return self.select



    # def add(self, clauses: Union[AnyClause, List[AnyClause]], **kwargs) -> None:
    #     if isinstance(clauses, List):
    #         clause_type = kwargs.get('type', 'conjunction')
    #         if clause_type == 'conjunction':
    #             list_clause = ConjunctiveClause(
    #                 clauses=clauses,
    #                 optional=kwargs.get('optional', False)
    #             )
    #         elif clause_type == 'union':
    #             list_clause = DisjunctiveClause(
    #                 subject=kwargs.get('subject'),
    #                 clauses=clauses
    #             )
    #         else:
    #             raise ValueError('unknown list clause type')
    #         self.clauses.append(list_clause)
    #     elif isinstance(clauses, AtomicClause) and clauses.method == Comparison.KEYWORD:
    #         self.clauses.insert(0, clauses)
    #     else:
    #         self.clauses.append(clauses)
    #
    # def clause(
    #     self,
    #     property: Union[Identifier, str],
    #     subject: Optional[Union[Identifier, Variable, str]] = None,
    #     argument: Optional[Union[str, int, float, Value, Identifier, Variable]] = None,
    #     variable: Optional[Union[Variable, str]] = None,
    #     method: Comparison = Comparison.ANY,
    #     project: bool = True,
    #     optional: bool = False
    # ) -> 'SelectQuery':
    #     if isinstance(property, str):
    #         property = Identifier(value=property)
    #
    #     if isinstance(subject, str):
    #         subject = Variable(value=subject) if subject.startswith('?') else Identifier(value=subject)
    #
    #     if argument and not isinstance(argument, (Value, Identifier, Variable)):
    #         argument = Value(value=argument)
    #
    #     if variable and not isinstance(variable, Variable):
    #         variable = Variable(value=variable)
    #
    #     atomic_clause = AtomicClause(
    #         property=property,
    #         subject=subject,
    #         argument=argument,
    #         variable=variable,
    #         method=method,
    #         project=project,
    #         optional=optional
    #     )
    #     self.add(atomic_clause)
    #     return self

    def project_clauses(self) -> List[AtomicClause]:
        def _project_clauses(c: BaseClause, _clauses: List[AtomicClause]) -> None:
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
        def _project_vars(c: BaseClause, _vars: List[str]) -> None:
            if isinstance(c, AtomicClause) and c.project:
                if c.arg_variable():
                    _vars.append(c.argument)
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

    def to_dict(self, **kwargs) -> dict:
        return self.model_dump(**kwargs)

class UnarySelectQuery(SelectQuery):
    subject: Subject = None
    kinds: Optional[List[Identifier]] = None


    @model_validator(mode='after')
    def setup(self) -> 'UnarySelectQuery':
        self.where(subject=self.subject,
                   property=RDF_TYPE,
                   operation=Comparison.EXACT,
                   argument=OWL_INDIVIDUAL)
        if self.kinds:
            # Add RDF type clause for the first kind
            self.select.and_where(subject=self.subject,
                property=RDF_TYPE,
                argument=Identifier(value=self.kinds[0]),
                operation=Comparison.EXACT,
                project=False
            )

            # Add union clause for additional kinds
            if len(self.kinds) > 1:
                for kind in self.kinds[1:]:
                    self.select.or_where(property=RDF_TYPE,
                         argument=Identifier(value=kind),
                         operation=Comparison.EXACT)

                # kind_union = DisjunctiveClause(subject=self.subject)
                # for kind in self.kinds[1:]:
                #     kind_union.add(AtomicClause(
                #         property=RDF_TYPE,
                #         argument=Identifier(value=kind),
                #         operator=Comparison.EXACT
                #     ))
                # self.add(kind_union)
        return self

    # def clause(
    #     self,
    #     property: Union[Identifier, str],
    #     subject: Optional[Union[Identifier, Variable, str]] = None,
    #     argument: Optional[Union[str, int, float, Value, Identifier, Variable]] = None,
    #     variable: Optional[Union[Variable, str]] = None,
    #     method: Comparison = Comparison.ANY,
    #     project: bool = True,
    #     optional: bool = False
    # ) -> 'UnarySelectQuery':
    #     if subject is None:
    #         subject = self.subject
    #     super().clause(
    #         property=property,
    #         subject=subject,
    #         argument=argument,
    #         variable=variable,
    #         method=method,
    #         project=project,
    #         optional=optional
    #     )
    #     return self
    #
    # def add_match_clause(
    #     self,
    #     predicate: Identifier,
    #     argument: Union[str, int, float, Value, Identifier],
    #     method: Comparison = Comparison.EXACT,
    #     project: bool = False,
    #     optional: bool = False
    # ) -> None:
    #     if not isinstance(argument, (Value, Identifier)):
    #         argument = Value(value=argument)
    #     self.add(AtomicClause(
    #         subject=self.subject,
    #         property=predicate,
    #         argument=argument,
    #         method=method,
    #         project=project,
    #         optional=optional
    #     ))
    #
    # def add_fetch_clause(
    #     self,
    #     predicate: Identifier,
    #     variable: Optional[Variable] = None
    # ) -> None:
    #     if variable is None:
    #         variable = Variable(value=str(random.randint(0, 1000000)))
    #     self.add(AtomicClause(
    #         subject=self.subject,
    #         property=predicate,
    #         variable=variable,
    #         method=Comparison.ANY,
    #         project=True,
    #         optional=True
    #     ))

    # def get_kinds(self) -> List[Identifier]:
    #     return [c.argument for c in self.atom_clauses()
    #             if isinstance(c, AtomicClause) and
    #             c.property == RDF_TYPE and
    #             isinstance(c.argument, Identifier)]
    #
    # def is_scored(self) -> bool:
    #     return any(isinstance(c, AtomicClause) and c.method == Comparison.KEYWORD
    #               for c in self.clauses)
    #
    # @classmethod
    # def new(cls, data: dict) -> 'UnarySelectQuery':
    #     return cls.model_validate(data)

