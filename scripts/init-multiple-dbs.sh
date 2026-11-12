#!/bin/bash
# ВАЖЛИВО: Файл має бути збережений із закінченням рядків LF (не CRLF)
set -e

function create_user_and_database() {
    local database=$1
    echo "Creating database '$database'..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
        CREATE DATABASE $database;
        GRANT ALL PRIVILEGES ON DATABASE $database TO $POSTGRES_USER;
EOSQL
}

if [ -n "$AUTH_DB_NAME" ] && [ -n "$ORDER_DB_NAME" ]; then
    create_user_and_database $AUTH_DB_NAME
    create_user_and_database $ORDER_DB_NAME
    
    echo "Installing pgvector on $CATALOG_DB_NAME..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$CATALOG_DB_NAME" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
fi