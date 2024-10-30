"""
SPARQL query generator
(c) Isagog S.r.l. 2024, MIT License
"""
import logging
from io import StringIO

from isagog.model.query_model import Generator, Clause
from isagog.model.query_model import UnaryQuery, AtomicClause, Comparison, Variable, \
    ConjunctiveClause, DisjunctiveClause, _SCOREVAR, Select, META_PROPERTIES


class SPARQLGenerator(Generator):
    """
    SPARQL query generator
    """


    def __init__(self):
        super().__init__(language="SPARQL")
        self.var_count = 0


    def fresh_variable(self) -> Variable:
        self.var_count += 1
        return Variable(symbol=f"?{self.var_count}")

    def generate_clause(self, clause: Clause, **kwargs) -> str:
      try:
        if isinstance(clause, AtomicClause):
            """
            Generates the sparql triple clause
            """
            if not clause.is_defined():
                raise ValueError(f"Clause not defined {clause.subject} {clause.property} {clause.argument}")

            if str(clause.property) == META_PROPERTIES.IN.value:
                return f"FILTER ({clause.subject} IN ({clause.argument})) .\n"

            clause_str = ""

            match Comparison(clause.operator):
                case Comparison.EXACT | Comparison.ANY:
                    clause_str += clause.n3()  # f"{self.subject} {self.property} {self.argument}"
                case Comparison.REGEX:
                    tmp_var = self.fresh_variable()  # self._temp_var()
                    clause_str = f"{clause.subject} {clause.property.n3()} {tmp_var}\n"
                    clause_str += f'\n\t\tFILTER  regex({tmp_var}, "{clause.argument.constraint}", "i")'
                case Comparison.KEYWORD:
                    clause_str += f'({clause.subject} ?{_SCOREVAR}) text:query "{clause.argument}"'
                case Comparison.GREATER:
                    var = clause.variable if clause.variable else self.fresh_variable()
                    clause_str += f"{clause.subject} {clause.property.n3()} {var}\n"
                    clause_str += f'\t\tFILTER ({var} > "{clause.argument}")'
                case Comparison.LESSER:
                    var = clause.variable if clause.variable else self.fresh_variable()
                    clause_str += f'{clause.subject} {clause.property.n3()} {var}\n'
                    clause_str += f'FILTER ({var} < "{clause.argument}")'
                case Comparison.GREATER_EQUAL:
                    var = clause.variable if clause.variable else self.fresh_variable()
                    clause_str += f'{clause.subject} {clause.property.n3()} {var}\n'
                    clause_str += f'FILTER ({var} >= "{clause.argument}")'
                case Comparison.LESSER_EQUAL:
                    var = clause.variable if clause.variable else self.fresh_variable()
                    clause_str += f'{clause.subject} {clause.property.n3()} {var}\n'
                    clause_str += f'FILTER ({var} <= "{clause.argument}")'
                case Comparison.EQUAL:
                    var = clause.variable if clause.variable else self.fresh_variable()
                    clause_str += f'{clause.subject} {clause.property.n3()} {var}\n'
                    clause_str += f'FILTER ({var} = "{clause.argument}")'
                case Comparison.NOT_EXISTS:
                    var = self.fresh_variable()
                    clause_str += f'FILTER NOT EXISTS {{ {clause.subject} {clause.property.n3()} {var} }}'
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
                for sub_clause in clause.clauses: #[1:]:
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
      except Exception as e:
          logging.error(f"Error in generate_clause: {e}", exc_info=True)

    def generate_query(self, query: UnaryQuery, **kwargs) -> str:
       """
        Generates a SPARQL query from a SelectQuery
        :param query:
        :param kwargs:
        :return:
       """

       try:
            if kwargs.get('optimize', True):
                query.sort_clauses()

            if not isinstance(query, UnaryQuery):
                raise TypeError("Can only generate_query from Query")

            strio = StringIO()
            for (name, uri) in query.prefixes.items():
                if uri.endswith("#") or uri.endswith("/"):
                    strio.write(f"PREFIX {name}: <{uri}>\n")
                else:
                    strio.write(f"PREFIX {name}: <{uri}#>\n")

            strio.write("SELECT distinct ")  # {query.subject}")
            for rv in query.project_vars():
                strio.write(f" {rv} ")
            if query.is_scored():
                strio.write(f" {_SCOREVAR} ")
            strio.write(" WHERE \n")
            for clause in query.clauses:
                strio.write(self.generate_clause(clause))
            if query.min_score:
                strio.write(f'\tFILTER (?{_SCOREVAR} >= {query.min_score})\n')

            #strio.write("}\n")
            if query.is_scored():
                strio.write(f"ORDER BY DESC(?{_SCOREVAR})\n")
            if query.limit > 0:
                strio.write(f"LIMIT {query.limit}\n")

            return strio.getvalue()

       except Exception as e:
                logging.error(f"Error in generate_query: {e}", exc_info=True)



_SPARQLGEN = SPARQLGenerator()
