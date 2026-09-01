import { useEffect, useRef, useState } from "react";
import { MoreVertical, Sun, Moon, Monitor, Check, LogOut, type LucideIcon } from "lucide-react";
import { useTheme, type Theme } from "../hooks/useTheme";
import { signOut } from "../hooks/useSession";

const THEME_OPTIONS: { value: Theme; label: string; icon: LucideIcon }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export default function TopbarMenu() {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="topbar-menu" ref={ref}>
      <button
        className={"topbar-menu-btn" + (open ? " open" : "")}
        onClick={() => setOpen((o) => !o)}
        aria-label="Settings"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <MoreVertical size={18} />
      </button>
      {open && (
        <div className="topbar-dropdown" role="menu">
          <div className="topbar-dropdown-label">Theme</div>
          {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              className="topbar-dropdown-item"
              role="menuitemradio"
              aria-checked={theme === value}
              onClick={() => {
                setTheme(value);
                setOpen(false);
              }}
            >
              <Icon size={15} />
              {label}
              {theme === value && <Check size={14} className="check" />}
            </button>
          ))}
          <div className="topbar-dropdown-divider" />
          <button
            className="topbar-dropdown-item danger"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              signOut();
            }}
          >
            <LogOut size={15} />
            Logout
          </button>
        </div>
      )}
    </div>
  );
}
