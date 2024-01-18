"""
KG Query module
"""
import logging
import random
import re
from enum import Enum
from typing import Protocol

from rdflib import RDF, RDFS, OWL, URIRef


DEFAULT_PREFIXES = [("rdf", "http://www.w3.org/2000/01/rdf-schema"),
                    ("rdfs", "http://www.w3.org/2001/XMLSchema"),
                    ("text", "http://jena.apache.org/text")]

_SUBJVAR = '_subj'
_KINDVAR = '_kind'
_SCOREVAR = '_score'

"""
  Support deprecated methods
"""


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


class AtomicClause(Clause):

    @staticmethod
    def _instantiate_argument(arg) -> Value | Identifier | Variable:
        if isinstance(arg, Variable) or isinstance(arg, Identifier) or isinstance(arg, Value):
            return arg
        elif isinstance(arg, URIRef):
            return Identifier(arg)
        elif isinstance(arg, int) or isinstance(arg, float):
            return Value(arg)
        else:
            arg = str(arg)
            if arg.startswith('?'):
                return Variable(arg)
            elif arg.startswith('<') or ':' in arg[:8]:
                return Identifier(arg)
            else:
                return Value(arg)

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
                 subject: Identifier | Variable = None,
                 property: Identifier = None,  # no property variable allowed
                 argument: Value | Identifier | Variable = None,
                 variable: Variable = None,
                 method: Comparison = Comparison.ANY,
                 project=True,
                 optional=False):
        """
        A select clause

        """

        super().__init__(subject=subject, optional=optional)

        self.subject = subject
        if self.subject and isinstance(subject, str):
            self.subject = Variable(subject) if subject.startswith("?") else Identifier(subject)
        self.property = property
        self.argument = self._instantiate_argument(argument) if argument else variable if variable else None
        self.variable = variable  # else argument  # argument's variable
        self.method = method
        self.project = project

    def is_defined(self) -> bool:
        return self.subject and self.property and (self.argument or self.variable)

    def to_sparql(self) -> str:
        """
        Deprecated
        Generates the sparql triple clause
        """
        from isagog.generator.sparql_generator import _SPARQLGEN

        return _SPARQLGEN.generate_clause(self)

    def to_dict(self, **kwargs) -> dict:
        out = {
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

        match kwargs.get('version', 'latest'):
            case 'latest':
                out['type'] = "atomic"
            case "v1.0.0":
                pass

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

    def add_atomic_clause(self,
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

    def to_sparql(self) -> str:
        """
        Deprecated
        :return:
        """
        from isagog.generator.sparql_generator import _SPARQLGEN
        return _SPARQLGEN.generate_clause(self)

    def to_dict(self, **kwargs) -> dict:
        out = {
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
            'subject': self.subject,
            'clauses': [c.to_dict() for c in self.clauses]
        }

        match kwargs.get('version', "latest"):
            case "latest":
                out['type'] = "union"
            case "v1.0.0":
                pass

        return out

    def from_dict(self, data: dict, **kwargs):
        subject = kwargs.get('subject', self.subject)
        for atom_dict in data.get('clauses', []):
            atom = AtomicClause()
            atom.from_dict(data=atom_dict,
                           subject=atom_dict.get('subject', subject))
            self.clauses.append(atom)


class SelectQuery(Query):
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

    def add(self, clause: Clause | list[Clause] = None, **kwargs) -> Query:
        assert (clause or kwargs)
        if clause is None:
            match kwargs.get('type', 'atomic'):
                case 'atomic':
                    clause_obj = AtomicClause()
                case 'union':
                    clause_obj = DisjunctiveClause()
                case 'conjunction':
                    clause_obj = ConjunctiveClause()
                case _:
                    raise ValueError('unknown clause type')
            clause_obj.from_dict(kwargs)
            clause = clause_obj
        if isinstance(clause, list):
            match kwargs.get('type', 'conjunction'):
                case 'conjunction':
                    list_clause = ConjunctiveClause(clause, optional= kwargs.get('optional', False))
                case 'union':
                    list_clause = DisjunctiveClause(subject=kwargs.get('subject'), clauses=clause)
                case _ :
                    raise ValueError('unknown list clause type')
            return self.add(list_clause)
        elif isinstance(clause, AtomicClause) and clause.method == Comparison.KEYWORD:
            self.clauses.insert(0, clause)
        else:
            self.clauses.append(clause)
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
                if isinstance(c.argument, Variable):
                    _vars.append(c.argument)
                if isinstance(c.subject, Variable):
                    _vars.append(c.subject)
        return set(_vars)

    def has_return_vars(self) -> bool:
        return len(self.project_vars()) > 0

    def to_sparql(self) -> str:
        """
        This method is deprecated and will be removed in a future version.

        Use generate_query with a SPARQL generator instead.
        """
        raise NotImplementedError()

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
                 prefixes: dict = None,
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

    def add(self, clause: Clause | list = None, **kwargs) -> Query:
        if isinstance(clause, list):
            return super(clause, **kwargs)
        if clause and clause.subject is None:
            clause.subject = self.subject
        if kwargs and 'subject' not in kwargs:
            kwargs['subject'] = self.subject
        return super().add(clause, **kwargs)

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
                kind_union.add_atomic_clause(property=RDF_TYPE, argument=Identifier(kind), method=Comparison.EXACT)
            self.add(kind_union)

    def add_match_clause(self, predicate, argument, method=Comparison.EXACT, project=False, optional=False):
        self.add(AtomicClause(property=predicate, argument=argument, method=method, project=project, optional=optional))

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
                    case 'kinds':
                        self.add_kinds(val)
                    case 'clauses':
                        for clause_data in val:
                            match clause_data.get('type', 'atomic'):
                                case 'atomic':
                                    clause = AtomicClause()
                                case 'union':
                                    clause = DisjunctiveClause()
                                case 'conjunction':
                                    clause = ConjunctiveClause()
                                case _:
                                    raise ValueError(f"Clause type unknown")
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

    def to_sparql(self) -> str:
        """
        Deprecated
        :return:

        """
        from isagog.generator.sparql_generator import _SPARQLGEN

        return _SPARQLGEN.generate_query(self)

        # strio = StringIO()
        # for (name, uri) in self.prefixes:
        #     strio.write(f"PREFIX {name}: <{uri}#>\n")
        #
        # strio.write("SELECT distinct ")  # {self.subject}")
        # for rv in self.project_vars():
        #     strio.write(f" {rv} ")
        # if self.is_scored():
        #     strio.write(f" ?{_SCOREVAR} ")
        # strio.write(" WHERE {\n")
        # if self.has_disjunctive_clauses():
        #     strio.write("\t{\n")
        #     for clause in self.atom_clauses():
        #         strio.write("\t\t" + clause.to_sparql())
        #     for clause in self.conjunctive_clauses():
        #         strio.write("\t\t" + clause.to_sparql())
        #
        #     strio.write("\t}\n")
        #
        #     for clause in self.disjunctive_clauses():
        #         strio.write(clause.to_sparql())
        #     # strio.write("\t}\n")
        # else:
        #     for clause in self.clauses:
        #         strio.write("\t" + clause.to_sparql())
        #
        # if self.min_score:
        #     strio.write(f'\tFILTER (?{_SCOREVAR} >= {self.min_score})\n')
        #
        # strio.write("}\n")
        # if self.is_scored():
        #     strio.write(f"ORDER BY DESC(?{_SCOREVAR})\n")
        # if self.limit > 0:
        #     strio.write(f"LIMIT {self.limit}\n")
        #
        # return strio.getvalue()

    def to_dict(self, version="latest") -> dict:

        out = {}
        if version == "latest" or version > "v1.0.0":
            out['subject'] = self.subject

        # kinds = self.get_kinds()
        # if len(kinds) > 0:
        #     out["kinds"] = kinds
        # out["clauses"] = [c.to_dict(version) for c in self.property_clauses()]
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
    def new(cls, rdata: dict) -> SelectQuery:
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

    def property_clauses(self):
        return self.atom_property_clauses() + self.disjunctive_clauses()
