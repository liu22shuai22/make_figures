import type { DiagramKind } from '../types'
import { useLocale } from '../LocaleContext'

interface Props {
  value: DiagramKind
  onChange: (kind: DiagramKind) => void
  disabled?: boolean
}

export default function DiagramKindSwitch({ value, onChange, disabled }: Props) {
  const { app: t } = useLocale()
  const options: { id: DiagramKind; label: string }[] = [
    { id: 'er', label: 'E-R' },
    { id: 'usecase', label: t.kindUsecase },
  ]

  return (
    <div className="kind-switch" role="group" aria-label={t.kindAria} data-testid="diagram-kind-switch">
      {options.map((option) => {
        const on = value === option.id
        return (
          <button
            key={option.id}
            type="button"
            className={'kind-switch-btn' + (on ? ' is-on' : '')}
            aria-pressed={on}
            disabled={disabled}
            onClick={() => onChange(option.id)}
            data-testid={`kind-${option.id}`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
