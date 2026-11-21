import { useEffect, useRef, type RefObject } from "react";

export function useMobileNavigation(
  isOpen: boolean,
  triggerRef: RefObject<HTMLButtonElement | null>,
  navigationRef: RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const navigation = navigationRef.current;
    const getFocusableElements = () => {
      const elements = Array.from(
        navigation?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.tabIndex >= 0);
      const selectedRadio = navigation?.querySelector<HTMLInputElement>(
        'input[type="radio"]:checked',
      );

      return elements.filter(
        (element) =>
          !(element instanceof HTMLInputElement && element.type === "radio") ||
          element === selectedRadio,
      );
    };

    getFocusableElements()[0]?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        triggerRef.current?.focus();
        return;
      }

      if (event.key !== "Tab" || !navigation) return;

      const focusableElements = getFocusableElements();
      const first = focusableElements[0];
      const last = focusableElements.at(-1);
      if (!first || !last) {
        event.preventDefault();
        triggerRef.current?.focus();
        return;
      }

      const focusIsOutside = !navigation.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || focusIsOutside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || focusIsOutside)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen, navigationRef, triggerRef]);
}
