FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY act2_router ./act2_router
COPY configs ./configs
COPY examples ./examples
COPY eval ./eval
COPY docker/entrypoint.sh /usr/local/bin/lcc-router-entrypoint

RUN python -m pip install --no-cache-dir -e .

ENTRYPOINT ["lcc-router-entrypoint"]
CMD ["lcc", "route", "eval", "--cases", "examples/tasks", "--output", "eval/reports/docker_eval.json"]
