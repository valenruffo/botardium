"use client";

export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <main className="min-h-screen bg-slate-950 flex items-center justify-center p-6 text-slate-50">
      <div className="w-full max-w-xl rounded-3xl border border-rose-500/20 bg-slate-900 p-8 shadow-2xl">
        <p className="text-xs uppercase tracking-[0.2em] text-rose-300">Error de interfaz</p>
        <h1 className="mt-3 text-3xl font-semibold">La app encontró un error de cliente</h1>
        <p className="mt-4 text-sm text-slate-300">
          Botardium recuperó el runtime visual. Puedes reintentar sin perder el backend. Si vuelve a pasar, recarga con Ctrl+F5.
        </p>
        <div className="mt-6 flex gap-3">
          <button onClick={reset} className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white hover:bg-rose-500">
            Reintentar
          </button>
          <button onClick={() => window.location.reload()} className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700">
            Recargar página
          </button>
        </div>
      </div>
    </main>
  );
}
