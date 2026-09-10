# SQL Server MCP Server

Servidor MCP custom para Microsoft SQL Server.  
Soporta SELECT, INSERT (individual y bulk), UPDATE, DELETE, DDL (CREATE SCHEMA, CREATE/ALTER TABLE) y Stored Procedures con parámetros opcionales.

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
| `MSSQL_QUERY_TIMEOUT` | Timeout de queries en segundos (0=sin límite) | `0` |
| `MSSQL_POOL_SIZE` | Tamaño del pool de conexiones | `5` |
| `MSSQL_CHAR_ENCODING` | Encoding de lectura de columnas VARCHAR (cp1252, latin-1, utf-8) | `cp1252` |
| `MSSQL_WRITE_ENCODING` | Encoding de escritura de datos (cp1252 para VARCHAR, utf-8 para NVARCHAR) | `cp1252` |
| `MSSQL_ALLOWED_OPS` | Ops habilitadas (csv) | `select,insert,update,delete,exec_sp,ddl,ddl_sp` |
| `MSSQL_ALLOWED_SCHEMAS` | Schemas permitidos (vacío = todos) | — |
| `MSSQL_DDL_TABLE_PREFIX` | Prefijo requerido para DDL (vacío = sin restricción) | — |
| `MSSQL_DDL_SCHEMA_OWNER` | Propietario fijo de los schemas creados por el MCP | `mcp_agent_role` |
| `MSSQL_LOG_QUERIES` | Loggear queries ejecutadas | `true` |
| `MSSQL_LOG_PARAMS` | Incluir valores de parámetros en logs | `true` |
| `MSSQL_LOG_LEVEL` | Nivel de logging (DEBUG/INFO/WARNING/ERROR) | `INFO` |

---

## Arranque manual (prueba)

```bash
# Modo stdio (para OpenCode)
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
| `tool_list_databases` | Lista bases de datos disponibles en el servidor |
| `tool_list_schemas` | Lista schemas de la BD |
| `tool_list_tables` | Lista tablas/vistas de un schema |
| `tool_describe_table` | Describe columnas, tipos, PKs e índices |
| `tool_execute_query` | SELECT parametrizado con filtros, paginación, TOP, DISTINCT, GROUP BY, HAVING y expresiones (COUNT, SUM, MIN, MAX, etc.) |
| `tool_execute_raw_select` | SELECT arbitrario (JOINs, CTEs, subconsultas, ventanas) con paginación; omite OFFSET/FETCH si el SQL contiene TOP |
| `tool_insert_record` | INSERT de un registro |
| `tool_bulk_insert` | INSERT masivo en lotes (ideal para traducciones, soporta `transactional=True/False`) |
| `tool_update_record` | UPDATE con WHERE obligatorio |
| `tool_delete_record` | DELETE con WHERE obligatorio |
| `tool_execute_transaction` | Múltiples statements en una sola transacción atómica |
| `tool_create_table` | CREATE TABLE con IF NOT EXISTS |
| `tool_create_schema` | CREATE SCHEMA con propietario configurado e IF NOT EXISTS |
| `tool_alter_table` | ALTER TABLE ADD/ALTER COLUMN |
| `tool_drop_table` | DROP TABLE IF EXISTS (requiere `allow_destructive=True`) |
| `tool_execute_ddl_raw` | DDL arbitrario T-SQL (con guardia anti-DROP) |
| `tool_list_stored_procedures` | Lista SPs del schema |
| `tool_describe_stored_procedure` | Muestra parámetros del SP (incluye opcionales y metadata de TVP cuando aplica) |
| `tool_execute_sp` | Ejecuta SP con parámetros nombrados opcionales; acepta `procedure` simple o `schema.procedure` y TVP automáticos desde listas de filas |
| `tool_create_sp` | Crea un nuevo stored procedure (requiere `ddl_sp` en `MSSQL_ALLOWED_OPS`) |
| `tool_alter_sp` | Modifica un stored procedure existente (requiere `ddl_sp` en `MSSQL_ALLOWED_OPS`) |
| `tool_drop_sp` | Elimina un stored procedure (requiere `ddl_sp` y `allow_destructive=True`) |

---

## Base de datos configurada

El MCP opera únicamente sobre la base definida en `MSSQL_DATABASE` del `.env`. Las tools mantienen el parámetro opcional `database` por compatibilidad, pero no permite cambiar de base en runtime.

**Ejemplos:**

```sql
-- Usa la base configurada en MSSQL_DATABASE
tool_execute_query(table="Products")

-- Pasar la misma base configurada es equivalente a omitir database
tool_execute_query(table="Products", database="TumiCloud")

-- Pasar otra base se rechaza
tool_execute_query(table="Products", database="OtraBD")
```

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

**Pregunta al agente:**
> "Llama al SP sp_SaveItems pasando dos filas al TVP Items"

El agente usará:
1. `tool_describe_stored_procedure` → ve que `@Items` es TVP y qué columnas espera
2. `tool_execute_sp` → llama con filas JSON normales

Formato recomendado para TVP:

```text
tool_execute_sp(
  procedure="sp_SaveItems",
  params={
    "Items": [
      {"ProdCode": 1, "Qty": 2},
      {"ProdCode": 2, "Qty": 5}
    ]
  }
)
```

Tambien se aceptan filas posicionales, usando el orden de columnas que devuelve
`tool_describe_stored_procedure`:

```text
tool_execute_sp(
  procedure="sp_SaveItems",
  params={
    "Items": [
      [1, 2],
      [2, 5]
    ]
  }
)
```

Si llamas al MCP desde Python, tambien puedes pasar tuplas por fila:

```python
tool_execute_sp(
    procedure="sp_SaveItems",
    params={"Items": [(1, 2), (2, 5)]},
)
```

Para enviar un TVP vacio, pasa una lista vacia:

```text
tool_execute_sp(procedure="sp_SaveItems", params={"Items": []})
```

**Observaciones de validación real**

- `tool_describe_stored_procedure` detecta automáticamente si un parámetro es TVP y expone `type_schema`, `type_name` y `tvp_columns` en el orden correcto.
- Con TVP en formato `list[dict]`, el orden de claves no importa: el MCP reordena los valores según `tvp_columns`.
- Con TVP en formato `list[list]` o `list[tuple]`, cada fila se interpreta por posición usando el orden de `tvp_columns`.
- Un TVP vacío (`[]`) se envía correctamente a SQL Server como TVP tipado vacío.
- Si una fila tiene columnas faltantes, extra o una longitud incorrecta, el MCP falla antes de ejecutar el SP y devuelve un error claro, por ejemplo: `Fila 1 invalida para TVP '@Items': faltan columnas: Qty.`

**Consulta avanzada con JOIN:**
> "Dame todas las órdenes del cliente 'Acme' con el nombre del vendedor"

El agente usará `tool_execute_raw_select` con:
```sql
SELECT o.Id, o.OrderDate, e.FirstName + ' ' + e.LastName AS SalesPerson
FROM Orders o
JOIN Employees e ON o.EmployeeID = e.EmployeeID
JOIN Customers c ON o.CustomerID = c.CustomerID
WHERE c.CustomerName = ?
```

**Importante: stored procedures no van en `tool_execute_raw_select`**

`tool_execute_raw_select` acepta solo `SELECT` o `WITH ... SELECT`.
Si intentas algo como:

```sql
EXEC [GENERAL].[SP_LISTA_PAIS] @ID = ''
```

debes usar:

```text
tool_execute_sp(procedure="SP_LISTA_PAIS", schema="GENERAL", params={"ID": ""})
```

Tambien puedes usar el nombre calificado:

```text
tool_execute_sp(procedure="GENERAL.SP_LISTA_PAIS", params={"ID": ""})
```

---

## Seguridad

- WHERE es **obligatorio** en UPDATE y DELETE para evitar operaciones masivas accidentales.
- DROP y TRUNCATE están **bloqueados** en `execute_ddl_raw` salvo que pases `allow_destructive=True`.
- `CREATE SCHEMA` debe ejecutarse mediante `tool_create_schema`; las rutas SQL genéricas lo bloquean.
- Puedes limitar schemas y operaciones desde el `.env` sin tocar código.
- Las queries van **parametrizadas** (placeholders `?`) para prevenir SQL injection.

### Creación de schemas

`tool_create_schema` requiere `ddl` en `MSSQL_ALLOWED_OPS` y crea el schema con el propietario definido en `MSSQL_DDL_SCHEMA_OWNER`. El agente no puede elegir el propietario en cada llamada.

Si `MSSQL_ALLOWED_SCHEMAS` está vacío, el MCP no limita el nombre del schema. Si contiene valores, el schema solicitado debe aparecer explícitamente en esa lista. Esta configuración solo controla la autorización de la aplicación; SQL Server también debe conceder el permiso `CREATE SCHEMA` a la cuenta o rol de conexión.

La provisión recomendada para el rol del MCP es:

```sql
GRANT CREATE SCHEMA TO [mcp_agent_role];
```

El rol debe existir y poder ser propietario del schema. Por defecto, `mcp_agent_role` ya cumple esta condición cuando `mcp-agent` es miembro del rol.

### Recomendación: usuario dedicado con permisos limitados

En producción, evita usar el usuario `sa`. Crea un login SQL Server dedicado con los permisos mínimos que realmente necesite el agente. Por ejemplo, si el agente solo requiere leer, insertar y crear tablas (sin editar ni eliminar registros):

```sql
CREATE LOGIN mcp_agent WITH PASSWORD = 'TuPasswordSeguro123!';
USE [tu_base];
CREATE USER mcp_agent FOR LOGIN mcp_agent;
GRANT SELECT, INSERT, CREATE TABLE TO mcp_agent;
```

Ajusta los permisos según tu caso (`UPDATE`, `DELETE`, `EXECUTE` en stored procedures, etc.) y acótalos también en la variable `MSSQL_ALLOWED_OPS` del `.env`.
