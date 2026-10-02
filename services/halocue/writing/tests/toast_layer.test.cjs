const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const start = source.indexOf('function toast('), end = source.indexOf('function setBusy(', start);

function harness({popover = true} = {}) {
  function node(name) {
    const classes = new Set(), listeners = new Map();
    const n = {name, dataset: {}, children: [], attributes: {},
      classList: {add: (...xs) => xs.forEach(x=>classes.add(x)), remove: (...xs) => xs.forEach(x=>classes.delete(x)), toggle: (x,on)=>on?classes.add(x):classes.delete(x), contains: x=>classes.has(x)},
      setAttribute(k,v) {this.attributes[k] = v;},
      append(...children) {children.forEach(child=>this.appendChild(child));},
      appendChild(child) {child.parentElement=this; this.children.push(child);},
      replaceChildren() {this.children=[];},
      addEventListener(k,fn) {listeners.set(k,fn);},
      removeEventListener(k,fn) {if(listeners.get(k)===fn) listeners.delete(k);},
      dispatch(k) {listeners.get(k)?.();},
      matches(selector) {return selector === ':popover-open' ? Boolean(this.popoverOpen) : Boolean(this.modal);},
    };
    if (popover) { n.showPopover=()=>{n.popoverOpen=true;}; n.hidePopover=()=>{n.popoverOpen=false;}; }
    return n;
  }
  const body=node('body'), first=node('dialog1'), second=node('dialog2'), toast=node('toast');
  first.modal=second.modal=true;
  body.appendChild(toast);
  const h={body,first,second,toast,dialogs:[first]};
  const context={document:{body,createElement:node,querySelectorAll:()=>h.dialogs}, $:()=>toast,
    state:{feedbackError:null},setTimeout:()=>1,clearTimeout:()=>{}};
  vm.createContext(context);
  vm.runInContext(source.slice(start,end),context);
  h.show=(bad=true)=>context.toast('Synthetic result',bad);
  h.dismiss=()=>context.dismissToast();
  return h;
}

test('toast is interactive inside modal and promoted to top layer',()=>{
  const h=harness(); h.show();
  assert.equal(h.toast.parentElement,h.first);
  assert.equal(h.toast.popoverOpen,true);
  assert.equal(h.toast.attributes.role,'alert');
  h.dismiss();
  assert.equal(h.toast.popoverOpen,false);
  assert.equal(h.toast.parentElement,h.body);
  assert(!h.toast.classList.contains('show'));
});

test('toast follows most recently opened modal and closes with its host',()=>{
  const h=harness(); h.show(); h.dialogs.push(h.second); h.show(false);
  assert.equal(h.toast.parentElement,h.second);
  h.first.dispatch('close');
  assert(h.toast.classList.contains('show'));
  h.second.dispatch('close');
  assert(!h.toast.classList.contains('show'));
  assert.equal(h.toast.parentElement,h.body);
});

test('older webviews still mount feedback in the active modal',()=>{
  const h=harness({popover:false}); h.show();
  assert.equal(h.toast.parentElement,h.first);
  h.dismiss(); h.dialogs=[]; h.show(false);
  assert.equal(h.toast.parentElement,h.body);
  assert.equal(h.toast.attributes.role,'status');
});
