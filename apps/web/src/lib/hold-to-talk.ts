/**
 * Hold-to-talk gestures, ONE implementation for every talk surface (header "Voix" button, Voix page call + command
 * modes, big round buttons). Two ways in, both "press = start, release = stop":
 *
 *   - keyboard: hold Space (anywhere that is not a text field). ⌥ Space also works, inside text fields too, where the
 *     OS lets it through (Alt+Space is the window menu on Windows and GNOME: a shortcut advertised alone would not work).
 *   - pointer: click-and-hold (mouse, touch, pen). Pointer capture: releasing outside the button still stops.
 *
 * Guards: key auto-repeat is ignored; Space typed in a field, or used by a keyboard-focused button / menu item, is left
 * alone; a talk button never fires twice (one window-level listener handles Space even when the button has focus, the
 * button itself only handles the pointer); a tap shorter than MIN_HOLD_MS is an accident, not an utterance.
 */
import { useEffect, useRef, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";

/** Shorter than this = an accidental tap or click: nothing is sent. */
export const MIN_HOLD_MS = 300;

/** Marks a talk button: Space is always for it, even when the button has keyboard focus. */
export const HOLD_TO_TALK_ATTR = "data-hold-to-talk";

const TYPING = "input, textarea, select, [contenteditable]:not([contenteditable='false'])";
const SPACE_ACTIVATES =
  "button, summary, [role='button'], [role='menuitem'], [role='option'], [role='tab'], [role='checkbox'], [role='switch'], [role='radio'], [role='combobox'], [role='slider'], [role='treeitem']";

interface MaybeElement {
  closest?: (selector: string) => unknown;
  matches?: (selector: string) => boolean;
  isContentEditable?: boolean;
}

/**
 * May Space start a recording when the key goes down on `target`?
 *   scope "page"   → the page IS a talk surface: yes, unless the user is typing.
 *   scope "global" → any page: also not when a button / menu item reached by the KEYBOARD has focus (Space activates it).
 *                    A button focused by a mouse click does not count (`:focus-visible` is false): Space talks.
 */
export function canHoldTalk(target: EventTarget | null, scope: "page" | "global"): boolean {
  const el = target as MaybeElement | null;
  if (!el || typeof el.closest !== "function") return true; // document / body
  if (el.isContentEditable || el.closest(TYPING)) return false;
  if (el.closest(`[${HOLD_TO_TALK_ATTR}]`)) return true;
  if (scope === "page") return true;
  return !(el.closest(SPACE_ACTIVATES) && focusVisible(el));
}

function focusVisible(el: MaybeElement): boolean {
  try { return !!el.matches?.(":focus-visible"); } catch { return false; }
}

export interface SpaceHoldOptions {
  start: () => void;
  stop: () => void;
  scope: "page" | "global";
  /** Plain Space (default true). The global listener turns it off on /voice, where the page owns Space. */
  plain?: boolean;
  /** ⌥ Space, even inside text fields (default false). */
  alt?: boolean;
  onEscape?: () => void;
}

/** Window-level Space (and optionally ⌥ Space) hold-to-talk. The options may change on every render. */
export function useSpaceHold(options: SpaceHoldOptions) {
  const opts = useRef(options);
  opts.current = options;
  useEffect(() => {
    let held = false;
    let viaAlt = false;
    const end = () => {
      if (!held) return;
      held = false;
      viaAlt = false;
      opts.current.stop();
    };
    const down = (e: KeyboardEvent) => {
      const o = opts.current;
      if (e.code === "Space") {
        if (e.defaultPrevented || e.metaKey || e.ctrlKey) return;
        const alt = e.altKey;
        const plain = !e.altKey && !e.shiftKey;
        if (!((alt && o.alt) || (plain && o.plain !== false && canHoldTalk(e.target, o.scope)))) return;
        e.preventDefault(); // no page scroll, no click on a focused button
        if (e.repeat || held) return;
        held = true;
        viaAlt = alt;
        o.start();
      } else if (e.key === "Escape" && !held) {
        o.onEscape?.();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (!held || !(e.code === "Space" || (viaAlt && e.key === "Alt"))) return;
      e.preventDefault();
      end();
    };
    const hidden = () => { if (document.hidden) end(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", end);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", end);
      document.removeEventListener("visibilitychange", hidden);
      end();
    };
  }, []);
}

/** Props that make any element a click-and-hold (mouse, touch, pen) talk button. Spread them on a <button>. */
export function useHoldPointer(start: () => void, stop: () => void) {
  const held = useRef(false);
  const fns = useRef({ start, stop });
  fns.current = { start, stop };
  const end = () => {
    if (!held.current) return;
    held.current = false;
    fns.current.stop();
  };
  return {
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => {
      if (e.button !== 0 || held.current) return;
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* synthetic event: no capture, the pointerup still comes */ }
      held.current = true;
      fns.current.start();
    },
    onPointerUp: end,
    onPointerCancel: end,
    onLostPointerCapture: end,
    onContextMenu: (e: ReactMouseEvent) => e.preventDefault(), // a long press on touch screens
    style: { touchAction: "none" } as const, // no scroll / zoom gesture stealing the hold
  };
}
