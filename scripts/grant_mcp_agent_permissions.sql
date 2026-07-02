/*
  Asigna los permisos necesarios para el usuario MCP en TumiCloud.

  Supuestos:
  - El login de servidor [mcp-agent] ya existe.
  - El MCP trabajara sobre los schemas de aplicacion existentes en la base.
  - Ejecutar con un usuario que pueda crear usuarios de base de datos y otorgar permisos.
*/

IF DB_ID(N'TumiCloud') IS NULL
BEGIN
    THROW 51000, 'La base de datos [TumiCloud] no existe.', 1;
END;
GO

USE [TumiCloud];
GO

IF SUSER_ID(N'mcp-agent') IS NULL
BEGIN
    THROW 51001, 'El login de servidor [mcp-agent] no existe. Crealo primero.', 1;
END;
GO

IF USER_ID(N'mcp-agent') IS NULL
BEGIN
    CREATE USER [mcp-agent] FOR LOGIN [mcp-agent];
END
ELSE
BEGIN
    ALTER USER [mcp-agent] WITH LOGIN = [mcp-agent];
END;
GO

IF DATABASE_PRINCIPAL_ID(N'mcp_agent_role') IS NULL
BEGIN
    CREATE ROLE [mcp_agent_role] AUTHORIZATION [dbo];
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.database_role_members drm
    JOIN sys.database_principals r ON r.principal_id = drm.role_principal_id
    JOIN sys.database_principals m ON m.principal_id = drm.member_principal_id
    WHERE r.name = N'mcp_agent_role'
      AND m.name = N'mcp-agent'
)
BEGIN
    ALTER ROLE [mcp_agent_role] ADD MEMBER [mcp-agent];
END;
GO

GRANT CONNECT TO [mcp_agent_role];
GRANT VIEW DEFINITION TO [mcp_agent_role];

GRANT CREATE TABLE TO [mcp_agent_role];
GRANT CREATE PROCEDURE TO [mcp_agent_role];
GRANT CREATE TYPE TO [mcp_agent_role];
GO

DECLARE @sql nvarchar(max) = N'';

SELECT @sql += N'
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::' + QUOTENAME(s.name) + N' TO [mcp_agent_role];
GRANT EXECUTE ON SCHEMA::' + QUOTENAME(s.name) + N' TO [mcp_agent_role];
GRANT REFERENCES ON SCHEMA::' + QUOTENAME(s.name) + N' TO [mcp_agent_role];
GRANT ALTER ON SCHEMA::' + QUOTENAME(s.name) + N' TO [mcp_agent_role];'
FROM sys.schemas s
WHERE s.name NOT IN (
    N'sys', N'INFORMATION_SCHEMA', N'guest',
    N'db_owner', N'db_accessadmin', N'db_securityadmin', N'db_ddladmin',
    N'db_backupoperator', N'db_datareader', N'db_datawriter',
    N'db_denydatareader', N'db_denydatawriter'
);

EXEC sys.sp_executesql @sql;
GO

SELECT
    DB_NAME() AS [database_name],
    N'mcp-agent' AS [database_user],
    N'mcp_agent_role' AS [role_name],
    N'Permisos asignados correctamente.' AS [status];
GO
