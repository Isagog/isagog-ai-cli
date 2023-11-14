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

    @staticmethod
    def is_valid_uri(uri_string):
        try:
            # Try to create a URIRef object from the string
            URIRef(uri_string)
            return True
        except Exception:
            # If an exception is raised, the string is not a valid URI
            return False

    def __new__(cls, value: str | URIRef):
        return super().__new__(cls, value)

    # def __str__(self):
    #     return f"<{super().__str__()}>"

    # def __eq__(self, other):
    #     if isinstance(other, URIRef):
    #         return
    #     else:
    #         return str(self) == str(other)


class Variable(str):
    """
    Can be an uri or a variable name
    """

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

    @staticmethod
    def is_valid_variable(var_string):
        try:
            # Try to create a URIRef object from the string
            Variable(var_string)
            return True
        except ValueError:
            # If an exception is raised, the string is not a valid URI
            return False


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

    def __init__(self, subject: Identifier | Variable | str = None):
        if subject:
            if isinstance(subject, str):
                subject = Variable(subject) if subject.startswith("?") else Identifier(subject)

        self.subject = subject
        self.predicate = None
        self.argument = None

    def to_sparql(self) -> str:
        pass

    def to_dict(self, version: str = "latest") -> dict:
        pass

    def is_defined(self) -> bool:
        return self.subject is not None

    def from_dict(self, subject: Variable | Identifier, data: dict, version: str = "latest"):
        pass


class AtomClause(Clause):

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
        pred = self.predicate.n3()
        val = self.argument.n3() if isinstance(self.argument, Identifier) else str(self.argument)
        return f"{subj} {pred} {val}"

    def __init__(self,
                 subject: Identifier | Variable = None,
                 predicate: Identifier = None,  # no predicate variable allowed
                 argument: Value | Identifier | Variable = None,
                 variable: Variable = None,
                 method: Comparison = Comparison.ANY,
                 project=False,
                 optional=False):
        """
        A select clause

        """

        super().__init__(subject)
        # if predicate:
        #     self.predicate = Identifier(predicate) if isinstance(predicate,str) else predicate
        # else:
        self.predicate = predicate
        self.argument = self._instantiate_argument(argument) if argument else None
        # if variable:  # binary predicate's second argument
        self.variable = variable  # else argument  # argument's variable
        self.method = method
        self.project = project
        self.optional = optional
        self.variable = None

    # self._temp_vars = 0

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
                clause += self.n3()  # f"{self.subject} {self.predicate} {self.argument}"
            case Comparison.REGEX:
                tmp_var = Variable()  # self._temp_var()
                clause = f"{self.subject} {self.predicate.n3()} {tmp_var}\n"
                clause += f'\n\t\tFILTER  regex({tmp_var}, "{self.argument}", "i")'
            case Comparison.KEYWORD:
                clause += f'({self.subject} ?score) text:query "{self.argument}"'
            case Comparison.GREATER:
                var = self.variable if self.variable else Variable()
                clause += f"{self.subject} {self.predicate.n3()} {var}\n"
                clause += f'\t\tFILTER ({var} > "{self.argument}")'
            case Comparison.LESSER:
                var = self.variable if self.variable else Variable()
                clause += f'{self.subject} {self.predicate.n3()} {var}\n'
                clause += f'FILTER ({var} < "{self.argument}")'
            case _:
                raise ValueError(self.method)

        if self.optional:
            clause = f"OPTIONAL {{ {clause} }}\n"
        else:
            clause += " .\n"

        return clause

    def to_dict(self, version: str = "latest") -> dict:
        out = {
            'property': self.predicate,
            'method': self.method.value,
            'project': self.project,
            'optional': self.optional
        }
        if self.subject:
            out['subject'] = self.subject

        if isinstance(self.argument, Value):
            out['value'] = self.argument
        elif isinstance(self.argument, Variable):
            out['variable'] = self.argument
        else:
            out['identifier'] = self.argument

        match version:
            case 'latest':
                out['type'] = "atomic"
            case "v1.0.0":
                pass

        return out

    def from_dict(self, subject: Variable | Identifier, data: dict, version: str = "latest"):
        """
        Openapi spec:  components.schemas.Clause
        """
        if subject and not (isinstance(subject, Variable) or isinstance(subject, Identifier)):
            if Identifier.is_valid_uri(str(subject)):
                subject = Identifier(str(subject))
            elif Variable.is_valid_variable(str(subject)):
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
                    self.predicate = Identifier(val)
                case 'value':
                    self.argument = Value(val)
                case 'identifier':
                    self.argument = Identifier(val)
                case 'subject':
                    # the subject should be already in plase
                    if self.subject:
                        pass
                    else:
                        self.subject = Identifier(val)
                case 'variable':
                    if val == "query.subject":
                        self.variable = Variable("i")  # the query subject
                    else:
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


class UnionClause(Clause):
    """
    A list of atomic clauses on the same subject, which are evaluated in 'or'
    """

    @staticmethod
    def _validate_union_clauses(clauses: list[AtomClause]) -> bool:
        if not clauses:
            return True
        subject = clauses[0].subject
        return all(clause.subject == subject for clause in clauses)

    def __init__(self,
                 subject: Identifier | Variable = None,
                 atom_clauses: list[AtomClause] = None):
        super().__init__(subject if subject else Variable())
        if not atom_clauses:
            atom_clauses = list[AtomClause]()
        else:
            if not self._validate_union_clauses(atom_clauses):
                raise ValueError("Invalid union clauses")
        self.atom_clauses = atom_clauses

    def add_clause(self,
                   predicate: Identifier,
                   argument: Value | Variable | Identifier,
                   method=Comparison.EXACT):
        self.atom_clauses.append(AtomClause(self.subject, predicate, argument, method))

    def to_sparql(self) -> str:
        match len(self.atom_clauses):
            case 0:
                return ""
            case 1:
                return self.atom_clauses[0].to_sparql()
            case _:
                strio = StringIO()
                strio.write("UNION {\n")
                for constraint in self.atom_clauses:
                    strio.write("\t\t" + constraint.to_sparql())
                strio.write("\t}\n")
                return strio.getvalue()

    def to_dict(self, version: str = "latest") -> dict:
        out = {
            'subject': self.subject,
            'clauses': [c.to_dict() for c in self.atom_clauses]
        }

        match version:
            case "latest":
                out['type'] = "union"
            case "v1.0.0":
                pass

        return out

    def from_dict(self, subject: Variable | Identifier, data: dict, version: str = "latest"):
        self.subject = subject
        for atom_dict in data.get('clauses', []):
            atom = AtomClause()
            subject = atom_dict.get('subject', self.subject)
            atom.from_dict(subject=subject, data=atom_dict)
            self.atom_clauses.append(atom)


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
            if isinstance(c, AtomClause) and c.project:
                if isinstance(c.argument, Variable):
                    _vars.append(c.argument)
                if isinstance(c.subject, Variable):
                    _vars.append(c.subject)
        return set(_vars)

    def has_return_vars(self) -> bool:
        return len(self.project_vars()) > 0

    def to_sparql(self) -> str:
        pass

    def to_dict(self, version: str = None) -> dict:
        pass


class UnarySelectQuery(SelectQuery):
    """
    Select query about a single subject
    By convention, the first variable is the subject, others are subject's attributes and relations
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
                 subject=None,
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
        @param clauses: a list of selection clauses
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
            self.subject = Variable("i")
        if kinds:
            self.add_kinds(kinds)

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
            self.add(AtomClause(subject=self.subject,
                                predicate=RDF_TYPE,
                                argument=Identifier(kind_refs[0]),
                                method=Comparison.EXACT,
                                project=False,
                                optional=False))
        elif len(kind_refs) > 1:
            kind_union = UnionClause(subject=self.subject)
            for kind in kind_refs:
                kind_union.add_clause(predicate=RDF_TYPE, argument=Identifier(kind), method=Comparison.EXACT)
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
                    case 'subject':
                        self.subject = self._new_id(val)
                    case 'kinds':
                        self.add_kinds(val)
                    case 'clauses':
                        for clause_data in val:
                            match clause_data.get('type', 'atomic'):
                                case 'atomic':
                                    clause = AtomClause()
                                case 'union':
                                    clause = UnionClause()
                                case _:
                                    raise ValueError(f"Clause type unknown")
                            subject = clause_data.get('subject', self.subject)
                            clause.from_dict(subject=subject, data=clause_data)
                            self.add(clause)
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

    def to_dict(self, version="latest") -> dict:

        out = {}
        if version == "latest" or version > "v1.0.0":
            out['subject'] = self.subject

        kinds = self.get_kinds()
        if len(kinds) > 0:
            out["kinds"] = kinds
        out["clauses"] = [c.to_dict(version) for c in self.property_clauses()]
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

    @classmethod
    def new(cls, rdata: dict) -> SelectQuery:
        q = UnarySelectQuery()
        q.from_dict(rdata)
        return q

    def is_scored(self) -> bool:
        return next(filter(lambda c: isinstance(c, AtomClause) and c.method == Comparison.KEYWORD, self.clauses),
                    None) is not None

    def get_kinds(self) -> list[Identifier]:
        atom_clauses = self.atom_clauses()
        rt = []
        for c in atom_clauses:
            if c.predicate == RDF_TYPE and isinstance(c.argument, Identifier):
                rt.append(c.argument)
        return rt

    def atom_property_clauses(self) -> list[AtomClause]:
        return [c for c in self.atom_clauses() if c.predicate != RDF_TYPE]

    def union_clauses(self) -> list[UnionClause]:
        return [c for c in self.clauses if isinstance(c, UnionClause)]

    def property_clauses(self):
        return self.atom_property_clauses() + self.union_clauses()
