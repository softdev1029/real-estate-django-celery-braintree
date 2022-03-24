from django.db.models import Expression, Func


class ToLocalTZ(Expression):
    """
    A database expression that will take a UTC datetime field and return a local TZ datetime.

    Example:
    Queryset.objects.annotate(
        local_dt=ToLocalTZ([F('utc_dt'), F('timezone')], output_field=models.DateTimeField())
    )
    """
    template = "%(expressions) AT TIME ZONE %(timezone)"

    def __init__(self, expressions, output_field):
        super().__init__(output_field=output_field)
        if len(expressions) < 2:
            raise ValueError('expressions must have at least 2 elements')
        for expression in expressions:
            if not hasattr(expression, 'resolve_expression'):
                raise TypeError('%r is not an Expression' % expression)
        self.expressions = expressions

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):  # noqa: E501
        c = self.copy()
        c.is_summary = summarize
        for pos, expression in enumerate(self.expressions):
            c.expressions[pos] = expression.resolve_expression(
                query,
                allow_joins,
                reuse,
                summarize,
                for_save,
            )
        return c

    def as_sql(self, compiler, connection, template=None):
        sql_expressions, sql_params = [], []
        for expression in self.expressions:
            sql, params = compiler.compile(expression)
            sql_expressions.append(sql)
            sql_params.extend(params)
        return f"{ sql_expressions[0] } AT TIME ZONE { sql_expressions[1] }", sql_params

    def get_source_expressions(self):
        return self.expressions

    def set_source_expressions(self, expressions):
        self.expressions = expressions
