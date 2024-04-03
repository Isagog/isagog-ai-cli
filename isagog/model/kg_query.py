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
from typing import Protocol

from rdflib import RDF, RDFS, OWL, URIRef

DEFAULT_PREFIXES = [("rdf", "http://www.w3.org/2000/01/rdf-schema"),
                    ("rdfs", "http://www.w3.org/2001/XMLSchema"),
                    ("text", "http://jena.apache.org/text")]

# don't change this for the sake of back compatibility
_SUBJVAR = 'i'
_KINDVAR = 'k'
_SCOREVAR = 'score'


class Comparison(Enum):
    EXACT = "exact_match"
    KEYWORD = "keyword_search"
    REGEX = "regex"
    SIMILARITY = "similarity"
    GREATER = "greater_than"
    LESSER = "lesser_than"
    ANY = "any"


class Identifier(str):
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

    def __new__(cls, _id: str | URIRef):
        # Handle URIRef or string input
        if isinstance(_id, URIRef):
            value = str(_id)
        return super(Identifier, cls).__new__(cls, _id)

    def n3(self):
        return URIRef(self).n3()


# The following are predefined identifiers
RDF_TYPE = Identifier(RDF.type)
RDFS_LABEL = Identifier(RDFS.label)
OWL_CLASS = Identifier(OWL.Class)


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

    def __init__(self, value: str | int | float):
        if isinstance(value, str) and ((value.startswith("<") and value.endswith(">")) or value.startswith("?")):
            raise ValueError(f"Bad value string {value}")
        self.value = value

    def __str__(self) -> str:
        return str(self.value)


class Clause(object):
    """
    A selection clause
    """
    def __init__(self,
                 subject: Identifier | Variable | str = None,
                 optional=False):
        self.subject = subject
        self.optional = optional

    def to_dict(self, **kwargs) -> dict:
        pass

    def is_defined(self) -> bool:
        return self.subject is not None

    def from_dict(self, data: dict, **kwargs):
        pass


class Generator(Protocol):

    def __init__(self, language: str, version: str = None):
        self.language = language
        self.version = version

    def generate_query(self, query: SelectQuery, **kwargs) -> str:
        pass

    def generate_clause(self, clause: Clause, **kwargs) -> str:
        pass


class AtomicClause(Clause):
    """
    A single triple clause
    """

    @staticmethod
    def _instantiate_argument(arg) -> Value | Identifier | Variable:
        if isinstance(arg, Variable) or isinstance(arg, Identifier) or isinstance(arg, Value):
            return arg
        elif isinstance(arg, URIRef):
            return Identifier(arg)
        elif isinstance(arg, int) or isinstance(arg, float) or isinstance(arg, str):
            return Value(arg)
        else:
            arg = str(arg)
            if arg.startswith('?'):
                return Variable(arg)
            elif arg.startswith('<') or ':' in arg[:8]:
                return Identifier(arg)
            else:
                return Value(arg)

    @staticmethod
    def _instantiate_variable(variable) -> Variable:
        if isinstance(variable, Variable):
            return variable
        else:
            return Variable(variable)

    def n3(self) -> str:
        subj = self.subject.n3() if isinstance(self.subject, Identifier) else self.subject
        pred = self.property.n3() if isinstance(self.property, Identifier) else f"<{self.property}>"
        val = None
        if self.argument:
            val = self.argument.n3() if isinstance(self.argument, Identifier) else str(self.argument)
        elif self.variable:
            val = self.variable if isinstance(self.variable, Variable) else f"?{self.variable}"
        else:
            ValueError("Invalid clause")
        return f"{subj} {pred} {val}"

    def __init__(self,
                 subject: Identifier | Variable | str = None,
                 property: Identifier | str = None,  # no property variable allowed
                 argument: str | int | float | Value | Identifier | Variable = None,
                 variable: Variable | str = None,
                 method: Comparison = Comparison.ANY,
                 project=True,
                 optional=False):
        """

        :param subject:
        :param property:
        :param argument:
        :param variable:
        :param method:
        :param project:
        :param optional:
        """
        if subject and not isinstance(subject, Identifier) and not isinstance(subject, str):
            raise ValueError("Invalid subject")
        if property and not isinstance(property, Identifier) and not isinstance(property, str):
            raise ValueError("Invalid property")
        super().__init__(subject=subject, optional=optional)

        self.subject = subject
        if self.subject and isinstance(subject, str):
            self.subject = Variable(subject) if subject.startswith("?") else Identifier(subject)
        self.property = property if property and isinstance(property, Identifier) \
            else Identifier(property) if property \
            else None
        self.argument = self._instantiate_argument(argument) if argument else None
        self.variable = self._instantiate_variable(variable) if variable else None
        self.method = method
        self.project = project

    def is_defined(self) -> bool:
        return (self.subject is not None
                and self.property is not None
                and (self.argument is not None or self.variable is not None))

    def to_dict(self, **kwargs) -> dict:
        out = {
            'type': 'atomic',
            'property': self.property,
            'method': self.method.value,
            'project': self.project,
            'optional': self.optional
        }
        if self.subject:
            out['subject'] = self.subject
        if self.argument:
            if isinstance(self.argument, Value):
                out['value'] = self.argument
            elif isinstance(self.argument, Variable):
                out['variable'] = self.argument
            else:
                out['identifier'] = self.argument
        if self.variable:
            out['variable'] = self.variable

        return out

    def from_dict(self, data: dict, **kwargs):
        """
        Openapi spec:  components.schemas.Clause
        """
        subject = kwargs.get('subject')  #: Variable | Identifier,
        version = kwargs.get('version', 'latest')

        if subject == "query.subject":
            subject = Variable(_SUBJVAR)
        elif subject and not (
                isinstance(subject, Variable)
                or isinstance(subject, Identifier)
        ):
            if Identifier.is_valid_id(str(subject)):
                subject = Identifier(str(subject))
            elif Variable.is_valid_variable_value(str(subject)):
                subject = Variable(str(subject))
            else:
                raise ValueError(f"Invalid subject {subject}")

        self.subject = subject

        for key, val in data.items():
            match key:
                case 'type':
                    if val != 'atomic':
                        raise ValueError("wrong clause type")
                case 'property':
                    self.property = Identifier(val)
                case 'subject':
                    # the subject should be already in plase
                    if self.subject:
                        pass
                    else:
                        self.subject = Identifier(val) if Identifier.is_valid_id(val) \
                            else Variable(val) if Variable.is_valid_variable_id(val) \
                            else None
                        if not self.subject:
                            raise ValueError(f"Invalid subject value {val}")
                case 'variable':
                    if val == "query.subject":
                        self.variable = Variable(_SUBJVAR)  # the query subject
                    else:
                        self.variable = Variable(val)
                    if self.argument is None:
                        self.argument = self.variable
                case 'argument' | 'identifier':  # for compatibility
                    self.argument = Identifier(val) if Identifier.is_valid_id(val) \
                        else Variable(val) if Variable.is_valid_variable_id(val) \
                        else Value(val)
                case 'value':
                    self.argument = Value(val)
                # case 'identifier':
                #     self.argument = Identifier(val)
                case 'method':
                    self.method = Comparison(val)
                case 'project':
                    self.project = bool(val)
                case 'optional':
                    self.optional = bool(val)
                case _:
                    raise ValueError(f"Invalid clause key {key}")


class CompositeClause(Clause):
    """
        A list of atomic clauses
    """

    def __init__(self,
                 subject: Identifier | Variable = None,
                 clauses: list[Clause] = None,
                 optional=False
                 ):
        super().__init__(subject=subject if subject else Variable(),
                         optional=optional)

        if not clauses:
            clauses = list[Clause]()

        self.clauses = clauses

    def add_atom(self,
                 property: Identifier,
                 argument: Value | Variable | Identifier,
                 method=Comparison.EXACT,
                 project=False,
                 optional=False):
        self.clauses.append(AtomicClause(subject=self.subject,
                                         property=property,
                                         argument=argument,
                                         method=method,
                                         project=project,
                                         optional=optional))

    def add_clause(self, clause: Clause):
        self.clauses.append(clause)


class ConjunctiveClause(CompositeClause):
    """
    A list of atomic clauses which are evaluated in 'and'
    """

    def __init__(self,
                 clauses: list[Clause] = None,
                 optional=False):
        super().__init__(clauses=clauses,
                         optional=optional)

    # def to_sparql(self) -> str:
    #     """
    #     Deprecated
    #     :return:
    #     """
    #     from isagog.generator.sparql_generator import _SPARQLGEN
    #     return _SPARQLGEN.generate_clause(self)

    def to_dict(self, **kwargs) -> dict:
        out = {
            'type': 'conjunction',
            'clauses': [c.to_dict() for c in self.clauses]
        }

        match kwargs.get('version', 'latest'):
            case "latest":
                out['type'] = "conjunction"
            case "v1.0.0":
                pass

        if self.optional:
            out['optional'] = True

        return out

    def from_dict(self, data: dict, **kwargs):

        version = kwargs.get('version', 'latest')
        self.subject = kwargs.get('subject')  #: Variable | Identifier,
        self.optional = bool(data.get('optional', False))
        for atom_dict in data.get('clauses', []):
            atom = AtomicClause()
            subject = atom_dict.get('subject', self.subject)
            atom.from_dict(data=atom_dict, subject=subject)
            self.clauses.append(atom)


class DisjunctiveClause(CompositeClause):
    """
    A list of atomic clauses on the same subject, which are evaluated in 'or'
    """

    def __init__(self,
                 subject: Identifier | Variable = None,
                 clauses: list[AtomicClause] = None
                 ):
        super().__init__(subject, clauses)

        if not self._validate_union_clauses(clauses):
            raise ValueError("Invalid union clauses")

    @staticmethod
    def _validate_union_clauses(clauses: list[AtomicClause]) -> bool:
        if not clauses:
            return True
        subject = clauses[0].subject
        return all(clause.subject == subject for clause in clauses)

    def to_sparql(self) -> str:
        from isagog.generator.sparql_generator import _SPARQLGEN
        return _SPARQLGEN.generate_clause(self)

    def to_dict(self, **kwargs) -> dict:
        out = {
            'type': 'union',
            'subject': self.subject,
            'clauses': [c.to_dict() for c in self.clauses]
        }

        return out

    def from_dict(self, data: dict, **kwargs):
        subject = kwargs.get('subject', self.subject)
        for atom_dict in data.get('clauses', []):
            atom = AtomicClause()
            atom.from_dict(data=atom_dict,
                           subject=atom_dict.get('subject', subject))
            self.clauses.append(atom)


class SelectQuery(object):
    """
    A selection query
    """

    def __init__(self,
                 prefixes: list[(str, str)],
                 clauses: list[Clause],
                 graph: str,
                 limit: int,
                 lang: str,
                 min_score: float
                 ):
        """
        Buils a selecion query
        @param clauses: a list of selection clauses
        """

        if prefixes is None:
            prefixes = DEFAULT_PREFIXES
        self.prefixes = prefixes
        self.clauses = list[Clause]()
        if clauses:
            for c in clauses:
                self.clauses.append(c)
        self.graph = graph
        self.limit = limit
        self.lang = lang
        self.min_score = min_score

    def add(self, clauses: Clause | list[Clause], **kwargs):
        if isinstance(clauses, list):
            match kwargs.get('type', 'conjunction'):
                case 'conjunction':
                    list_clause = ConjunctiveClause(clauses, optional=kwargs.get('optional', False))
                case 'union':
                    list_clause = DisjunctiveClause(subject=kwargs.get('subject'), clauses=clauses)
                case _:
                    raise ValueError('unknown list clause type')
            self.clauses.append(list_clause)
        elif isinstance(clauses, AtomicClause) and clauses.method == Comparison.KEYWORD:
            self.clauses.insert(0, clauses)
        else:
            self.clauses.append(clauses)

    def clause(self,
               property: Identifier | str,
               subject: Identifier | Variable | str = None,
               argument: str | int | float | Value | Identifier | Variable = None,
               variable: Variable | str = None,
               method: Comparison = Comparison.ANY,
               project=True,
               optional=False) -> SelectQuery:
        """
        Constructs and adds an atomic
        :param property:
        :param subject:
        :param argument:
        :param variable:
        :param method:
        :param project:
        :param optional:
        :return:
        """
        atomic_clause = AtomicClause(property=property,
                                     subject=subject,
                                     argument=argument,
                                     variable=variable,
                                     method=method,
                                     project=project,
                                     optional=optional)
        # clause_obj.from_dict(kwargs)
        self.add(atomic_clause)
        return self

    def project_clauses(self) -> list[AtomicClause]:
        return [c for c in self.clauses if isinstance(c, AtomicClause) and c.project]

    def project_vars(self) -> set[str]:
        """
        Selects all the projectes arguments
        """
        _vars = []
        for c in self.clauses:
            if isinstance(c, AtomicClause) and c.project:
                if c.variable and not c.argument:
                    _vars.append(c.variable)
                elif isinstance(c.argument, Variable):
                    _vars.append(c.argument)
                if isinstance(c.subject, Variable):
                    _vars.append(c.subject)
        return set(_vars)

    def has_return_vars(self) -> bool:
        return len(self.project_vars()) > 0

    # def to_sparql(self) -> str:
    #     """
    #     This method is deprecated and will be removed in a future version.
    #
    #     Use generate_query with a SPARQL generator instead.
    #     """
    #     raise NotImplementedError()

    def generate(self, generator: Generator) -> str:
        return generator.generate_query(self)

    def to_dict(self, version: str = None) -> dict:
        pass


class UnarySelectQuery(SelectQuery):
    """
    Select query about a single subject

    """

    @staticmethod
    def _new_id(id_obj) -> Variable | Identifier:
        if isinstance(id_obj, Identifier) or isinstance(id_obj, Variable):
            return id_obj
        else:
            id_obj = str(id_obj)
            if id_obj.startswith("?"):
                return Variable(id_obj)
            else:
                return Identifier(id_obj)

    def __init__(self,
                 subject: Variable | Identifier = None,
                 kinds: list[str] = None,
                 prefixes: list[(str, str)] = None,
                 clauses: list[Clause] = None,
                 graph="defaultGraph",
                 limit=-1,
                 lang="en",
                 min_score=None,
                 ):
        """
        Buils a unary selection query
        @param subject: the query subject, defaults to an inner variable
        @param kinds: the subject's kinds
        @param clauses: a list of selection clauses
        @param graph: the graph name, defaults to 'defaultGraph'
        @param limit: the result limit, defaults to -1 (no limits
        @param lang: the result language, defaults to 'en'
        @param min_score: the minimum result score, defaults to no none
        """
        super().__init__(
            prefixes=prefixes,
            clauses=clauses,
            graph=graph,
            limit=limit,
            lang=lang,
            min_score=min_score,
        )

        if subject:
            self.subject = self._new_id(subject)
        else:
            self.subject = Variable(_SUBJVAR)

        if kinds:
            self.add(AtomicClause(subject=self.subject,
                                  property=RDF_TYPE,
                                  argument=Variable(_KINDVAR),
                                  project=True))
            self.add_kinds(kinds)

    def add(self, clauses: Clause | list[Clause], **kwargs):
        if isinstance(clauses, Clause):
            if clauses.subject is None:
                clauses.subject = self.subject
        super().add(clauses, **kwargs)

    def clause(self,
               property: Identifier | str,
               subject: Identifier | Variable | str = None,
               argument: str | int | float | Value | Identifier | Variable = None,
               variable: Variable | str = None,
               method: Comparison = Comparison.ANY,
               project=True,
               optional=False) -> SelectQuery:
        if subject is None:
            subject = self.subject
        return super().clause(property=property,
                              subject=subject,
                              argument=argument,
                              variable=variable,
                              method=method,
                              project=project,
                              optional=optional)

    def add_kinds(self, kind_refs: list[str]):
        if not kind_refs:
            return

        self.add(AtomicClause(subject=self.subject,
                              property=RDF_TYPE,
                              argument=Identifier(kind_refs[0]),
                              method=Comparison.EXACT,
                              project=False,
                              optional=False))

        if len(kind_refs) > 1:
            kind_union = DisjunctiveClause(subject=self.subject)
            for kind in kind_refs[1:]:
                kind_union.add_atom(property=RDF_TYPE, argument=Identifier(kind), method=Comparison.EXACT)
            self.add(kind_union)

    def add_match_clause(self, predicate, argument, method=Comparison.EXACT, project=False, optional=False):
        self.add(
            AtomicClause(property=predicate, argument=argument, method=method, project=project, optional=optional))

    def add_fetch_clause(self, predicate):
        self.add(AtomicClause(property=predicate, method=Comparison.ANY, project=True, optional=True))

    def from_dict(self, data: dict):
        """
           Openapi spec:  components.schemas.Clause
        """
        try:
            for key, val in data.items():
                match key:
                    case 'subject':
                        self.subject = self._new_id(val)
                    case 'kind' | 'kinds':  # backward compatibility w 0.7
                        self.add_kinds(val)
                    case 'clauses':
                        for clause_data in val:
                            match clause_data.get('type'):
                                case 'atomic':
                                    clause = AtomicClause()
                                case 'union':
                                    clause = DisjunctiveClause()
                                case 'conjunction':
                                    clause = ConjunctiveClause()
                                case _:
                                    if 'clauses' in clause_data:
                                        # if not otherwise specified, assume a conjunction
                                        clause = ConjunctiveClause()
                                    else:
                                        clause = AtomicClause()
                            subject = clause_data.get('subject', self.subject)
                            clause.from_dict(data=clause_data, subject=subject)
                            self.add(clause)
                    case 'graph':
                        self.graph = str(val)
                    case 'limit':
                        self.limit = int(val)
                    case 'lang':
                        self.lang = str(val)
                    case 'min_score' | 'minScore':  # backward compatibility
                        self.min_score = float(val)
                    case 'dataset':
                        pass
                    case _:
                        logging.error("Illegal key %s", key)
        except Exception as e:
            raise ValueError(f"Malformed query due to: {e}")

    # def to_sparql(self) -> str:
    #     """
    #     Deprecated
    #     :return:
    #
    #     """
    #     from isagog.generator.sparql_generator import _SPARQLGEN
    #
    #     return _SPARQLGEN.generate_query(self)

    def to_dict(self, version=None) -> dict:

        out = {}
        if version is None or version > "1.0.0":
            out['subject'] = self.subject

        out['clauses'] = [c.to_dict(version=version) for c in self.clauses]
        out['graph'] = self.graph
        out['limit'] = self.limit
        out['lang'] = self.lang
        if self.min_score:
            out['min_score'] = self.min_score
        return out

    def atom_clauses(self) -> list[AtomicClause]:
        return [c for c in self.clauses if isinstance(c, AtomicClause)]

    def conjunctive_clauses(self) -> list[ConjunctiveClause]:
        return [c for c in self.clauses if isinstance(c, ConjunctiveClause)]

    def disjunctive_clauses(self) -> list[DisjunctiveClause]:
        return [c for c in self.clauses if isinstance(c, DisjunctiveClause)]

    def has_disjunctive_clauses(self):
        return len(self.disjunctive_clauses()) > 0

    def has_conjunctive_clauses(self):
        return len(self.conjunctive_clauses()) > 0

    @classmethod
    def new(cls, rdata: dict) -> UnarySelectQuery:
        q = UnarySelectQuery()
        q.from_dict(rdata)
        return q

    def is_scored(self) -> bool:
        return next(filter(lambda c: isinstance(c, AtomicClause) and c.method == Comparison.KEYWORD, self.clauses),
                    None) is not None

    def get_kinds(self) -> list[Identifier]:
        atom_clauses = self.atom_clauses()
        rt = []
        for c in atom_clauses:
            if c.property == RDF_TYPE and isinstance(c.argument, Identifier):
                rt.append(c.argument)
        return rt

    def atom_property_clauses(self) -> list[AtomicClause]:
        return [c for c in self.atom_clauses() if c.property != RDF_TYPE]

    # def property_clauses(self):
    #     return self.atom_property_clauses() + self.disjunctive_clauses()
