@echo off
REM Migration script for Voxlyne (Windows)
REM Run all pending migrations

echo Running database migrations...

REM Check if .env file exists
if not exist .env (
    echo Error: .env file not found
    echo Please create .env from .env.example and configure DATABASE_URL
    exit /b 1
)

REM Load DATABASE_URL from .env
for /f "tokens=1,2 delims==" %%a in ('type .env ^| findstr /v "^#"') do (
    if "%%a"=="DATABASE_URL" set DATABASE_URL=%%b
)

if "%DATABASE_URL%"=="" (
    echo Error: DATABASE_URL not set in .env
    exit /b 1
)

echo Database URL configured

REM Check if docker-compose is available
docker-compose ps postgres | findstr "Up" >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: PostgreSQL container not running
    echo Start it with: docker-compose up -d postgres
    exit /b 1
)

echo Creating migrations tracking table...
docker-compose exec -T postgres psql -U voxlyne -d voxlyne -c "CREATE TABLE IF NOT EXISTS _migrations (id SERIAL PRIMARY KEY, filename VARCHAR(255) UNIQUE NOT NULL, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"

REM Run each migration
for %%f in (migrations\*.sql) do (
    echo Checking: %%~nxf

    REM Check if already applied
    for /f %%c in ('docker-compose exec -T postgres psql -U voxlyne -d voxlyne -t -c "SELECT COUNT(*) FROM _migrations WHERE filename = '%%~nxf';"') do set count=%%c

    if "%count%"=="0" (
        echo Running: %%~nxf
        docker-compose exec -T postgres psql -U voxlyne -d voxlyne < %%f
        docker-compose exec -T postgres psql -U voxlyne -d voxlyne -c "INSERT INTO _migrations (filename) VALUES ('%%~nxf');"
        echo Applied: %%~nxf
    ) else (
        echo Skipped: %%~nxf (already applied)
    )
)

echo.
echo All migrations completed successfully!
echo.
echo Applied migrations:
docker-compose exec -T postgres psql -U voxlyne -d voxlyne -c "SELECT filename, applied_at FROM _migrations ORDER BY applied_at;"

pause
