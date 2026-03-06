"""
PrimeBot Core - Smoke Test
===========================
Verifica que las dependencias core están instaladas y el entorno es funcional.
Ejecutar: python scripts/smoke_test.py
"""

import sys
import importlib

DEPENDENCIES = {
    "dotenv": "python-dotenv",
    "ppadb": "pure-python-adb",
    "ddgs": "ddgs",
}

def check_dependency(module_name: str, pip_name: str) -> bool:
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "N/A")
        print(f"  ✅ {pip_name} ({module_name}) - v{version}")
        return True
    except ImportError:
        print(f"  ❌ {pip_name} ({module_name}) - NO INSTALADO")
        return False

def main():
    print("=" * 50)
    print("🔧 PrimeBot Core - Smoke Test")
    print(f"   Python: {sys.version}")
    print("=" * 50)
    print()

    print("📦 Verificando dependencias:")
    results = []
    for module_name, pip_name in DEPENDENCIES.items():
        results.append(check_dependency(module_name, pip_name))

    print()
    ok = sum(results)
    total = len(results)
    print(f"📊 Resultado: {ok}/{total} dependencias disponibles")

    if all(results):
        print("🟢 Entorno OPERATIVO. Listo para trabajar.")
        return 0
    else:
        print("🟡 Algunas dependencias faltan. Ejecutá:")
        print("   pip install -r requirements.txt")
        return 1

if __name__ == "__main__":
    sys.exit(main())
