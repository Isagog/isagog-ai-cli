"""
SPARQL query generator
(c) Isagog S.r.l. 2024, MIT License
"""
from io import StringIO

from isagog.model.kg_model import Assertion
from isagog.model.kg_query import UnarySelectQuery, AtomicClause, Comparison, Variable, \
    ConjunctiveClause, DisjunctiveClause, _SCOREVAR, SelectQuery
from isagog.model.kg_query import Generator, Clause


class SPARQLGenerator(Generator):
    """
    SPARQL query generator
    """

    def generate_clause(self, clause: Clause, **kwargs) -> str:

        if isinstance(clause, AtomicClause):
            """
            Generates the sparql triple clause
            """
            if not clause.is_defined():
                raise ValueError(f"Clause not defined {clause.subject} {clause.property} {clause.argument}")

            clause_str = ""

            match Comparison(clause.method):
                case Comparison.EXACT | Comparison.ANY:
                    clause_str += clause.n3()  # f"{self.subject} {self.property} {self.argument}"
                case Comparison.REGEX:
                    tmp_var = Variable()  # self._temp_var()
                    clause_str = f"{clause.subject} {clause.property.n3()} {tmp_var}\n"
                    clause_str += f'\n\t\tFILTER  regex({tmp_var}, "{clause.argument}", "i")'
                case Comparison.KEYWORD:
                    clause_str += f'({clause.subject} ?{_SCOREVAR}) text:query "{clause.argument}"'
                case Comparison.GREATER:
                    var = clause.variable if clause.variable else Variable()
                    clause_str += f"{clause.subject} {clause.property.n3()} {var}\n"
                    clause_str += f'\t\tFILTER ({var} > "{clause.argument}")'
                case Comparison.LESSER:
                    var = clause.variable if clause.variable else Variable()
                    clause_str += f'{clause.subject} {clause.property.n3()} {var}\n'
                    clause_str += f'FILTER ({var} < "{clause.argument}")'
                case Comparison.SIMILARITY:
                    pass
                case _:
                    raise ValueError(clause.method)

            if clause.optional:
                clause_str = f"OPTIONAL {{ {clause_str} }}\n"
            else:
                clause_str += " .\n"

            return clause_str
        elif isinstance(clause, ConjunctiveClause):
            strio = StringIO()
            if len(clause.clauses) > 1:
                if clause.optional:
                    strio.write("OPTIONAL")
                strio.write("\t{\n")
                for sub_clause in clause.clauses[1:]:
                    strio.write("\t\t\t" + self.generate_clause(sub_clause))  # sub_clause.to_sparql())
                strio.write("\t\t}\n")
                # strio.write("\t}\n")
            else:
                strio.write("\t\t\t" + self.generate_clause(clause.clauses[0]))  # clause.clauses[0].to_sparql())

            return strio.getvalue()
        elif isinstance(clause, DisjunctiveClause):
            strio = StringIO()
            if len(clause.clauses) > 1:
                strio.write("\t{\n")

                strio.write("\t\t{\n")
                strio.write("\t\t\t" + self.generate_clause(clause.clauses[0]))  # clause.clauses[0].to_sparql())
                strio.write("\t\t}\n")

                strio.write("\tUNION {\n")
                for constraint in clause.clauses[1:]:
                    strio.write("\t\t\t" + self.generate_clause(constraint))  # constraint.to_sparql())
                strio.write("\t\t}\n")
                strio.write("\t}\n")
            else:
                strio.write("\tUNION {\n")
                strio.write("\t\t\t" + self.generate_clause(clause.clauses[0]))  # clause.clauses[0].to_sparql())
                strio.write("\t}\n")
            return strio.getvalue()
        else:
            raise ValueError("Unsupported clause type")

    def __init__(self):
        super().__init__("SPARQL")

    def generate_query(self, query: SelectQuery, **kwargs) -> str:
        """
        Generates a SPARQL query from a SelectQuery
        :param query:
        :param kwargs:
        :return:
        """

        if not isinstance(query, UnarySelectQuery):
            raise TypeError("Can only generate_query from UnarySelectQuery")

        strio = StringIO()
        for (name, uri) in query.prefixes:
            if uri.endswith("#") or uri.endswith("/"):
                strio.write(f"PREFIX {name}: <{uri}>\n")
            else:
                strio.write(f"PREFIX {name}: <{uri}#>\n")

        strio.write("SELECT distinct ")  # {query.subject}")
        for rv in query.project_vars():
            strio.write(f" {rv} ")
        if query.is_scored():
            strio.write(f" ?{_SCOREVAR} ")
        strio.write(" WHERE {\n")
        if query.has_disjunctive_clauses():
            strio.write("\t{\n")
            for clause in query.atom_clauses():
                strio.write("\t\t" + self.generate_clause(clause))  # clause.to_sparql()
            for clause in query.conjunctive_clauses():
                strio.write("\t\t" + self.generate_clause(clause))  # clause.to_sparql()

            strio.write("\t}\n")

            for clause in query.disjunctive_clauses():
                strio.write(self.generate_clause(clause))  # clause.to_sparql()

        else:
            for clause in query.clauses:
                strio.write("\t" + self.generate_clause(clause))  # clause.to_sparql()

        if query.min_score:
            strio.write(f'\tFILTER (?{_SCOREVAR} >= {query.min_score})\n')

        strio.write("}\n")
        if query.is_scored():
            strio.write(f"ORDER BY DESC(?{_SCOREVAR})\n")
        if query.limit > 0:
            strio.write(f"LIMIT {query.limit}\n")

        return strio.getvalue()



_SPARQLGEN = SPARQLGenerator()
