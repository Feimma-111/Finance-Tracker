import { useEffect, useRef, type ReactNode } from "react";

/**
 * An Apple-style sheet: a card that rises over a dimmed page. Built on the
 * native <dialog> element, which handles Escape, keeps keyboard focus inside,
 * and makes the page behind it inert. On phones it docks to the bottom.
 */
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);

  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault(); // Escape: let React decide, so state stays in sync
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // click on the dimmed backdrop
      }}
    >
      <div className="sheet-body">
        <div className="sheet-head">
          <button type="button" className="btn-link" onClick={onClose}>Cancel</button>
          <h2>{title}</h2>
          <span />
        </div>
        {children}
      </div>
    </dialog>
  );
}
