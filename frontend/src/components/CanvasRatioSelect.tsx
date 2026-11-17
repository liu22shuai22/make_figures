import { CANVAS_RATIOS, type CanvasRatio } from '../types'
import { useLocale } from '../LocaleContext'

interface Props {
  ratio: CanvasRatio
  disabled: boolean
  onChange: (ratio: CanvasRatio) => void
}

export default function CanvasRatioSelect({ ratio, disabled, onChange }: Props) {
  const { app } = useLocale()
  return (
    <label className="canvas-ratio">
      {app.canvasRatio}
      <select value={ratio} disabled={disabled} onChange={(event) => onChange(event.target.value as CanvasRatio)}>
        {CANVAS_RATIOS.map((option) => (
          <option key={option} value={option}>
            {option === 'auto' ? app.canvasAuto : option}
          </option>
        ))}
      </select>
    </label>
  )
}
