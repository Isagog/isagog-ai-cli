"""
KG Query module
"""
import random
import re
from enum import Enum
from io import StringIO

from rdflib import RDF, RDFS, OWL, URIRef


class Identifier(URIRef):
    """
    Must be an uri string, possibly prefixed
    """

    def __new__(cls, value: str | URIRef):
        return super().__new__(cls, value)

    def __str__(self):
        return f"<{super().__str__()}>"


class Variable(str):
    """
    Can be an uri or a variable name
    """

    def __new__(cls, value=None):
        if not value:
            value = random.randint(1, 100000)
        if not (isinstance(value, str) or isinstance(value, int)):
            raise ValueError(f"Bad variable type {value}")
        if isinstance(value, int):
            return super().__new__(cls, f'?tmp_{value}')

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


class Value(object):
    """
    Can be a string or a number
    """

    def __init__(self, value):
        if isinstance(value, str) and (value.startswith("<") and value.endswith(">")) or value.startswith("?"):
            raise ValueError(f"Bad value string {value}")
        self.value = value

    def __str__(self) -> str:
        if isinstance(self.value, str):
            return f"'{self.value}'"
        return str(self.value)


class Comparison(Enum):
    EXACT = "exact_match"
    KEYWORD = "keyword_search"
    REGEX = "regex"
    SIMILARITY = "similarity"
    GREATER = "greater_than"
    LESSER = "lesser_than"
    ANY = "any"


RDF_TYPE = Identifier(RDF.type)
RDFS_LABEL = Identifier(RDFS.label)
OWL_CLASS = Identifier(OWL.Class)
DEFAULT_PREFIXES = [("rdf", "http://www.w3.org/2000/01/rdf-schema"),
                    ("rdfs", "http://www.w3.org/2001/XMLSchema"),
                    ("text", "http://jena.apache.org/text")]


class Clause(object):

    def __init__(self, subject: Identifier | Variable = None):
        self.subject = subject
        self.predicate = None
        self.argument = None

    def to_sparql(self) -> str:
        pass

    def to_dict(self) -> dict:
        pass

    def is_defined(self) -> bool:
        return self.subject is not None

    def from_dict(self, subject: Variable | Identifier, data: dict):
        pass


def _validate_clause_data(data: dict) -> (bool, str):
    if "property" not in data:
        return False, "Property missing"
    return True, ""


class AtomClause(Clause):

    def __init__(self,
                 subject: Identifier | Variable = None,
                 predicate: Identifier = None,  # no predicate variable allowed
                 argument: Value | Variable | Identifier = None,
                 #     variable: Variable = None,
                 method: Comparison = Comparison.ANY,
                 project=False,
                 optional=False):
        """
        A select clause

        """
        super().__init__(subject)

        self.predicate = predicate if predicate and isinstance(predicate, Identifier) \
            else Identifier(predicate) if predicate else None
        self.argument = argument if argument else Variable()
        # variable  # binary predicate's second argument
        #    self.variable = variable if variable else argument  # argument's variable
        self.method = method
        self.project = project
        self.optional = optional
        self._temp_vars = 0

    def is_defined(self) -> bool:
        return self.subject is not None and self.predicate is not None and self.argument is not None

    def to_sparql(self) -> str:
        """
        Generates the sparql triple clause
        """
        if not self.is_defined():
            raise ValueError(f"Clause not defined {self.subject} {self.predicate} {self.argument}")

        clause = ""

        match self.method:
            case Comparison.EXACT | Comparison.ANY:
                clause += f"{self.subject} {self.predicate} {self.argument}"
            case Comparison.REGEX:
                tmp_var = self._temp_var()
                clause = f"{self.subject} {self.predicate} {tmp_var}\n"
                clause += f'\t\tFILTER  regex({tmp_var}, {self.argument}, "i")'
            case Comparison.KEYWORD:
                clause += f'({self.subject} ?score) text:query {self.argument}'
            case Comparison.GREATER:
                var = self.variable if self.variable else self._temp_var()
                clause += f"{self.subject} {self.predicate} {var}\n"
                clause += f'\t\tFILTER ({var} > {self.argument})'
            case Comparison.LESSER:
                var = self._temp_var()
                clause += f'{self.subject} {self.predicate} {var}\n'
                clause += f'FILTER ({var} < {self.argument})'
            case _:
                raise ValueError(self.method)

        if self.optional:
            clause = f"OPTIONAL {{ {clause} }}\n"
        else:
            clause += " .\n"

        return clause

    def to_dict(self) -> dict:
        out = {
            'property': self.predicate,
            'method': self.method.value,
            'project': self.project,
            'optional': self.optional
        }
        if isinstance(self.argument, Value):
            out['value'] = self.argument
        else:
            out['variable'] = self.argument

        return out

    def from_dict(self, subject: Variable | Identifier, data: dict):
        """
        Openapi spec:  components.schemas.Clause
        """

        self.subject = subject
        for key, val in data.items():
            match key:
                case 'property':
                    self.predicate = Identifier(val)
                case 'value':
                    self.argument = Value(val)
                    self.variable = self._temp_var()
                case 'identifier':
                    self.argument = Identifier(val)
                case 'variable':
                    self.variable = Variable(val)
                    if not self.argument:
                        self.argument = self.variable
                case 'method':
                    self.method = Comparison(val)
                case 'project':
                    self.project = bool(val)
                case 'optional':
                    self.optional = bool(val)
                case _:
                    raise ValueError(f"Invalid clause key {key}")

    def _temp_var(self) -> Variable:
        self._temp_vars += 1
        return Variable(self._temp_vars)

    @classmethod
    def new(cls, subject: Variable, rdata: dict) -> Clause:
        c = AtomClause()
        c.from_dict(subject, rdata)
        return c


class UnionClause(Clause):

    def __init__(self, subject: Identifier | Variable = None):
        super().__init__(subject if subject else Variable())
        self.sub_clauses = list[AtomClause]()

    def add_constraint(self, predicate: Identifier, argument: Value | Variable | Identifier, method=Comparison.EXACT):
        self.sub_clauses.append(AtomClause(self.subject, predicate, argument, method))

    def to_sparql(self) -> str:
        match len(self.sub_clauses):
            case 0:
                return ""
            case 1:
                return self.sub_clauses[0].to_sparql()
            case _:
                strio = StringIO()
                strio.write("UNION {\n")
                for constraint in self.sub_clauses:
                    strio.write("\t\t" + constraint.to_sparql())
                strio.write("\t}\n")
                return strio.getvalue()


class SelectQuery(object):
    """
    A selection query
    """

    def __init__(self,
                 dataset: str,
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
        self.dataset = dataset
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

    def add(self, clause: Clause):
        if isinstance(clause, AtomClause) and clause.method == Comparison.KEYWORD:
            self.clauses.insert(0, clause)
        else:
            self.clauses.append(clause)

    def project_clauses(self) -> list[AtomClause]:
        return [c for c in self.clauses if isinstance(c, AtomClause) and c.project]

    def project_vars(self) -> set[str]:
        """
        Selects all the projectes arguments
        """
        _vars = []
        for c in self.clauses:
            if isinstance(c.subject, Variable):
                _vars.append(c.subject)
            if isinstance(c, AtomClause) and c.project:
                _vars.append(c.argument)
        return set(_vars)

    #    return set([c.argument for c in self.project_clauses() if isinstance(c.argument, Variable)])

    def has_return_vars(self) -> bool:
        return len(self.project_vars()) > 0

    def to_sparql(self) -> str:
        pass

    def to_dict(self) -> dict:
        pass


class UnarySelectQuery(SelectQuery):
    """
    Select query about a single subject
    By convention, the first variable is the subject, others are subject's attributes and relations
    """

    def __init__(self,
                 subject=None,
                 dataset=None,
                 prefixes=None,
                 clauses: list[AtomClause] = None,
                 graph="defaultGraph",
                 limit=-1,
                 lang="en",
                 min_score=None,
                 ):
        """
        Buils a unary selection query
        @param clauses: a list of selection clauses
        """
        super().__init__(
            dataset=dataset,
            prefixes=prefixes,
            clauses=clauses,
            graph=graph,
            limit=limit,
            lang=lang,
            min_score=min_score,
        )

        if subject:
            self.subject = subject if isinstance(subject, Identifier) else Identifier(subject)
        else:
            self.subject = Variable("i")

    def add(self, clause: Clause):
        if clause.subject is None:
            clause.subject = self.subject
        super().add(clause)

    def add_kinds(self, kind_refs: list[str]):
        self.add(AtomClause(subject=self.subject,
                            predicate=RDF_TYPE,
                            argument=Variable("k"),
                            project=True))
        if len(kind_refs) == 1:
            self.add(AtomClause(self.subject,
                                RDF_TYPE,
                                Identifier(kind_refs[0]),
                                method=Comparison.EXACT,
                                project=False,
                                optional=False))
        elif len(kind_refs) > 1:
            kind_union = UnionClause(self.subject)
            for kind in kind_refs:
                kind_union.add_constraint(RDF_TYPE, Identifier(kind), method=Comparison.EXACT)
            self.add(kind_union)

    def add_match_clause(self, predicate, argument, method=Comparison.EXACT, project=False, optional=False):
        self.add(AtomClause(predicate=predicate, argument=argument, method=method, project=project, optional=optional))

    def add_fetch_clause(self, predicate):
        self.add(AtomClause(predicate=predicate, method=Comparison.ANY, project=True, optional=True))

    def from_dict(self, data: dict):
        """
           Openapi spec:  components.schemas.Clause
        """
        try:
            for key, val in data.items():
                match key:
                    case 'kinds':
                        self.add_kinds(val)
                    case 'clauses':
                        for clause_data in val:
                            valid, reason = _validate_clause_data(clause_data)
                            if valid:
                                clause = AtomClause()
                                clause.from_dict(subject=self.subject, data=clause_data)
                                self.add(clause)
                            else:
                                raise ValueError(reason)
                    case 'graph':
                        self.graph = str(val)
                    case 'limit':
                        self.limit = int(val)
                    case 'lang':
                        self.lang = str(val)
                    case 'min_score' | 'minScore':  # backward compatibility
                        self.min_score = float(val)
                    case _:
                        raise ValueError(f"Illegal key {key}")
        except Exception as e:
            raise ValueError(f"Malformed query due to: {e}")

    def to_sparql(self) -> str:

        strio = StringIO()
        for (name, uri) in self.prefixes:
            strio.write(f"PREFIX {name}: <{uri}#>\n")

        strio.write("SELECT distinct ")  # {self.subject}")
        for rv in self.project_vars():
            strio.write(f" {rv} ")
        if self.is_scored():
            strio.write(f" ?score ")
        strio.write(" WHERE {\n")
        if self.has_unions():
            strio.write("\t{\n")
            for clause in self.atom_clauses():
                strio.write("\t\t" + clause.to_sparql())
            strio.write("\t}\n")
            for clause in self.union_clauses():
                strio.write(clause.to_sparql())
        else:
            for clause in self.clauses:
                strio.write("\t" + clause.to_sparql())

        if self.min_score:
            strio.write(f'\tFILTER (?score >= {self.min_score})\n')

        strio.write("}\n")
        if self.is_scored():
            strio.write("ORDER BY DESC(?score)\n")
        if self.limit > 0:
            strio.write(f"LIMIT {self.limit}\n")

        return strio.getvalue()

    def to_dict(self) -> dict:
        out = {
            'subject': self.subject,
        }

        kinds = self.get_kinds()
        if len(kinds) > 0:
            out["kinds"] = kinds
        if self.dataset:
            out["dataset"] = self.dataset
        out["clauses"] = [c.to_dict() for c in self.get_atom_clauses()]
        out['graph'] = self.graph
        out['limit'] = self.limit
        out['lang'] = self.lang
        if self.min_score:
            out['min_score'] = self.min_score
        return out

    def atom_clauses(self) -> list[AtomClause]:
        return [c for c in self.clauses if isinstance(c, AtomClause)]

    def has_unions(self):
        return len(self.union_clauses()) > 0

    def union_clauses(self) -> list[UnionClause]:
        return [c for c in self.clauses if isinstance(c, UnionClause)]

    @classmethod
    def new(cls, rdata: dict) -> SelectQuery:
        q = UnarySelectQuery()
        q.from_dict(rdata)
        return q

    def is_scored(self) -> bool:
        return next(filter(lambda c: c.method == Comparison.KEYWORD, self.clauses), None) is not None

    def get_kinds(self) -> list[Identifier]:
        return [c.argument for c in self.atom_clauses() if c.predicate == RDF_TYPE]

    def get_atom_clauses(self) -> list[AtomClause]:
        return [c for c in self.atom_clauses() if c.predicate != RDF_TYPE]
