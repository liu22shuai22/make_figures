import { useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import type { DiagramLayout, EntityBox } from '../types'
import { useLocale } from '../LocaleContext'

interface DragOverlayProps {
  layout: DiagramLayout
  onMove: (entity: string, x: number, y: number) => void
  onMoveRelation: (index: number, x: number, y: number) => void
}

type DragBox = EntityBox & { relationIndex?: number }

export default function DragOverlay({ layout, onMove, onMoveRelation }: DragOverlayProps) {
  const { app } = useLocale()
  const p = app.preview
  const overlay = useRef<HTMLDivElement>(null)
  const pointer = useRef<{ id: number; box: DragBox; clientX: number; clientY: number } | null>(null)
  const [ghost, setGhost] = useState<DragBox | null>(null)
  const boxes: DragBox[] = [
    ...layout.entities,
    ...(layout.dependencyLabels ?? layout.relations ?? [])
      .map(({ name, index, ...box }) => ({ ...box, entity: name, relationIndex: index })),
  ]

  const withinFrame = (box: DragBox, x: number, y: number) => ({
    ...box,
    x: Math.max(layout.x + box.width / 2, Math.min(x, layout.x + layout.width - box.width / 2)),
    y: Math.max(layout.y + box.height / 2, Math.min(y, layout.y + layout.height - box.height / 2)),
  })

  const begin = (event: PointerEvent<HTMLButtonElement>, box: DragBox) => {
    if (event.button !== 0 || pointer.current) return
    event.currentTarget.setPointerCapture(event.pointerId)
    pointer.current = { id: event.pointerId, box, clientX: event.clientX, clientY: event.clientY }
    setGhost(box)
  }

  const move = ({ entity, x, y, relationIndex }: DragBox) => {
    if (relationIndex === undefined) onMove(entity, x, y)
    else onMoveRelation(relationIndex, x, y)
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
      move(next)
    }
  }

  return (
    <div className="drag-overlay" ref={overlay} aria-label={p.dragAria}>
      {boxes.map((box) => {
        const relation = box.relationIndex !== undefined
        const moving = ghost?.entity === box.entity && ghost.relationIndex === box.relationIndex
        const displayed = moving ? ghost : box
        return (
          <button
            key={relation ? `relation-${box.relationIndex}` : `entity-${box.entity}`}
            type="button"
            className={`drag-entity${moving ? ' is-moving' : ''}`}
            style={{
              left: `${100 * (displayed.x - layout.x) / layout.width}%`,
              top: `${100 * (displayed.y - layout.y) / layout.height}%`,
              width: `${100 * displayed.width / layout.width}%`,
              height: `${100 * displayed.height / layout.height}%`,
            }}
            aria-label={relation && !layout.dependencyLabels ? p.moveRelation(box.entity) : p.moveEntity(box.entity)}
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
              if (next.x !== box.x || next.y !== box.y) move(next)
            }}
          >
            {moving && box.entity}
          </button>
        )
      })}
    </div>
  )
}
