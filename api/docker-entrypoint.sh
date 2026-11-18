#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-1}" != "0" ]; then
    python -m app.core.migrate
fi

exec "$@"
