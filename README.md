# SQL Server MCP Server

Servidor MCP custom para Microsoft SQL Server.  
Soporta SELECT, INSERT (individual y bulk), UPDATE, DELETE, DDL (CREATE/ALTER TABLE) y Stored Procedures con parámetros opcionales.

---

## Requisitos previos

- Python 3.11+
- [ODBC Driver 17 o 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) instalado en tu máquina
- Acceso a tu instancia de SQL Server

---

## Instalación

```bash
# 1. Clonar / copiar el proyecto
cd sqlserver-mcp

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar conexión
cp .env.example .env
# Edita .env con tus datos de SQL Server
```

> **Importante:**  
> El archivo `.env.example` contiene comentarios (`#`) como referencia y documentación.  
> El archivo `.env` final debe contener únicamente las variables de entorno necesarias, sin comentarios.

---

## Configuración (.env)

| Variable | Descripción | Default |
|---|---|---|
| `MSSQL_SERVER` | IP o nombre del servidor | `localhost` |
| `MSSQL_PORT` | Puerto TCP | `1433` |
| `MSSQL_DATABASE` | Base de datos por defecto | `master` |
| `MSSQL_USERNAME` | Usuario SQL | `sa` |
| `MSSQL_PASSWORD` | Contraseña | — |
| `MSSQL_DRIVER` | Driver ODBC instalado | `ODBC Driver 17 for SQL Server` |
| `MSSQL_ENCRYPT` | Encriptar conexión (yes/no) | `yes` |
| `MSSQL_TRUST_CERT` | Confiar en cert autofirmado | `no` |
| `MSSQL_TIMEOUT` | Timeout de conexión en segundos | `30` |
| `MSSQL_POOL_SIZE` | Tamaño del pool de conexiones | `5` |
| `MSSQL_CHAR_ENCODING` | Encoding de columnas VARCHAR (cp1252, latin-1, utf-8) | `cp1252` |
| `MSSQL_ALLOWED_OPS` | Ops habilitadas (csv) | `select,insert,update,delete,exec_sp,ddl` |
| `MSSQL_ALLOWED_SCHEMAS` | Schemas permitidos (vacío = todos) | — |
| `MSSQL_DDL_TABLE_PREFIX` | Prefijo requerido para DDL (vacío = sin restricción) | — |
| `MSSQL_LOG_QUERIES` | Loggear queries ejecutadas | `true` |
| `MSSQL_LOG_LEVEL` | Nivel de logging (DEBUG/INFO/WARNING/ERROR) | `INFO` |

---

## Arranque manual (prueba)

```bash
# Modo stdio (para Claude Desktop / Claude Code)
python server.py

# Modo HTTP (para agentes remotos)
python server.py --transport streamable-http --port 5000
```

---

## Integración con OpenCode

Agrega esto a tu archivo de configuración de OpenCode (`opencode.json` o `opencode.jsonc`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "sqlserver": {
      "type": "local",
      "command": [
        "C:\\ruta-al-proyecto\\.venv\\Scripts\\python.exe",
        "-u",
        "C:\\ruta-al-proyecto\\server.py"
      ],
      "environment": {
        "MSSQL_SERVER": "localhost",
        "MSSQL_PORT": "1433",
        "MSSQL_DATABASE": "mi_bd",
        "MSSQL_USERNAME": "sa",
        "MSSQL_PASSWORD": "TuPassword123!"
      }
    }
  }
}
```

> Ajusta las rutas en `command` a tu entorno virtual y al directorio del proyecto.

---

## Tools disponibles

| Tool | Descripción |
|---|---|
| `tool_list_schemas` | Lista schemas de la BD |
| `tool_list_tables` | Lista tablas/vistas de un schema |
| `tool_describe_table` | Describe columnas, tipos, PKs e índices |
| `tool_execute_query` | SELECT parametrizado con filtros y paginación |
| `tool_insert_record` | INSERT de un registro |
| `tool_bulk_insert` | INSERT masivo en lotes (ideal para traducciones) |
| `tool_update_record` | UPDATE con WHERE obligatorio |
| `tool_delete_record` | DELETE con WHERE obligatorio |
| `tool_create_table` | CREATE TABLE con IF NOT EXISTS |
| `tool_alter_table` | ALTER TABLE ADD/ALTER COLUMN |
| `tool_execute_ddl_raw` | DDL arbitrario T-SQL (con guardia anti-DROP) |
| `tool_list_stored_procedures` | Lista SPs del schema |
| `tool_describe_stored_procedure` | Muestra parámetros del SP (incluye opcionales) |
| `tool_execute_sp` | Ejecuta SP con parámetros nombrados opcionales |

---

## Ejemplo de uso con un agente

**Pregunta al agente:**
> "Crea la tabla de traducciones para inglés y español, e inserta estas 500 filas de forma masiva"

El agente usará:
1. `tool_create_table` → crea la tabla
2. `tool_bulk_insert` → inserta en lotes de 500

**Pregunta al agente:**
> "Llama al SP sp_GetCatalogo con IdIdioma = 2"

El agente usará:
1. `tool_describe_stored_procedure` → ve que IdIdioma es opcional
2. `tool_execute_sp` → llama con `{"IdIdioma": 2}`

---

## Seguridad

- WHERE es **obligatorio** en UPDATE y DELETE para evitar operaciones masivas accidentales.
- DROP y TRUNCATE están **bloqueados** en `execute_ddl_raw` salvo que pases `allow_destructive=True`.
- Puedes limitar schemas y operaciones desde el `.env` sin tocar código.
- Las queries van **parametrizadas** (placeholders `?`) para prevenir SQL injection.

### Recomendación: usuario dedicado con permisos limitados

En producción, evita usar el usuario `sa`. Crea un login SQL Server dedicado con los permisos mínimos que realmente necesite el agente. Por ejemplo, si el agente solo requiere leer, insertar y crear tablas (sin editar ni eliminar registros):

```sql
CREATE LOGIN mcp_agent WITH PASSWORD = 'TuPasswordSeguro123!';
USE [tu_base];
CREATE USER mcp_agent FOR LOGIN mcp_agent;
GRANT SELECT, INSERT, CREATE TABLE TO mcp_agent;
```

Ajusta los permisos según tu caso (`UPDATE`, `DELETE`, `EXECUTE` en stored procedures, etc.) y acótalos también en la variable `MSSQL_ALLOWED_OPS` del `.env`.
