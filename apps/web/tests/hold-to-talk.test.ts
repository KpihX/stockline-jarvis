/**
 * canHoldTalk: which keyboard focus lets Space start a recording. The real gestures (key repeat, pointer capture, touch,
 * no double fire) are checked in a browser by scripts/ui-check/hold-to-talk.py.
 * Run: pnpm --filter @kit/web test
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { canHoldTalk } from "../src/lib/hold-to-talk";

/** A minimal element: `tag` + attributes, closest() understands the comma-separated selectors used by the module. */
function el(tag: string, opts: { attrs?: Record<string, string>; focusVisible?: boolean; editable?: boolean; parent?: ReturnType<typeof el> } = {}) {
  const self: any = {
    tag, isContentEditable: !!opts.editable, parent: opts.parent,
    matches: (sel: string) => sel === ":focus-visible" && !!opts.focusVisible,
    closest(selector: string): unknown {
      const alts = selector.split(/,\s*(?![^\[]*\])/).map((s) => s.trim());
      for (let n: any = self; n; n = n.parent) {
        for (const a of alts) {
          const role = /^\[role='(.+)'\]$/.exec(a)?.[1];
          const attr = /^\[([\w-]+)\]$/.exec(a)?.[1];
          const editable = a.startsWith("[contenteditable]") && n.isContentEditable;
          if (a === n.tag || editable || (role && n.attrs?.role === role) || (attr && n.attrs && attr in n.attrs)) return n;
        }
      }
      return null;
    },
    attrs: opts.attrs,
  };
  return self as EventTarget;
}

test("body / document: Space talks, in both scopes", () => {
  assert.equal(canHoldTalk(null, "global"), true);
  assert.equal(canHoldTalk({} as EventTarget, "page"), true);
});

test("text fields never talk", () => {
  for (const scope of ["page", "global"] as const) {
    assert.equal(canHoldTalk(el("input"), scope), false);
    assert.equal(canHoldTalk(el("textarea"), scope), false);
    assert.equal(canHoldTalk(el("select"), scope), false);
    assert.equal(canHoldTalk(el("div", { editable: true }), scope), false);
  }
});

test("a keyboard-focused button keeps Space on the global scope, the page scope still talks", () => {
  const b = el("button", { focusVisible: true });
  assert.equal(canHoldTalk(b, "global"), false);
  assert.equal(canHoldTalk(b, "page"), true);
});

test("a button focused by a mouse click does not keep Space (Space talks)", () => {
  assert.equal(canHoldTalk(el("button", { focusVisible: false }), "global"), true);
});

test("menu items / tabs reached by keyboard keep Space", () => {
  assert.equal(canHoldTalk(el("div", { attrs: { role: "menuitem" }, focusVisible: true }), "global"), false);
  assert.equal(canHoldTalk(el("div", { attrs: { role: "tab" }, focusVisible: true }), "global"), false);
});

test("a talk button always gets Space, even keyboard-focused", () => {
  const talk = el("button", { attrs: { "data-hold-to-talk": "call" }, focusVisible: true });
  assert.equal(canHoldTalk(talk, "global"), true);
});

test("a link has no Space action: Space talks", () => {
  assert.equal(canHoldTalk(el("a", { focusVisible: true }), "global"), true);
});
