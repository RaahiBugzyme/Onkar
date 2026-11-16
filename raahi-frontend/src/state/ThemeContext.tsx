import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { generationThemes, type GenerationId } from '../data/generations'

const THEME_STORAGE_KEY = 'raahiGenerationTheme.v1'

function readSavedGeneration(): GenerationId {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved && saved in generationThemes) return saved as GenerationId
  } catch {
    // Keep the default theme when browser storage is unavailable.
  }
  return 'genz'
}

interface ThemeContextValue {
  generation: GenerationId
  setGeneration: (generation: GenerationId) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [generation, setGenerationState] = useState<GenerationId>(readSavedGeneration)
  const setGeneration = useCallback((next: GenerationId) => {
    setGenerationState(next)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Theme still changes for this session when browser storage is unavailable.
    }
  }, [])
  const theme = generationThemes[generation]

  return (
    <ThemeContext.Provider value={useMemo(() => ({ generation, setGeneration }), [generation])}>
      <div
        className="app-shell"
        data-theme={generation}
        style={{
          '--ep': theme.primary,
          '--es': theme.secondary,
          '--glow': theme.glow,
          '--cbg': theme.cardBackground,
          '--cbr': theme.cardBorder,
          '--bd': theme.background,
        } as React.CSSProperties}
      >
        {children}
      </div>
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const value = useContext(ThemeContext)
  if (!value) throw new Error('useTheme must be used inside ThemeProvider')
  return value
}
