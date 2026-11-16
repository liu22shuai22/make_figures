import { CANVAS_RATIOS, type CanvasRatio } from '../types'

interface Props {
  ratio: CanvasRatio
  disabled: boolean
  onChange: (ratio: CanvasRatio) => void
}

export default function CanvasRatioSelect({ ratio, disabled, onChange }: Props) {
  return (
    <label className="canvas-ratio">
      画布比例
      <select value={ratio} disabled={disabled} onChange={(event) => onChange(event.target.value as CanvasRatio)}>
        {CANVAS_RATIOS.map((option) => (
          <option key={option} value={option}>{option === 'auto' ? '自动' : option}</option>
        ))}
      </select>
    </label>
  )
}
