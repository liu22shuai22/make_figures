import { useId, useRef, useState } from 'react'

interface AccountMenuProps {
  username: string
  onLogout: () => void
}

function PersonIcon() {
  return (
    <svg className="user-chip-mark" width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="8.2" r="4.2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M4.5 20c1.3-3.6 4.1-5.4 7.5-5.4S18.2 16.4 19.5 20" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

/** 已登录顶栏的账户卡片。 */
export default function AccountMenu({ username, onLogout }: AccountMenuProps) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  const close = () => {
    setOpen(false)
    trigger.current?.focus()
  }

  return (
    <div
      className="account-menu"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
      }}
      onKeyDown={(event) => {
        if (open && event.key === 'Escape' && !event.nativeEvent.isComposing) {
          event.preventDefault()
          close()
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        className="user-chip user-chip-btn"
        title={`已登录：${username}`}
        data-testid="user-chip"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((previous) => !previous)}
      >
        <PersonIcon />
        <span className="user-chip-name">{username}</span>
        <svg className="user-chip-caret" width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2.2 3.8 5 6.5 7.8 3.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div id={panelId} className="account-menu-panel" role="menu">
          <div className="account-card-head">
            <span className="account-initial" aria-hidden="true">
              {username.trim().slice(0, 1).toLocaleUpperCase()}
            </span>
            <span className="account-id">
              <strong>{username}</strong>
            </span>
          </div>
          <button
            type="button"
            role="menuitem"
            className="account-menu-item account-menu-item-muted"
            data-testid="logout"
            onClick={() => {
              setOpen(false)
              onLogout()
            }}
          >
            退出登录
          </button>
        </div>
      )}
    </div>
  )
}
