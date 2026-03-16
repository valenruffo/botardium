# Phase 9: Disaster Recovery & Backup System

## Overview

Sistema de backup automático, snapshots incrementales, y point-in-time recovery para proteger los datos del Botardium (sessions, jobs, métricas, configuraciones).

## Architecture

```
scripts/
├── backup/
│   ├── __init__.py
│   ├── backup_manager.py    # Backup automático programadas
│   └── snapshot.py          # Snapshots incrementales
├── recovery/
│   ├── __init__.py
│   └── restore.py           # Point-in-time recovery
└── health/
    └── snapshot.py          # Health snapshots del sistema
```

## Components

### 1. BackupManager (scripts/backup/backup_manager.py)

**Responsabilidad:** Gestionar backups automáticos programados de la base de datos y archivos de sesión.

**Funcionalidades:**
- Backup completo (full backup) de SQLite databases
- Backup incremental (solo cambios desde último backup)
- Programación de backups (cron-style)
- Rotación de backups (mantener últimos N backups)
- Compresión de backups con gzip
- Verificación de integridad post-backup

**API:**
```python
class BackupManager:
    def __init__(self, backup_dir: Path, retention_count: int = 7)
    def create_full_backup(self, label: str = None) -> BackupInfo
    def create_incremental_backup(self, label: str = None) -> BackupInfo
    def restore_from_backup(self, backup_id: str) -> bool
    def list_backups(self) -> List[BackupInfo]
    def delete_backup(self, backup_id: str) -> bool
    def verify_backup(self, backup_id: str) -> bool
    def schedule_backup(self, interval_hours: int, backup_type: str)
```

**Modelos:**
```python
@dataclass
class BackupInfo:
    backup_id: str
    backup_type: str  # "full" | "incremental"
    created_at: datetime
    size_bytes: int
    file_path: Path
    label: str
    verified: bool
```

### 2. SnapshotManager (scripts/backup/snapshot.py)

**Responsabilidad:** Crear y gestionar snapshots incrementales del estado del sistema.

**Funcionalidades:**
- Snapshots de bases de datos (incrementales usando WAL)
- Snapshots de archivos de configuración
- Snapshots de sesiones activas
- Metadata de snapshots (timestamps, checksum)
- Restauración selectiva por componente

**API:**
```python
class SnapshotManager:
    def __init__(self, snapshot_dir: Path)
    def create_snapshot(self, components: List[str] = None) -> SnapshotInfo
    def list_snapshots(self) -> List[SnapshotInfo]
    def restore_snapshot(self, snapshot_id: str, components: List[str] = None) -> bool
    def delete_snapshot(self, snapshot_id: str) -> bool
    def get_snapshot_diff(self, snapshot_id1: str, snapshot_id2: str) -> Dict
```

**Modelos:**
```python
@dataclass
class SnapshotInfo:
    snapshot_id: str
    created_at: datetime
    components: List[str]
    size_bytes: int
    checksum: str
    parent_snapshot_id: str | None
```

### 3. RecoveryManager (scripts/recovery/restore.py)

**Responsabilidad:** Punto de recuperación en el tiempo para desastres.

**Funcionalidades:**
- Listar puntos de recuperación disponibles
- Restaurar a un punto específico en el tiempo
- Restauración parcial (solo ciertos componentes)
- Validación pre-restore (checksum, integridad)
- Rollback automático si restore falla
- Logging de operaciones de restore

**API:**
```python
class RecoveryManager:
    def __init__(self, backup_dir: Path, snapshot_dir: Path)
    def list_recovery_points(self) -> List[RecoveryPoint]
    def restore_to_point(self, point_id: str, components: List[str] = None) -> RestoreResult
    def restore_to_timestamp(self, timestamp: datetime, components: List[str] = None) -> RestoreResult
    def validate_restore(self, point_id: str) -> bool
    def get_latest_valid_restore_point(self) -> RecoveryPoint
```

**Modelos:**
```python
@dataclass
class RecoveryPoint:
    point_id: str
    timestamp: datetime
    backup_id: str
    snapshot_id: str | None
    components: List[str]
    size_bytes: int

@dataclass
class RestoreResult:
    success: bool
    restored_components: List[str]
    failed_components: List[str]
    errors: List[str]
    duration_seconds: float
```

### 4. HealthSnapshot (scripts/health/snapshot.py)

**Responsabilidad:** Capturar snapshots del estado de salud del sistema.

**Funcionalidades:**
- Capturar estado de sesiones (activas, inactivas, rotas)
- Capturar estado de jobs (en cola, procesando, completados, fallidos)
- Capturar métricas del sistema (CPU, memoria, red)
- Capturar configuración actual
- Comparar health snapshots (detectar drifts)
- Alertas basadas en health snapshots

**API:**
<function=HealthSnapshot>
    def __init__(self, snapshot_dir: Path)
    def capture_health_snapshot(self) -> HealthSnapshotInfo
    def list_snapshots(self, limit: int = 10) -> List[HealthSnapshotInfo]
    def compare_snapshots(self, snap1_id: str, snap2_id: str) -> HealthDiff
    def get_snapshot_by_id(self, snapshot_id: str) -> HealthSnapshotInfo | None
    def cleanup_old_snapshots(self, max_age_days: int = 30) -> int
</function>

**Modelos:**
```python
@dataclass
class HealthSnapshotInfo:
    snapshot_id: str
    captured_at: datetime
    sessions: SessionHealth
    jobs: JobHealth
    system: SystemHealth
    config_hash: str

@dataclass
class SessionHealth:
    total: int
    available: int
    checked_out: int
    expired: int
    broken: int

@dataclass
class JobHealth:
    pending: int
    processing: int
    completed: int
    failed: int
    retrying: int

@dataclass
class SystemHealth:
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_latency_ms: float

@dataclass
class HealthDiff:
    snapshot1_id: str
    snapshot2_id: str
    session_diff: Dict
    job_diff: Dict
    system_diff: Dict
    alerts: List[str]
```

## Tests

### test_backup_creation
```python
def test_full_backup_creation(backup_manager, temp_backup_dir):
    # Crear backup completo
    backup = backup_manager.create_full_backup(label="test_full")
    
    # Verificar que el backup existe
    assert backup.backup_id is not None
    assert backup.backup_type == "full"
    assert backup.file_path.exists()
    
    # Verificar que el archivo tiene contenido
    assert backup.size_bytes > 0
    
    # Verificar integridad
    assert backup_manager.verify_backup(backup.backup_id)

def test_incremental_backup_creation(backup_manager, temp_backup_dir):
    # Crear backup completo primero
    full_backup = backup_manager.create_full_backup()
    
    # Hacer cambios en la DB simulada
    # ...
    
    # Crear backup incremental
    incr_backup = backup_manager.create_incremental_backup()
    
    assert incr_backup.backup_type == "incremental"
    assert incr_backup.parent_backup_id == full_backup.backup_id

def test_backup_rotation(backup_manager, temp_backup_dir):
    # Crear más backups que el límite de retención
    for i in range(10):
        backup_manager.create_full_backup(label=f"backup_{i}")
    
    backups = backup_manager.list_backups()
    assert len(backups) == 7  # retention_count
```

### test_point_in_time_restore
```python
def test_restore_to_specific_point(recovery_manager, backup_dir, snapshot_dir):
    # Crear varios backups con timestamps diferentes
    bp1 = create_backup_with_timestamp("2024-01-01 10:00:00")
    bp2 = create_backup_with_timestamp("2024-01-01 12:00:00")
    bp3 = create_backup_with_timestamp("2024-01-01 14:00:00")
    
    # Restaurar al punto del medio
    result = recovery_manager.restore_to_point(bp2.point_id)
    
    assert result.success
    assert "database" in result.restored_components

def test_restore_to_timestamp(recovery_manager):
    # Restaurar a un timestamp específico
    target_time = datetime(2024, 1, 1, 12, 30, 0)
    
    result = recovery_manager.restore_to_timestamp(target_time)
    
    assert result.success

def test_partial_restore(recovery_manager):
    # Restaurar solo componentes específicos
    result = recovery_manager.restore_to_point(
        point_id="bp_001",
        components=["sessions", "config"]
    )
    
    assert "jobs" not in result.restored_components

def test_restore_validation(recovery_manager):
    # Verificar que la validación funciona
    is_valid = recovery_manager.validate_restore("invalid_point")
    assert is_valid == False
    
    is_valid = recovery_manager.validate_restore("bp_001")
    assert is_valid == True
```

### test_health_snapshot
```python
def test_health_snapshot_capture(health_snapshot, mock_db):
    snapshot = health_snapshot.capture_health_snapshot()
    
    assert snapshot.snapshot_id is not None
    assert snapshot.sessions.total >= 0
    assert snapshot.jobs.pending >= 0
    assert snapshot.system.cpu_percent >= 0

def test_health_snapshot_list(health_snapshot):
    # Crear varios snapshots
    for _ in range(5):
        health_snapshot.capture_health_snapshot()
    
    snapshots = health_snapshot.list_snapshots(limit=3)
    
    assert len(snapshots) == 3

def test_health_snapshot_compare(health_snapshot):
    # Capturar dos snapshots
    snap1 = health_snapshot.capture_health_snapshot()
    # Simular cambios...
    snap2 = health_snapshot.capture_health_snapshot()
    
    diff = health_snapshot.compare_snapshots(snap1.snapshot_id, snap2.snapshot_id)
    
    assert diff.snapshot1_id == snap1.snapshot_id
    assert diff.snapshot2_id == snap2.snapshot_id
    assert isinstance(diff.session_diff, dict)

def test_health_snapshot_cleanup(health_snapshot):
    # Crear snapshots antiguos
    create_old_snapshot(days_ago=60)
    
    cleaned = health_snapshot.cleanup_old_snapshots(max_age_days=30)
    
    assert cleaned >= 1
```

## Integration Points

- **SessionPool:** Usar backup de session_pool.db
- **JobQueue:** Usar backup de job_queue.db
- **RuntimeConfig:** Backup de archivos de configuración en config/
- **MetricsCollector:** Snapshots de métricas en observabilidad/

## Constraints

- Backups deben ser idempotentes
- No usar time.sleep() estático (usar random.uniform)
- Todos los errores deben loguearse con selector y screenshot si es posible
- Prohibido dejar bloques try/except mudos