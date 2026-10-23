/* Structured prose editing. The adapter owns persistence and proposal decisions. */
import {Schema} from 'prosemirror-model';
import {EditorState, Plugin, TextSelection} from 'prosemirror-state';
import {EditorView} from 'prosemirror-view';
import {baseKeymap, splitBlockAs} from 'prosemirror-commands';
import {keymap} from 'prosemirror-keymap';
import {history, undo, redo, closeHistory} from 'prosemirror-history';

const editors = new Map();
let activeKey=null;
const id = () => `block-${crypto.randomUUID()}`;
const types = {narration:'旁白', action:'动作', dialogue:'对白'};
const schema = new Schema({nodes:{
  doc:{content:'scene_block+'},
  scene_block:{
    content:'inline*', group:'block',
    attrs:{id:{default:null}, type:{default:'narration'}, speaker:{default:''}},
    parseDOM:[{tag:'p', getAttrs:node=>({id:null, type:types[node.dataset.proseType]?node.dataset.proseType:'narration', speaker:node.dataset.proseSpeaker||''})}, {tag:'div'}],
    toDOM:node=>['p', {'data-prose-type':node.attrs.type,'data-prose-speaker':node.attrs.speaker}, 0],
  },
  text:{group:'inline'},
  hard_break:{inline:true, group:'inline', selectable:false, parseDOM:[{tag:'br'}], toDOM:()=>['br']},
}});
const canonical = blocks => blocks.filter(block=>block.text.trim()).map(block=>({id:block.id,type:block.type,speaker:block.type==='dialogue'?block.speaker||'':'',text:block.text}));
function docFrom(blocks) {
  const seen = new Set();
  return schema.node('doc',null,(blocks.length?blocks:[{type:'narration',text:''}]).map(block=>{
    const blockId=block.id&&!seen.has(block.id)?block.id:id(); seen.add(blockId);
    const content=[];
    String(block.text||'').split('\n').forEach((line,i)=>{if(i)content.push(schema.node('hard_break'));if(line)content.push(schema.text(line));});
    return schema.node('scene_block',{id:blockId,type:types[block.type]?block.type:'narration',speaker:block.speaker||''},content);
  }));
}
function blocksFrom(doc) {
  const blocks=[];
  doc.forEach(node=>blocks.push({...node.attrs,text:node.textBetween(0,node.content.size,'\n','\n')}));
  return blocks;
}
const identities = new Plugin({appendTransaction(transactions, oldState, state){
  if(!transactions.some(tr=>tr.docChanged))return null;
  const seen=new Set(); let tr=null;
  state.doc.forEach((node,pos)=>{
    let blockId=node.attrs.id;
    if(!blockId||seen.has(blockId)){blockId=id();tr ||= state.tr;tr.setNodeMarkup(pos,null,{...node.attrs,id:blockId});}
    seen.add(blockId);
  });
  return tr;
}});

class ParagraphView {
  constructor(node, view, getPos) {
    this.view=view;this.getPos=getPos;
    this.dom=document.createElement('article');this.dom.className='chapter-document-block';this.dom.dataset.chapterBlock='';
    this.dom.innerHTML='<span class="chapter-document-number" contenteditable="false" aria-hidden="true"></span><div class="chapter-document-body"><div class="chapter-document-meta" contenteditable="false" data-block-controls><select aria-label="段落类型" data-chapter-type><option value="narration">旁白</option><option value="action">动作</option><option value="dialogue">对白</option></select><input aria-label="说话人" data-chapter-speaker placeholder="说话人"></div><p data-chapter-text></p></div><div class="chapter-document-actions" contenteditable="false" data-block-controls><button type="button" data-document-move="up" aria-label="上移段落" title="上移段落">↑</button><button type="button" data-document-move="down" aria-label="下移段落" title="下移段落">↓</button><button type="button" data-document-remove aria-label="删除段落" title="删除段落">×</button></div>';
    this.contentDOM=this.dom.querySelector('[data-chapter-text]');
    this.type=this.dom.querySelector('[data-chapter-type]');this.speaker=this.dom.querySelector('[data-chapter-speaker]');
    this.type.addEventListener('change',()=>this.setAttrs({type:this.type.value,...(this.type.value==='dialogue'?{}:{speaker:''})}));
    this.speaker.addEventListener('input',()=>this.setAttrs({speaker:this.speaker.value}));
    this.dom.querySelector('.chapter-document-actions').addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;event.preventDefault();event.stopPropagation();
      const owner=editors.get(view.dom.dataset.documentKey);owner?.changeBlock(this.node.attrs.id,button.dataset.documentMove||'remove');
    });
    this.update(node);
  }
  setAttrs(attrs) {
    const pos=this.getPos();if(typeof pos!=='number')return;
    const node=this.view.state.doc.nodeAt(pos);if(!node)return;
    this.view.dispatch(this.view.state.tr.setNodeMarkup(pos,null,{...node.attrs,...attrs}));
  }
  update(node) {
    if(node.type!==schema.nodes.scene_block)return false;
    this.node=node;this.dom.dataset.blockId=node.attrs.id;this.dom.dataset.blockType=node.attrs.type;
    if(this.type.value!==node.attrs.type)this.type.value=node.attrs.type;
    if(this.speaker.value!==node.attrs.speaker)this.speaker.value=node.attrs.speaker;
    this.speaker.hidden=node.attrs.type!=='dialogue';
    this.type.title=`段落类型：${types[node.attrs.type]}`;
    return true;
  }
  stopEvent(event){return Boolean(event.target.closest?.('[data-block-controls]'));}
  ignoreMutation(mutation){return mutation.type==='attributes'||mutation.type!=='selection'&&!this.contentDOM.contains(mutation.target);}
}

class ManuscriptDocument {
  constructor(options) {
    this.options=options;
    this.root=document.createElement('div');this.root.className='chapter-document';
    const enter=splitBlockAs(node=>({type:node.type,attrs:{...node.attrs,id:id()}}));
    this.view=new EditorView(this.root,{
      state:EditorState.create({doc:docFrom(options.blocks),plugins:[identities,history(),keymap({'Mod-z':undo,'Mod-Shift-z':redo,'Mod-y':redo,'Enter':enter,'Shift-Enter':(state,dispatch)=>{if(dispatch)dispatch(state.tr.replaceSelectionWith(schema.node('hard_break')).scrollIntoView());return true;}}),keymap(baseKeymap)]}),
      attributes:{class:'chapter-document-content','data-document-key':options.key,role:'textbox','aria-multiline':'true','aria-label':'场景正文',spellcheck:'false'},
      nodeViews:{scene_block:(node,view,getPos)=>new ParagraphView(node,view,getPos)},
      dispatchTransaction:tr=>{
        activeKey=this.options.key;
        const next=this.view.state.apply(tr);this.view.updateState(next);this.decorate();
        if(tr.docChanged)this.options.onChange(blocksFrom(next.doc));
        if(!this.view.composing)this.selectionChanged();
      },
      handleDOMEvents:{
        beforeinput:(view,event)=>{
          // Chromium keeps empty custom-node wrappers when native text input
          // replaces a selection across paragraphs. Apply that replacement as
          // a document transaction; composition stays with the editor core.
          if(event.inputType==='insertText'&&!event.isComposing&&!view.composing&&!view.state.selection.$from.sameParent(view.state.selection.$to)){
            event.preventDefault();view.dispatch(view.state.tr.insertText(event.data||'').scrollIntoView());return true;
          }
          return false;
        },
        focus:()=>{activeKey=this.options.key;return false;},
        blur:()=>{this.tools.hidden=true;return false;},
        compositionend:()=>{queueMicrotask(()=>this.options.onChange(this.blocks()));return false;},
      },
    });
    this.tools=document.createElement('div');this.tools.className='chapter-document-selection';this.tools.hidden=true;this.tools.setAttribute('role','group');this.tools.setAttribute('aria-label','选中正文的操作');
    this.tools.addEventListener('mousedown',event=>{if(event.target.closest('button'))event.preventDefault();});
    this.root.append(this.tools);this.decorate();
  }
  blocks(){return blocksFrom(this.view.state.doc);}
  decorate(){
    const current=this.view.state.selection.$head.parent.attrs.id;
    [...this.view.dom.querySelectorAll('[data-chapter-block]')].forEach((node,index)=>{
      node.setAttribute('aria-label',`第 ${index+1} 段`);
      node.querySelector('.chapter-document-number').textContent=String(index+1).padStart(2,'0');
      node.querySelector('[data-chapter-text]').setAttribute('aria-label',`第 ${index+1} 段正文`);
      node.classList.toggle('is-active',node.dataset.blockId===current);
      node.classList.toggle('is-empty',this.view.state.doc.child(index).content.size===0);
    });
  }
  selectionChanged(){
    const selection=this.view.state.selection;
    if(selection.empty||!selection.$from.sameParent(selection.$to)){this.tools.hidden=true;this.options.onSelection?.(null);return;}
    const block=selection.$from.parent;
    const range={block_id:block.attrs.id,local_start:selection.$from.parentOffset,local_end:selection.$to.parentOffset,quote:block.textBetween(selection.$from.parentOffset,selection.$to.parentOffset,'\n','\n')};
    const actions=this.options.onSelection?.(range);
    if(!actions){this.tools.hidden=true;return;}
    this.tools.innerHTML=actions;this.tools.hidden=false;
    const start=this.view.coordsAtPos(selection.from),end=this.view.coordsAtPos(selection.to),bounds=this.root.getBoundingClientRect();
    this.tools.style.left=`${Math.max(0,Math.min(start.left-bounds.left,bounds.width-this.tools.offsetWidth))}px`;
    this.tools.style.top=`${Math.max(0,Math.min(start.top,end.top)-bounds.top-this.tools.offsetHeight-8)}px`;
  }
  changeBlock(blockId,action){
    const state=this.view.state;let pos=0,index=0,node=null;
    state.doc.forEach((item,at,i)=>{if(item.attrs.id===blockId){pos=at;index=i;node=item;}});
    if(!node)return;
    let tr=closeHistory(state.tr),target=pos;
    if(action==='remove')tr.delete(pos,pos+node.nodeSize);
    else if(action==='up'&&index>0){target=pos-state.doc.child(index-1).nodeSize;tr.delete(pos,pos+node.nodeSize).insert(target,node);}
    else if(action==='down'&&index<state.doc.childCount-1){target=pos+state.doc.child(index+1).nodeSize;tr.delete(pos,pos+node.nodeSize).insert(target,node);}
    else return;
    tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(target+1,tr.doc.content.size))));
    this.view.dispatch(tr.scrollIntoView());this.view.focus();
  }
  focus(){this.view.focus();}
  update(options){
    this.options=options;
    if(JSON.stringify(canonical(this.blocks()))!==JSON.stringify(canonical(options.blocks))){
      this.view.updateState(EditorState.create({doc:docFrom(options.blocks),plugins:this.view.state.plugins}));this.decorate();
    }
  }
}

window.HaloCueManuscriptDocument={
  mount(host,options){
    let editor=editors.get(options.key);
    if(!editor){editor=new ManuscriptDocument(options);editors.set(options.key,editor);}else editor.update(options);
    host.append(editor.root);return editor;
  },
  get:key=>editors.get(key),
  get composing(){return [...editors.values()].some(editor=>editor.root.isConnected&&editor.view.composing);},
  can(action){const editor=editors.get(activeKey);return Boolean(editor?.root.isConnected&&(action==='undo'?undo:redo)(editor.view.state));},
  run(action){const editor=editors.get(activeKey);if(editor?.root.isConnected){(action==='undo'?undo:redo)(editor.view.state,tr=>editor.view.dispatch(tr));editor.focus();}},
  retain(keys){for(const [key,editor] of editors)if(!keys.has(key)){editor.view.destroy();editor.root.remove();editors.delete(key);}},
  preserveFocus(){
    const focused=document.activeElement;
    if(focused?.matches('[data-chapter-save]')&&editors.get(activeKey)?.root.isConnected)return {key:activeKey};
    for(const [key,editor] of editors)if(editor.view.dom.contains(focused))return {key,blockId:focused.closest('[data-chapter-block]')?.dataset.blockId,control:focused.matches('[data-chapter-speaker]')?'speaker':focused.matches('[data-chapter-type]')?'type':null,start:focused.selectionStart,end:focused.selectionEnd};
    return null;
  },
  restoreFocus(saved){
    const editor=saved&&editors.get(saved.key);if(!editor)return;
    const control=saved.control&&editor.root.querySelector(`[data-block-id="${CSS.escape(saved.blockId)}"] [data-chapter-${saved.control}]`);
    if(control){control.focus({preventScroll:true});if(saved.control==='speaker')control.setSelectionRange(saved.start,saved.end);}
    else editor.focus();
  },
  canonical,
};
