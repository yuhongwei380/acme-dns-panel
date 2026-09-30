'use strict';
// Progressive enhancement: native selects remain the source of form values and change events.
let selectCounter = 0;
let openSelect = null;
function enhanceSelects(root = document) {
  root.querySelectorAll('select:not([data-enhanced])').forEach(select => {
    select.dataset.enhanced = 'true';
    const wrapper = document.createElement('div'); wrapper.className = 'select-control';
    select.before(wrapper); wrapper.append(select); select.hidden = true;
    const id = 'panel-select-' + (++selectCounter);
    const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'select-trigger';
    trigger.id = id; trigger.setAttribute('role','combobox'); trigger.setAttribute('aria-haspopup','listbox');
    trigger.setAttribute('aria-expanded','false'); trigger.setAttribute('aria-controls',id+'-list');
    const caption = select.closest('label')?.firstChild?.textContent.trim() || select.name;
    trigger.setAttribute('aria-label',caption);
    const menu = document.createElement('div'); menu.className = 'select-menu'; menu.id = id+'-list'; menu.hidden = true;
    menu.setAttribute('role','listbox'); menu.setAttribute('aria-label',caption);
    wrapper.append(trigger,menu);
    let active = select.selectedIndex, typed = '', typedAt = 0;
    function options() { return Array.from(select.options); }
    function paint() {
      trigger.disabled = select.disabled;
      trigger.replaceChildren();
      const text = document.createElement('span'); text.textContent = select.selectedOptions[0]?.textContent || '请选择';
      const arrow = document.createElement('span'); arrow.className = 'select-arrow'; arrow.setAttribute('aria-hidden','true');
      trigger.append(text,arrow);
      menu.replaceChildren();
      options().forEach((option,index) => {
        const row = document.createElement('div'); row.className = 'select-option'; row.id = id+'-option-'+index;
        row.setAttribute('role','option'); row.setAttribute('aria-selected',String(index===select.selectedIndex));
        row.setAttribute('aria-disabled',String(option.disabled)); row.textContent = option.textContent;
        row.classList.toggle('highlighted',index===active); row.dataset.index = index;
        menu.append(row);
      });
      if (!menu.hidden && active>=0) trigger.setAttribute('aria-activedescendant',id+'-option-'+active);
      else trigger.removeAttribute('aria-activedescendant');
    }
    function close() {menu.hidden=true;trigger.setAttribute('aria-expanded','false');trigger.removeAttribute('aria-activedescendant');if(openSelect?.trigger===trigger)openSelect=null;}
    function open() {
      if(select.disabled)return;
      openSelect?.close();active=select.selectedIndex;menu.hidden=false;trigger.setAttribute('aria-expanded','true');
      openSelect={trigger,wrapper,close};paint();
    }
    function move(index) {
      active=index;paint();document.getElementById(id+'-option-'+active)?.scrollIntoView({block:'nearest'});
    }
    function choose(index) {
      if(index<0||options()[index]?.disabled)return;
      select.selectedIndex=index;active=index;close();paint();
      select.dispatchEvent(new Event('change',{bubbles:true}));trigger.focus();
    }
    trigger.addEventListener('click',()=>menu.hidden?open():close());
    menu.addEventListener('pointerdown',event=>event.preventDefault());
    // Cancel the surrounding label's default activation of its hidden native select.
    menu.addEventListener('click',event=>{event.preventDefault();const row=event.target.closest('[data-index]');if(row)choose(Number(row.dataset.index));});
    trigger.addEventListener('keydown',event=>{
      if(event.key==='Escape'){if(!menu.hidden){event.preventDefault();event.stopPropagation();close();}return;}
      if(event.key==='Tab'){close();return;}
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
        event.preventDefault();if(menu.hidden)open();
        const enabled=options().map((o,i)=>o.disabled?-1:i).filter(i=>i>=0);
        if(!enabled.length)return;
        const position=enabled.indexOf(active);
        const next=event.key==='Home'?enabled[0]:event.key==='End'?enabled[enabled.length-1]:enabled[Math.max(0,Math.min(enabled.length-1,position+(event.key==='ArrowDown'?1:-1)))];
        move(next);return;
      }
      if(event.key==='Enter'||event.key===' '){event.preventDefault();if(menu.hidden)open();else choose(active);return;}
      if(event.key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
        event.preventDefault();if(menu.hidden)open();
        const time=Date.now();typed=time-typedAt>800?event.key:typed+event.key;typedAt=time;
        const index=options().findIndex(o=>!o.disabled&&o.textContent.toLowerCase().startsWith(typed.toLowerCase()));if(index>=0)move(index);
      }
    });
    select.addEventListener('change',()=>{active=select.selectedIndex;paint();});
    paint();
  });
}
document.addEventListener('click',event=>{if(openSelect&&!openSelect.wrapper.contains(event.target))openSelect.close();});
document.addEventListener('focusin',event=>{if(openSelect&&!openSelect.wrapper.contains(event.target))openSelect.close();});
document.addEventListener('close',()=>openSelect?.close(),true);
