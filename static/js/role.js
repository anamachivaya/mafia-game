// Client logic for the role page. This file centralizes polling, voting, night actions and UI updates.
(function(){
  // Read globals injected by template: PLAYER_NAME, ROOM_NAME, PLAYER_ROLE, PLAYER_FACTION, ROLE_DESCRIPTION
  const POLL_INTERVAL = 2500;

  function qs(id){ return document.getElementById(id); }

  function showToast(msg, short){
    const t = qs('toast');
    if(!t) return;
    t.textContent = msg;
    t.classList.add('visible');
    clearTimeout(t._timeout);
    t._timeout = setTimeout(()=> t.classList.remove('visible'), short?2000:4000);
  }

  async function fetchRoom(){
    try{
      const res = await fetch(`/api/rooms/${encodeURIComponent(ROOM_NAME)}/players`, {cache:'no-store'});
      if(!res.ok) return null;
      return await res.json();
    }catch(e){ return null; }
  }

  function renderBasicInfo(){
    const nameEl = qs('playerName');
    const roleEl = qs('roleBadge');
    const descEl = qs('roleDescription');
    const factionEl = qs('factionBadge');
    if(nameEl) nameEl.textContent = `Welcome, ${PLAYER_NAME}`;
    if(roleEl) roleEl.textContent = PLAYER_ROLE || '—';
    if(descEl) descEl.textContent = ROLE_DESCRIPTION || '';
    if(factionEl) factionEl.textContent = PLAYER_FACTION || '';
  }

  function renderVisibleRoles(data){
    const wrap = qs('visibleRoles');
    if(!wrap) return;
    wrap.innerHTML = '';
    const v = data.visible_roles || [];
    if(v.length === 0){ wrap.innerHTML = '<div class="muted">No extra roles visible</div>'; return; }
    v.forEach(item => {
      const div = document.createElement('div');
      div.className = 'visible-role';
      div.innerHTML = `<strong>${item.name}</strong> — <em>${item.role}</em>`;
      wrap.appendChild(div);
    });
  }

  function renderStatus(data){
    const s = qs('statusIndicator');
    const lu = qs('lastUpdated');
    const eliminated = (data.eliminated_players||[]).includes(PLAYER_NAME);
    if(s) s.textContent = eliminated ? 'ELIMINATED 💀' : 'ALIVE';
    if(lu) lu.textContent = 'Last checked: ' + (new Date()).toLocaleTimeString();
    if(eliminated){ document.body.classList.add('eliminated'); }
  }

  function renderVoting(data){
    const v = data.voting || {active:false};
    const votingWrap = qs('votingArea');
    if(!votingWrap) return;
    votingWrap.innerHTML = '';
    if(!v.active){
      votingWrap.innerHTML = '<div class="muted">No active voting session</div>';
      return;
    }

    const current = v.current_voter;
    const ism = (current === PLAYER_NAME);
    const header = document.createElement('div'); header.className='v-header';
    header.textContent = `Voting: ${ism ? 'Your turn to vote' : `Current voter: ${current}`}`;
    votingWrap.appendChild(header);

    if(ism){
      // allow voting for alive players
      const list = document.createElement('div'); list.className='choices';
      (data.players||[]).forEach(p=>{
        if(p===PLAYER_NAME) return;
        const btn = document.createElement('button'); btn.className='btn small'; btn.textContent = p;
        btn.addEventListener('click', async ()=>{
          btn.disabled = true;
          try{
            const resp = await fetch(`/api/rooms/${encodeURIComponent(ROOM_NAME)}/vote`, { method:'POST', body: new URLSearchParams({choice:p}) });
            const j = await resp.json();
            if(!resp.ok) showToast(j.error || 'Vote failed'); else showToast('Vote submitted');
          }catch(e){ showToast('Network error'); }
        });
        list.appendChild(btn);
      });
      votingWrap.appendChild(list);
    }else{
      // show tally / log
      const tally = v.tally || {};
      const tallyEl = document.createElement('div'); tallyEl.className='tally';
      for(const k of Object.keys(tally)){
        const row = document.createElement('div'); row.textContent = `${k}: ${tally[k]}`; tallyEl.appendChild(row);
      }
      votingWrap.appendChild(tallyEl);
    }
  }

  function openNightModal(data){
    const modal = qs('nightModal');
    if(!modal) return;
    // populate targets list
    const container = qs('nightTargets'); container.innerHTML = '';
    const alive = (data.players||[]).filter(p=> (data.eliminated_players||[]).indexOf(p)===-1 );
    alive.forEach(p=>{
      if(p===PLAYER_NAME) return;
      const b = document.createElement('button'); b.className='btn small'; b.textContent = p;
      b.addEventListener('click', async ()=>{
        // submit action
        const act = modal.dataset.actionType || 'mafia_final';
        try{
          const resp = await fetch(`/api/rooms/${encodeURIComponent(ROOM_NAME)}/action`, { method:'POST', body: new URLSearchParams({action_type: act, target: p}) });
          const j = await resp.json();
          if(!resp.ok) showToast(j.error || 'Action failed'); else showToast('Action submitted');
          closeNightModal();
        }catch(e){ showToast('Network error'); }
      });
      container.appendChild(b);
    });
    modal.classList.add('open');
  }

  function closeNightModal(){ const m=qs('nightModal'); if(m) m.classList.remove('open'); }

  async function handleSuicideSubmit(choice){
    try{
      const resp = await fetch(`/api/rooms/${encodeURIComponent(ROOM_NAME)}/suicide`, { method:'POST', body: new URLSearchParams({target: choice}) });
      const j = await resp.json();
      if(!resp.ok) showToast(j.error || 'Suicide failed'); else showToast('Choice submitted');
    }catch(e){ showToast('Network error'); }
  }

  // Main poll loop
  async function pollOnce(){
    const data = await fetchRoom();
    if(!data) return;
    renderBasicInfo();
    renderStatus(data);
    renderVisibleRoles(data);
    renderVoting(data);

    // suicide prompt
    if(data.suicide_prompt && data.suicide_prompt.active){
      const sp = qs('suicideChoices'); sp.innerHTML = '';
      (data.suicide_prompt.choices || []).forEach(c=>{
        const b = document.createElement('button'); b.className='btn small danger'; b.textContent=c;
        b.addEventListener('click', ()=> handleSuicideSubmit(c));
        sp.appendChild(b);
      });
      qs('suicideCard').classList.remove('hidden');
    } else {
      qs('suicideCard').classList.add('hidden');
    }
  }

  // Wire up UI events
  document.addEventListener('DOMContentLoaded', ()=>{
    const toggle = qs('toggleRole'); if(toggle) toggle.addEventListener('click', ()=>{ const rb=qs('roleBadge'); const d=qs('roleDescription'); if(rb&&d){ const hidden = rb.classList.toggle('hidden'); d.classList.toggle('hidden'); toggle.textContent = hidden ? 'Show role' : 'Hide role'; } });
    const nightBtn = qs('nightActionBtn'); if(nightBtn) nightBtn.addEventListener('click', ()=>{ const modal = qs('nightModal'); if(modal) { modal.dataset.actionType = nightBtn.dataset.actionType || 'mafia_final'; openNightModal(window._lastRoomData||{}); } });
    const nightClose = qs('nightClose'); if(nightClose) nightClose.addEventListener('click', closeNightModal);
    const suicideClose = qs('suicideClose'); if(suicideClose) suicideClose.addEventListener('click', ()=>qs('suicideCard').classList.add('hidden'));

    // Kick off polling
    pollOnce().then(()=>{});
    setInterval(async ()=>{ const d = await fetchRoom(); if(d){ window._lastRoomData = d; pollOnce(); } }, POLL_INTERVAL);
  });

  // expose small helpers for debugging
  window.rolePage = { pollOnce, openNightModal, closeNightModal, showToast };

})();
