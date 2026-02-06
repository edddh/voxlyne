#!/bin/bash
# Migration script for Ascolta
# Run all pending migrations

set -e

echo "🔄 Running database migrations..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "Please create .env from .env.example and configure DATABASE_URL"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ Error: DATABASE_URL not set in .env"
    exit 1
fi

# Parse DATABASE_URL to extract connection parameters
# Format: postgresql://user:password@host:port/database
if [[ $DATABASE_URL =~ postgresql://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+) ]]; then
    DB_USER="${BASH_REMATCH[1]}"
    DB_PASS="${BASH_REMATCH[2]}"
    DB_HOST="${BASH_REMATCH[3]}"
    DB_PORT="${BASH_REMATCH[4]}"
    DB_NAME="${BASH_REMATCH[5]}"
else
    echo "❌ Error: Invalid DATABASE_URL format"
    exit 1
fi

echo "📊 Database: $DB_NAME on $DB_HOST:$DB_PORT"

# Check if psql is available
if ! command -v psql &> /dev/null; then
    echo "⚠️  psql not found, trying docker-compose exec..."

    # Check if docker-compose is running
    if docker-compose ps postgres | grep -q "Up"; then
        RUN_CMD="docker-compose exec -T postgres psql -U $DB_USER -d $DB_NAME"
    else
        echo "❌ Error: PostgreSQL container not running"
        echo "Start it with: docker-compose up -d postgres"
        exit 1
    fi
else
    RUN_CMD="PGPASSWORD=$DB_PASS psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"
fi

# Create migrations table if not exists
echo "📝 Creating migrations tracking table..."
$RUN_CMD <<-EOSQL
    CREATE TABLE IF NOT EXISTS _migrations (
        id SERIAL PRIMARY KEY,
        filename VARCHAR(255) UNIQUE NOT NULL,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
EOSQL

# Run each migration
for migration in migrations/*.sql; do
    filename=$(basename "$migration")

    # Check if already applied
    already_applied=$($RUN_CMD -t -c "SELECT COUNT(*) FROM _migrations WHERE filename = '$filename';" | xargs)

    if [ "$already_applied" = "0" ]; then
        echo "▶️  Running: $filename"
        $RUN_CMD < "$migration"
        $RUN_CMD -c "INSERT INTO _migrations (filename) VALUES ('$filename');"
        echo "✅ Applied: $filename"
    else
        echo "⏭️  Skipped: $filename (already applied)"
    fi
done

echo ""
echo "✅ All migrations completed successfully!"
echo ""
echo "📋 Applied migrations:"
$RUN_CMD -c "SELECT filename, applied_at FROM _migrations ORDER BY applied_at;"
