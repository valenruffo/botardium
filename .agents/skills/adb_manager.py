"""
PrimeBot Core — ADB Manager
================================
Control de dispositivos Android via pure-python-adb.
Gestiona conexión, rotación de IP (Modo Avión) y captura de pantalla.

Dependencias: pure-python-adb
Consulta: directivas/memoria_maestra.md § 4 (Reglas de IP)
"""

import asyncio
import time
import random
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger("primebot.adb")

# Directorio para screenshots de diagnóstico
TMP_DIR = Path(__file__).resolve().parent.parent.parent / ".tmp"


class ADBManager:
    """
    Gestiona la comunicación con un dispositivo Android via ADB.

    Uso:
        mgr = ADBManager()
        mgr.connect()
        mgr.rotate_ip()  # Toggle Modo Avión
        mgr.take_screenshot("diagnostico")
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5037,
        device_serial: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.device_serial = device_serial
        self._client = None
        self._device = None
        self._rotation_count = 0

    def connect(self) -> bool:
        """
        Conecta al ADB server y obtiene el dispositivo.

        Returns:
            True si la conexión fue exitosa.
        """
        try:
            from ppadb.client import Client as AdbClient

            self._client = AdbClient(host=self.host, port=self.port)
            devices = self._client.devices()

            if not devices:
                logger.error("❌ No se encontraron dispositivos ADB conectados.")
                return False

            if self.device_serial:
                self._device = self._client.device(self.device_serial)
                if not self._device:
                    logger.error(f"❌ Dispositivo {self.device_serial} no encontrado.")
                    return False
            else:
                self._device = devices[0]
                self.device_serial = self._device.serial

            logger.info(f"✅ Conectado a dispositivo ADB: {self.device_serial}")
            return True

        except Exception as e:
            logger.error(f"❌ Error conectando ADB: {e}")
            return False

    def is_connected(self) -> bool:
        """Verifica si hay una conexión activa."""
        return self._device is not None

    def execute_shell(self, command: str) -> Optional[str]:
        """
        Ejecuta un comando shell en el dispositivo.

        Args:
            command: Comando a ejecutar.

        Returns:
            Output del comando o None si falla.
        """
        if not self._device:
            logger.error("❌ No hay dispositivo conectado. Ejecutar connect() primero.")
            return None

        try:
            result = self._device.shell(command)
            logger.debug(f"ADB Shell: {command} → {str(result)[:100]}")
            return result
        except Exception as e:
            logger.error(f"❌ Error ejecutando shell '{command}': {e}")
            return None

    def _get_public_ip(self) -> Optional[str]:
        """Obtiene la IP publica actual via request HTTP simple al exterior."""
        try:
            # Usamos un Timeout corto porque si falla la red, queremos saber rapido
            req = urllib.request.Request(
                "https://api.ipify.org",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                ip = response.read().decode("utf-8").strip()
                return ip
        except Exception as e:
            logger.warning(f"⚠️ No se pudo verificar la IP actual: {e}")
            return None

    def rotate_ip(self, wait_range: tuple = (5, 10)) -> bool:
        """
        Rota la IP del dispositivo togglando Modo Avión ON → espera → OFF.

        Esto fuerza al carrier a asignar una nueva IP al reconectar la red móvil.
        Consulta: memoria_maestra.md § 4 — solo para cuentas prospectoras.

        Args:
            wait_range: Rango de espera (en segundos) con Modo Avión activado.

        Returns:
            True si la rotación fue exitosa.
        """
        if not self._device:
            logger.error("❌ No hay dispositivo conectado.")
            return False

        try:
            wait_time = random.uniform(*wait_range)
            
            # 1. Obtener IP actual
            old_ip = self._get_public_ip()
            if old_ip:
                logger.info(f"   IP actual: {old_ip}")
            else:
                logger.warning("   No se pudo leer la IP previa (posible red offline)")

            # 2. Activar Modo Avión
            logger.info("✈️  Activando Modo Avión...")
            self.execute_shell("settings put global airplane_mode_on 1")
            self.execute_shell(
                "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true"
            )

            # 3. Espera para que la red se desconecte completamente
            logger.info(f"   ⏳ Esperando {wait_time:.1f}s para nueva IP...")
            time.sleep(wait_time)

            # 4. Desactivar Modo Avión
            logger.info("📶 Desactivando Modo Avión...")
            self.execute_shell("settings put global airplane_mode_on 0")
            self.execute_shell(
                "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"
            )

            # 5. Espera a que la red se restablezca y verificar nueva IP
            logger.info("   ⏳ Esperando conexion de red (max 20s)...")
            new_ip = None
            retry_count = 0
            
            while retry_count < 4:
                time.sleep(5)
                new_ip = self._get_public_ip()
                if new_ip:
                    break
                logger.info("      ...esperando red...")
                retry_count += 1

            # 6. Validar cambio
            if not new_ip:
                logger.error("❌ Falló la reconexión de red despues del Modo Avión.")
                return False
                
            if old_ip and new_ip == old_ip:
                logger.warning(f"⚠️ La IP no cambió. Sigue siendo {new_ip}.")
                return False

            self._rotation_count += 1
            logger.info(
                f"✅ IP rotada exitosamente: {old_ip} → {new_ip} (Rotación #{self._rotation_count})"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Error rotando IP: {e}")
            return False

    def take_screenshot(self, name: str = "screenshot") -> Optional[Path]:
        """
        Captura la pantalla del dispositivo y guarda en .tmp/.

        Args:
            name: Nombre base del archivo (sin extensión).

        Returns:
            Path del archivo guardado o None si falla.
        """
        if not self._device:
            logger.error("❌ No hay dispositivo conectado.")
            return None

        try:
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = TMP_DIR / f"{name}_{timestamp}.png"

            result = self._device.screencap()
            with open(filepath, "wb") as fp:
                fp.write(result)

            logger.info(f"📸 Screenshot guardado: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"❌ Error capturando pantalla: {e}")
            return None

    @property
    def rotation_count(self) -> int:
        """Cantidad de rotaciones de IP realizadas en esta sesión."""
        return self._rotation_count
