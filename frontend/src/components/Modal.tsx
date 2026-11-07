import { useEffect, useRef } from "react";

interface Props {
  title: string;
  /** Short line under the title; read out with the dialog. */
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  /** The Cancel / Save row. Standard order: Cancel first, primary action last. */
  footer?: React.ReactNode;
  width?: number;
}

/**
 * A focused edit, in the pattern every other system uses: a native <dialog>
 * opened modally, so the browser traps focus and handles Escape; focus starts
 * on the first field and returns to the trigger on close.
 */
export default function Modal({ title, description, onClose, children, footer, width = 760 }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    const d = ref.current;
    if (d && !d.open) d.showModal();
    // Start on the first field, not on Close, so typing begins where it should.
    const field = d?.querySelector<HTMLElement>(
      ".modal-body input:not([type=hidden]):not(:disabled), .modal-body select:not(:disabled), .modal-body textarea:not(:disabled)",
    );
    (field ?? d?.querySelector<HTMLElement>("button:not(:disabled)"))?.focus();
    return () => {
      if (d?.open) d.close();
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className="modal"
      style={{ maxWidth: width }}
      aria-labelledby="modal-title"
      aria-describedby={description ? "modal-desc" : undefined}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // click on the backdrop
      }}
    >
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <header className="modal-head">
          <div>
            <h2 id="modal-title">{title}</h2>
            {description && <p id="modal-desc" className="small muted">{description}</p>}
          </div>
          <button type="button" className="icon modal-x" onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </form>
    </dialog>
  );
}
