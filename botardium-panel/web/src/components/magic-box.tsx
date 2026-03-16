"use client"

import React, { useState } from 'react'
import { Search, Sparkles, Target, ArrowRight } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { apiUrl } from '@/lib/api'

type StrategyResult = {
    sources: Array<{
        type: 'hashtag' | 'followers' | 'location'
        target: string
    }>
    reasoning: string
    filter_context?: {
        intent_summary?: string
        include_terms?: string[]
        exclude_terms?: string[]
    }
}

const typeLabel: Record<StrategyResult['sources'][number]['type'], string> = {
    hashtag: 'Hashtag tecnico',
    followers: 'Cuenta semilla',
    location: 'Mercado geografico',
}

export function MagicBox({
    onStrategyApplied,
    workspaceId,
    disabled = false,
    disabledReason,
    onRequireSetup,
}: {
    onStrategyApplied: (data: StrategyResult) => void
    workspaceId?: number | null
    disabled?: boolean
    disabledReason?: string
    onRequireSetup?: () => void
}) {
    const [prompt, setPrompt] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [result, setResult] = useState<StrategyResult | null>(null)

    const handleMagicSearch = async (e: React.FormEvent) => {
        e.preventDefault()
        if (disabled) {
            toast.error(disabledReason || 'Necesitas configurar API keys para usar Magic Box.')
            onRequireSetup?.()
            return
        }
        if (!prompt || !workspaceId) return

        setIsLoading(true)
        try {
            // LLamada a FastAPI Backend
            const res = await fetch(apiUrl('/api/ai/strategy'), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt, workspace_id: workspaceId })
            })

            const data = await res.json()
            if (!res.ok) {
                toast.error(data.detail || 'La IA no pudo generar una ruta valida.')
                if (res.status === 412) onRequireSetup?.()
                return
            }

            if (!Array.isArray(data?.sources) || data.sources.length === 0) {
                toast.error('La IA devolvio una estrategia incompleta. Intenta refinar el prompt.')
                return
            }

            setResult(data)
        } catch (error) {
            console.error("Error connecting to Magic Box API", error)
            toast.error('No pude conectar con el backend de estrategia.')
        } finally {
            setIsLoading(false)
        }
    }

    const applyStrategy = () => {
        if (result && onStrategyApplied) {
            onStrategyApplied(result)
            setResult(null)
            setPrompt("")
        }
    }

    return (
        <div className="my-8 w-full max-w-3xl">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl transition-all duration-300">

                {/* Input Area */}
                <div className="p-4 bg-slate-900 flex items-center gap-3">
                    <Sparkles className="w-6 h-6 text-purple-400" />
                    <form onSubmit={handleMagicSearch} className="flex-1 flex gap-3 overflow-hidden">
                        <input
                            type="text"
                            placeholder="Ej: Busco dueños de agencias de marketing en España que necesiten software..."
                            className="w-full bg-transparent border-0 outline-none focus:outline-none focus:ring-0 focus:border-transparent text-slate-100 placeholder:text-slate-500 text-base md:text-lg px-2"
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            disabled={isLoading || disabled}
                        />
                        <button
                            type="submit"
                            disabled={isLoading || !prompt}
                            onClick={disabled ? (e) => { e.preventDefault(); onRequireSetup?.(); } : undefined}
                            title={disabled ? (disabledReason || 'Necesitas API keys para usar Magic Box.') : undefined}
                            className={`px-5 lg:px-6 py-2 rounded-xl font-medium transition-colors flex items-center justify-center gap-2 whitespace-nowrap flex-shrink-0 min-w-[140px] ${disabled ? 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30 hover:bg-rose-500/20' : 'bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50'}`}
                        >
                            {isLoading ? (
                                <div className="flex items-center gap-1.5">
                                    <motion.div animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.2 }} className="w-1.5 h-1.5 bg-white rounded-full" />
                                    <motion.div animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.2, delay: 0.2 }} className="w-1.5 h-1.5 bg-white rounded-full" />
                                    <motion.div animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.2, delay: 0.4 }} className="w-1.5 h-1.5 bg-white rounded-full" />
                                </div>
                            ) : (
                                <>
                                    Generar Ruta
                                    <Search className="w-4 h-4" />
                                </>
                            )}
                        </button>
                    </form>
                </div>
                {disabled && (
                    <div className="border-t border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                        {disabledReason || 'Necesitas API keys para usar Magic Box.'}
                    </div>
                )}

                {/* AI Result Area */}
                <AnimatePresence>
                    {result && (
                        <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            exit={{ opacity: 0, height: 0 }}
                            className="bg-slate-800/50 p-6 border-t border-slate-700/50"
                        >
                            <h3 className="text-sm font-semibold text-purple-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                                <Target className="w-4 h-4" />
                                Estrategia Sugerida
                            </h3>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                <div className="col-span-2 space-y-2">
                                    <p className="text-slate-300 leading-relaxed text-sm">
                                        {result.reasoning}
                                    </p>
                                    <div className="flex flex-wrap gap-4 mt-4">
                                        {result.sources.filter((source) => source.type === 'hashtag').map((source, index) => (
                                            <div key={`${source.type}-${source.target}-${index}`} className={`px-4 py-2 rounded-lg border flex flex-col ${index === 0 ? 'bg-cyan-500/10 border-cyan-500/30' : 'bg-slate-900 border-slate-700'}`}>
                                                <span className="text-xs text-slate-500 uppercase">{typeLabel[source.type]}</span>
                                                <span className="font-medium text-slate-200">{source.type === 'hashtag' ? '#' : source.type === 'followers' ? '@' : ''}{source.target}</span>
                                                {index === 0 ? <span className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-cyan-300">Principal</span> : null}
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="flex items-end justify-end">
                                    <button
                                        onClick={applyStrategy}
                                        className="bg-slate-100 hover:bg-white text-slate-900 px-6 py-3 rounded-xl font-semibold w-full flex items-center justify-center gap-2 transition-all shadow-lg hover:shadow-xl"
                                        title="Aplica estos parámetros automáticamente en el panel de scraping"
                                    >
                                        Auto-Rellenar
                                        <ArrowRight className="w-4 h-4" />
                                    </button>
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </div>
    )
}
