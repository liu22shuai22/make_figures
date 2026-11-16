import { useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import type { DiagramLayout, EntityBox } from '../types'

interface DragOverlayProps {
  layout: DiagramLayout
  onMove: (entity: string, x: number, y: number) => void
}

export default function DragOverlay({ layout, onMove }: DragOverlayProps) {
  const overlay = useRef<HTMLDivElement>(null)
  const pointer = useRef<{ id: number; box: EntityBox; clientX: number; clientY: number } | null>(null)
  const [ghost, setGhost] = useState<EntityBox | null>(null)

  const withinFrame = (box: EntityBox, x: number, y: number) => ({
    ...box,
    x: Math.max(layout.x + box.width / 2, Math.min(x, layout.x + layout.width - box.width / 2)),
    y: Math.max(layout.y + box.height / 2, Math.min(y, layout.y + layout.height - box.height / 2)),
  })

  const begin = (event: PointerEvent<HTMLButtonElement>, box: EntityBox) => {
    if (event.button !== 0 || pointer.current) return
    event.currentTarget.setPointerCapture(event.pointerId)
    pointer.current = { id: event.pointerId, box, clientX: event.clientX, clientY: event.clientY }
    setGhost(box)
  }

  const destination = (event: PointerEvent<HTMLButtonElement>) => {
    const active = pointer.current
    const frame = overlay.current?.getBoundingClientRect()
    if (!active || active.id !== event.pointerId || !frame?.width || !frame.height) return null
    const dx = event.clientX - active.clientX
    const dy = event.clientY - active.clientY
    if (Math.hypot(dx, dy) < 3) return active.box
    return withinFrame(active.box,
      active.box.x + dx * layout.width / frame.width,
      active.box.y + dy * layout.height / frame.height,
    )
  }

  const cancel = (event: PointerEvent<HTMLButtonElement>) => {
    if (pointer.current?.id !== event.pointerId) return
    pointer.current = null
    setGhost(null)
  }

  const finish = (event: PointerEvent<HTMLButtonElement>) => {
    const next = destination(event)
    const previous = pointer.current?.box
    cancel(event)
    if (next && previous && (next.x !== previous.x || next.y !== previous.y)) {
      onMove(next.entity, next.x, next.y)
    }
  }

  return (
    <div className="drag-overlay" ref={overlay} aria-label="整体图实体位置">
      {layout.entities.map((box) => {
        const moving = ghost?.entity === box.entity
        const displayed = moving ? ghost : box
        return (
          <button
            key={box.entity}
            type="button"
            className={`drag-entity${moving ? ' is-moving' : ''}`}
            style={{
              left: `${100 * (displayed.x - layout.x) / layout.width}%`,
              top: `${100 * (displayed.y - layout.y) / layout.height}%`,
              width: `${100 * displayed.width / layout.width}%`,
              height: `${100 * displayed.height / layout.height}%`,
            }}
            aria-label={`移动${box.entity}`}
            onPointerDown={(event) => begin(event, box)}
            onPointerMove={(event) => {
              const next = destination(event)
              if (next) setGhost(next)
            }}
            onPointerUp={finish}
            onPointerCancel={cancel}
            onLostPointerCapture={cancel}
            onKeyDown={(event) => {
              const dx = (Number(event.key === 'ArrowRight') - Number(event.key === 'ArrowLeft')) * 0.15
              const dy = (Number(event.key === 'ArrowDown') - Number(event.key === 'ArrowUp')) * 0.15
              if (!dx && !dy) return
              event.preventDefault()
              const next = withinFrame(box, box.x + dx, box.y + dy)
              if (next.x !== box.x || next.y !== box.y) onMove(box.entity, next.x, next.y)
            }}
          >
            {moving && box.entity}
          </button>
        )
      })}
    </div>
  )
}
