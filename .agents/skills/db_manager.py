"""
PrimeBot Core — Database Manager
=================================
Gestiona la persistencia local de leads y campañas (SQLite).
Provee una interfaz limpia para que los scrapers inserten y
los messengers consuman.

Ruta: Uses runtime_paths.DB_PATH as authoritative source.
"""

import os
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from scripts.runtime_paths import DB_PATH, DB_DIR, ensure_runtime_dirs, create_rollback_snapshot

logger = logging.getLogger("botardium.db")

ensure_runtime_dirs()


class DatabaseManager:
    """Gestor de base de datos local SQLite para PrimeBot."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path if db_path is not None else DB_PATH
        self.workspace_id = int(os.getenv("BOTARDIUM_WORKSPACE_ID") or "0") or None
        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self):
        """Asegura que el directorio exista."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self):
        """Retorna una conexión a SQLite (diccionario-like rows)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Crea las tablas si no existen."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabla de Leads
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ig_username TEXT UNIQUE NOT NULL,
                    full_name TEXT,
                    bio TEXT,
                    campaign_id TEXT,
                    source TEXT,
                    status TEXT DEFAULT 'Pendiente',  -- Pendiente, Contactado, Rechazado, Error
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    contacted_at TIMESTAMP
                )
            ''')

            cursor.execute("PRAGMA table_info(leads)")
            columns = {row[1] for row in cursor.fetchall()}
            if "campaign_id" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN campaign_id TEXT")
            if "full_name" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN full_name TEXT")
            if "bio" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN bio TEXT")
            if "contacted_at" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN contacted_at TIMESTAMP")
            if "last_message_preview" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN last_message_preview TEXT")
            if "message_prompt" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN message_prompt TEXT")
            if "message_variant" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN message_variant TEXT")
            if "sent_at" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN sent_at TIMESTAMP")
            if "follow_up_due_at" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN follow_up_due_at TIMESTAMP")
            if "last_outreach_result" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN last_outreach_result TEXT")
            if "last_outreach_error" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN last_outreach_error TEXT")
            if "last_message_rationale" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN last_message_rationale TEXT")
            if "workspace_id" not in columns:
                cursor.execute("ALTER TABLE leads ADD COLUMN workspace_id INTEGER")
            
            # Índices para búsquedas rápidas
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)')
            
            conn.commit()
            logger.debug("Base de datos inicializada correctamente.")

    def add_lead(self, username: str, full_name: str = "", bio: str = "", source: str = "", campaign_id: str = "", workspace_id: Optional[int] = None) -> bool:
        """
        Agrega un nuevo lead a la base de datos si no existe.
        
        Args:
            username: @usuario de IG
            full_name: Nombre completo
            bio: Biografía extraída
            source: Origen (ej. follower_of_XYZ, hashtag_ABC)
            
        Returns:
            True si se insertó, False si ya existía.
        """
        try:
            active_workspace_id = workspace_id or self.workspace_id
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if active_workspace_id:
                    cursor.execute(
                        "SELECT id FROM leads WHERE workspace_id = ? AND lower(ig_username) = lower(?) LIMIT 1",
                        (active_workspace_id, username),
                    )
                else:
                    cursor.execute("SELECT id FROM leads WHERE lower(ig_username) = lower(?) LIMIT 1", (username,))
                if cursor.fetchone():
                    return False
                cursor.execute('''
                    INSERT INTO leads (ig_username, full_name, bio, campaign_id, source, status, created_at, workspace_id)
                    VALUES (?, ?, ?, ?, ?, 'Pendiente', ?, ?)
                ''', (username, full_name, bio, campaign_id, source, datetime.now().isoformat(), active_workspace_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error insertando lead @{username}: {e}")
            return False

    def get_pending_leads(self, limit: int = 5) -> List[Dict]:
        """
        Retorna N leads en estado 'Pendiente' para ser contactados.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM leads 
                    WHERE status = 'Pendiente' 
                    ORDER BY created_at ASC 
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error leyendo pendientes: {e}")
            return []

    def get_outreach_leads(self, limit: int = 5, ids: Optional[List[int]] = None) -> List[Dict]:
        """Retorna leads listos para ejecucion de outreach real."""
        valid_statuses = ("Listo para contactar", "Primer contacto", "Follow-up 1")
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    workspace_clause = " AND workspace_id = ?" if self.workspace_id else ""
                    cursor.execute(
                        f'''
                        SELECT * FROM leads
                        WHERE id IN ({placeholders}) AND status IN ({','.join('?' for _ in valid_statuses)}){workspace_clause}
                        ORDER BY created_at ASC
                        LIMIT ?
                        ''',
                        [*ids, *valid_statuses, *([self.workspace_id] if self.workspace_id else []), limit],
                    )
                else:
                    workspace_clause = " AND workspace_id = ?" if self.workspace_id else ""
                    cursor.execute(
                        f'''
                        SELECT * FROM leads
                        WHERE status IN ({','.join('?' for _ in valid_statuses)}){workspace_clause}
                        ORDER BY created_at ASC
                        LIMIT ?
                        ''',
                        [*valid_statuses, *([self.workspace_id] if self.workspace_id else []), limit],
                    )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error leyendo cola outreach: {e}")
            return []

    def update_status(self, username: str, new_status: str):
        """
        Actualiza el estado de un lead (ej. de Pendiente a Contactado).
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if new_status in {'Contactado', 'Completado'}:
                    cursor.execute('''
                        UPDATE leads 
                        SET status = ?, contacted_at = ? 
                        WHERE ig_username = ?
                    ''', (new_status, datetime.now().isoformat(), username))
                else:
                    cursor.execute('''
                        UPDATE leads 
                        SET status = ? 
                        WHERE ig_username = ?
                    ''', (new_status, username))
                conn.commit()
        except Exception as e:
            logger.error(f"Error actualizando estado de @{username}: {e}")

    def update_lead_after_message(
        self,
        username: str,
        new_status: str,
        sent_at: Optional[str] = None,
        follow_up_due_at: Optional[str] = None,
        message_variant: Optional[str] = None,
        result: Optional[str] = None,
        error_detail: Optional[str] = None,
    ):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    UPDATE leads
                    SET status = ?,
                        contacted_at = ?,
                        sent_at = COALESCE(?, sent_at),
                        follow_up_due_at = COALESCE(?, follow_up_due_at),
                        message_variant = COALESCE(?, message_variant),
                        last_outreach_result = COALESCE(?, last_outreach_result),
                        last_outreach_error = ?
                    WHERE ig_username = ? AND (? IS NULL OR workspace_id = ?)
                    ''',
                    (new_status, datetime.now().isoformat(), sent_at, follow_up_due_at, message_variant, result, error_detail, username, self.workspace_id, self.workspace_id),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error actualizando resultado de mensaje para @{username}: {e}")

    def update_account_warmup_log(self, ig_username: str, log_data: dict):
        """Guarda el log JSON de warmeo de sesion en la tabla ig_accounts."""
        try:
            import json
            log_str = json.dumps(log_data, ensure_ascii=False)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    UPDATE ig_accounts
                    SET session_warmup_phase = ?
                    WHERE ig_username = ?
                    ''',
                    (log_str, ig_username),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error guardando log de warmup para cuenta @{ig_username}: {e}")

    def get_stats(self) -> Dict[str, int]:
        """Obtiene conteo rápido de estados para dashboard."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT status, COUNT(*) as count 
                    FROM leads 
                    GROUP BY status
                ''')
                rows = cursor.fetchall()
                return {row['status']: row['count'] for row in rows}
        except Exception:
            return {}

    def sanitize_leads_source(self, source: str) -> None:
        """Normaliza el source de leads existentes para mantener trazabilidad consistente."""
        try:
            normalized = source.strip()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE leads SET source = ? WHERE source = ?",
                    (normalized, source),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error sanitizando source {source}: {e}")
