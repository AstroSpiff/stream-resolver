async function jget(url) { const r = await fetch(url, { credentials: "omit" }); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function jpost(url, body) { const r = await fetch(url, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body || {}) }); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function jdel(url) { const r = await fetch(url, { method: "DELETE" }); if (!r.ok) throw new Error(await r.text()); return r.json(); }
function byId(id){ return document.getElementById(id); }
let _lists = []; // per popolare le select Xtream
let _editingXt = null; // id xtream in modifica
let _activeInlineEditor = null; // traccia un solo editor inline aperto
function cancelActiveInlineEdit(){ if(_activeInlineEditor && _activeInlineEditor.container){ const { container, prev } = _activeInlineEditor; try{ container.textContent = ''; prev.forEach(n=>container.appendChild(n)); }catch(e){ /* ignore */ } } _activeInlineEditor = null; }
// --- Helpers: validazione URL ---
function isValidAbsoluteHttpUrl(u){ try{ const url = new URL((u||'').trim()); return url.protocol === 'http:' || url.protocol === 'https:'; }catch(e){ return false; } }
function isValidIPv4Host(s){ const parts = s.split('.'); if(parts.length !== 4) return false; return parts.every(p=>{ if(!/^\d{1,3}$/.test(p)) return false; const n=+p; return n>=0 && n<=255; }); }
function isValidHostPortOrHttp(u){ u = (u||'').trim(); if(!u) return false; if(/^https?:\/\//i.test(u)) return isValidAbsoluteHttpUrl(u); // IPv6: [::1]:8080
let m = u.match(/^\[([0-9A-Fa-f:]+)\]:(\d{1,5})$/);
if(m){ const port = +m[2]; return port>=1 && port<=65535; } // IPv4: 1.2.3.4:8080
m = u.match(/^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$/);
if(m){ if(!isValidIPv4Host(m[1])) return false; const port=+m[2]; return port>=1 && port<=65535; } // hostname:port (localhost or domain)
m = u.match(/^([A-Za-z0-9.-]+):(\d{1,5})$/);
if(m){ const host=m[1]; if(!host) return false; if(/\.\.|^-|-$|^\.|\.$/.test(host)) return false; const port=+m[2]; return port>=1 && port<=65535; } return false; }
// --- Inline edit utility ---
function startInlineEdit(container, opts){ // Se c'è un altro editor attivo, annulla prima di aprire questo
if(_activeInlineEditor){ if(_activeInlineEditor.container === container){ const existing = container.querySelector('input,select'); if(existing) existing.focus(); return; } cancelActiveInlineEdit(); } // opts: { value, type, placeholder, validator(value)->bool, normalizer(value)->string, onSave(value), onCancel() }
const prev = Array.from(container.childNodes);
let control;
if(opts && opts.kind === 'select'){ const sel = document.createElement('select'); sel.innerHTML = opts.optionsHtml || ''; sel.value = (opts.value != null ? String(opts.value) : ''); control = sel; }else{ const input = document.createElement('input'); input.type = opts.type || 'text'; input.value = opts.value || ''; if(opts.placeholder) input.placeholder = opts.placeholder; input.size = Math.min(60, Math.max(12, (input.value || '').length + 4)); control = input; }
const save = document.createElement('button'); save.className = 'tiny btn-save'; save.textContent = 'Salva';
const cancel = document.createElement('button'); cancel.className = 'tiny btn-cancel'; cancel.textContent = 'Annulla'; // clear and inject editor
container.textContent = '';
const wrap = document.createElement('span'); wrap.className = 'inline-editor'; wrap.appendChild(control); wrap.appendChild(save); wrap.appendChild(cancel); container.appendChild(wrap);
control.focus();
if(control.select) try{ control.select(); } catch(_e){} _activeInlineEditor = { container, prev };
const finish = (ok)=>{ // restore view; caller will re-render row on save
container.textContent = '';
prev.forEach(n=>container.appendChild(n));
if(!ok && typeof opts.onCancel === 'function') opts.onCancel();
if(_activeInlineEditor && _activeInlineEditor.container === container){ _activeInlineEditor = null; } };
const doSave = async ()=>{ let val = (control.value != null ? String(control.value) : '').trim(); if(opts.validator && !opts.validator(val)) return; // validator shows its own alert
if(opts.normalizer) val = opts.normalizer(val);
await opts.onSave(val); // caller should trigger a re-render; we still restore to avoid flicker
finish(true); };
save.onclick = doSave;
cancel.onclick = ()=> finish(false);
control.addEventListener('keydown', (e)=>{ if(e.key === 'Enter') { e.preventDefault(); doSave(); } if(e.key === 'Escape') { e.preventDefault(); finish(false); } }); }
// ---------------- Settings ----------------
async function loadSettings(){ try{ const { settings } = await jget("/admin/settings.json");
_sr = Array.isArray(settings.resolvers) ? settings.resolvers.slice() : [];
_mf = Array.isArray(settings.mediaflows) ? settings.mediaflows.slice() : [];
renderSRList();
renderMFList();
populateResolverDropdowns();
populateMFDropdown(); // Popola anche il select dell'Endpoint resolver in Gestione Xtream
const xSel = byId('xt_resolver');
if(xSel){ // se stiamo modificando un xtream, preserva il valore corrente, altrimenti placeholder
const current = xSel.value || '';
xSel.innerHTML = buildResolverOptionsHtml(current); } // DB & TMDB
const dbu = (settings.database_url || '');
_dbps = Array.isArray(settings.db_profiles) ? settings.db_profiles.slice() : [];
_activeDb = (settings.active_db || 'default');
const tmdb = settings.tmdb || {};
const key = tmdb.api_key || '';
const lang = tmdb.language || 'it-IT';
const dbInp = byId('cfg_dburl'); if(dbInp) dbInp.value = dbu;
renderDbProfiles();
const keyInp = byId('cfg_tmdb_key'); if(keyInp) keyInp.value = key;
const langInp = byId('cfg_tmdb_lang'); if(langInp) langInp.value = lang;
const mf = (settings.tmdb && settings.tmdb.movie_fields) || [];
const ms = (settings.tmdb && settings.tmdb.series_fields) || [];
const mseas = (settings.tmdb && settings.tmdb.season_fields) || [];
const me = (settings.tmdb && settings.tmdb.episode_fields) || [];
const has = (arr, key)=> (arr||[]).includes(key) || (key==='name' && (arr||[]).includes('title'));
const setCk = (id, arr, key)=>{ const el=byId(id); if(el) el.checked = has(arr, key); };
setCk('tmf_name', mf, 'name');
setCk('tmf_original_title', mf, 'original_title');
setCk('tmf_overview', mf, 'overview');
setCk('tmf_poster', mf, 'poster');
setCk('tmf_backdrop', mf, 'backdrop');
setCk('tmf_logo', mf, 'logo');
setCk('tmf_rating', mf, 'rating');
setCk('tmf_year', mf, 'year');
setCk('tmf_release_date', mf, 'release_date');
setCk('tmf_duration', mf, 'duration');
setCk('tmf_imdb', mf, 'imdb_id');
setCk('tmf_genres', mf, 'genres');
setCk('tmf_production_countries', mf, 'production_countries');
setCk('tmf_cast', mf, 'cast');
setCk('tmf_director', mf, 'director');
setCk('tmf_writers', mf, 'writers');
setCk('tmf_tagline', mf, 'tagline');
setCk('tmf_collection', mf, 'collection');
setCk('tmf_youtube_trailer', mf, 'youtube_trailer');
setCk('tmf_production_companies', mf, 'production_companies');
setCk('tmf_certification', mf, 'certification');
setCk('ms_name', ms, 'name');
setCk('ms_original_name', ms, 'original_name');
setCk('ms_overview', ms, 'overview');
setCk('ms_poster', ms, 'poster');
setCk('ms_backdrop', ms, 'backdrop');
setCk('ms_logo', ms, 'logo');
setCk('ms_rating', ms, 'rating');
setCk('ms_first_air_date', ms, 'first_air_date');
setCk('ms_year', ms, 'year');
setCk('ms_duration', ms, 'duration');
setCk('ms_imdb', ms, 'imdb_id');
setCk('ms_genres', ms, 'genres');
setCk('ms_cast', ms, 'cast');
setCk('ms_created_by', ms, 'created_by');
setCk('ms_networks', ms, 'networks');
setCk('ms_status', ms, 'status');
setCk('ms_tagline', ms, 'tagline');
setCk('ms_youtube_trailer', ms, 'youtube_trailer');
setCk('ms_seasons', ms, 'seasons'); // Season
setCk('tms_name', mseas, 'name');
setCk('tms_season_number', mseas, 'season_number');
setCk('tms_first_air_date', mseas, 'first_air_date');
setCk('tms_episode_count', mseas, 'episode_count');
setCk('tms_overview', mseas, 'overview');
setCk('tms_poster', mseas, 'poster');
setCk('tms_backdrop', mseas, 'backdrop');
setCk('tms_tmdb', mseas, 'tmdb_id'); // Episode
setCk('tme_name', me, 'name');
setCk('tme_overview', me, 'overview');
setCk('tme_air_date', me, 'air_date');
setCk('tme_still', me, 'still');
setCk('tme_duration', me, 'duration');
setCk('tme_rating', me, 'rating');
setCk('tme_guests', me, 'guest_stars');
setCk('tme_crew', me, 'crew');
setCk('tme_imdb', me, 'imdb_id');
}catch(e){ console.error(e); } // DB ping per TMDB
try{ const st = await jget('/admin/db/ping');
const dbs = byId('dbStatus');
const upd = byId('btnTmdbUpdate');
const miss = byId('btnTmdbMissing'); // Nuovi pannelli info (Settings)
const sSimple = byId('dbStatusSimple');
const sUrl = byId('dbUrlDisplay');
const sSrc = byId('dbSource');
if(dbs){ if(st.ok){ dbs.textContent = `DB: connesso (${st.url})`; } else{ dbs.textContent = `DB: non raggiungibile (${st.url}) – ${st.error||''}`; } }
if(sSimple){ sSimple.textContent = st.ok ? 'Connesso' : `Non raggiungibile${st.error? ' – '+st.error:''}`; }
if(sUrl){ sUrl.textContent = st.url || ''; }
if(sSrc){ sSrc.textContent = (st.source === 'env') ? 'Variabile d\'ambiente' : 'settings'; }
if(upd) upd.disabled = !st.ok;
if(miss) miss.disabled = !st.ok; // Se la sorgente è env, blocca i campi di configurazione DB e mostra nota
try{ const note = byId('dbSourceNote');
const isEnv = (st && st.source === 'env');
const disable = (el)=>{ if(el){ el.setAttribute('disabled','disabled'); el.classList.add('disabled'); } };
if(isEnv){ if(note){ note.textContent = 'Sorgente DB: variabile d\'ambiente DATABASE_URL (UI in sola lettura).'; } }else{ if(note){ note.textContent = 'Sorgente DB: configurazione da settings.'; } } }catch(_e){} }catch(_){ /* ignora */ } }
async function saveSettings(){ // normalizza: trim e rimozione trailing slash per tutti i preset
const norm_sr = (_sr||[]).map(it=>({ name: (it.name||'').trim(), url: ((it.url||'').trim()).replace(/\/+$/, ''), }));
const norm_mf = (_mf||[]).map(it=>({ name: (it.name||'').trim(), url: ((it.url||'').trim()).replace(/\/+$/, ''), api_password: it.api_password || '' })); // DB & TMDB extra
// DB profiles payload
const cfg_dburl = (byId('cfg_dburl')?.value || '').trim();
const activeSel = byId('dbp_active');
const active_name = activeSel ? (activeSel.value || _activeDb) : _activeDb;
const cfg_tmdb_key = (byId('cfg_tmdb_key')?.value || '').trim();
const cfg_tmdb_lang = (byId('cfg_tmdb_lang')?.value || '').trim() || 'it-IT';
const ck = (id)=> !!byId(id)?.checked;
const movie_fields = ['name','original_title','overview','poster','backdrop','logo','rating','year','release_date','duration','imdb_id','genres','production_countries','cast','director','writers','tagline','collection','youtube_trailer','production_companies','certification'] .filter(f=> ck('tmf_'+(f==='imdb_id'?'imdb':f)) );
const series_fields = ['name','original_name','overview','poster','backdrop','logo','rating','first_air_date','year','duration','imdb_id','genres','cast','created_by','networks','status','tagline','youtube_trailer','seasons'] .filter(f=> ck('ms_'+(f==='imdb_id'?'imdb':f)) );
const season_fields = ['name','season_number','first_air_date','episode_count','overview','poster','backdrop','tmdb_id'] .filter(f=> ck('tms_'+(f==='tmdb_id'?'tmdb':f)) );
const episode_fields = ['name','overview','air_date','still','duration','rating','guest_stars','crew','imdb_id'] .filter(f=> ck('tme_'+(f=='guest_stars'?'guests':(f=='air_date'?'air_date':(f=='still'?'still':(f=='imdb_id'?'imdb':f))))) );
const payload = { resolvers: norm_sr, mediaflows: norm_mf, database_url: cfg_dburl, db_profiles: _dbps, active_db: active_name, tmdb: { api_key: cfg_tmdb_key, language: cfg_tmdb_lang, movie_fields, series_fields, season_fields, episode_fields } };
const status = byId("saveStatus");
status.textContent = "salvataggio...";
try{ await jpost("/admin/settings.json", payload);
status.textContent = "ok";
setTimeout(()=> status.textContent="", 1500); }catch(e){ console.error(e); status.textContent = "errore"; } }
// DB & TMDB save button
document.addEventListener('DOMContentLoaded', ()=>{ const btn = byId('btnSaveCfg');
if(btn){ btn.onclick = async ()=>{ const st = byId('cfgStatus'); if(st) st.textContent = 'salvataggio...'; try{ await saveSettings(); if(st) st.textContent = 'ok'; setTimeout(()=>{ if(st) st.textContent=''; }, 1200);} catch(e){ if(st) st.textContent='errore'; } }; }
// TMDB scan controls (support All/Movie/Series + Full/Missing)
const btnAllFull = byId('btnTmdbAllFull');
const btnAllMissing = byId('btnTmdbAllMissing');
const btnInc = byId('btnTmdbIncremental');
const btnMovieFull = byId('btnTmdbMovieFull');
const btnMovieMissing = byId('btnTmdbMovieMissing');
const btnSeriesFull = byId('btnTmdbSeriesFull');
const btnSeriesMissing = byId('btnTmdbSeriesMissing');
const stop = byId('btnTmdbStop');
const clearBtn = byId('btnTmdbClear');
const clearSel = byId('tmdbClearScope');
const cleanupBtn = byId('btnTmdbCleanup');
const pBar = byId('tmdbProgressBar');
const pNum = byId('tmdbStatusNum');
function setScanButtonsDisabled(on){
  [btnAllFull, btnAllMissing, btnMovieFull, btnMovieMissing, btnSeriesFull, btnSeriesMissing].forEach(b=>{ if(b) b.disabled = !!on; });
}
async function poll(){ try{ const { job } = await jget('/admin/tmdb/status');
if(!job) return;
const total = Number(job.total||0);
const done = Number(job.done||0);
const running = !!job.running;
const pct = (total>0 ? Math.round((done/total)*100) : 0);
if(pBar){ pBar.style.width = (running? pct: 0) + '%'; }
if(pNum){
  const base = running ? `${done}/${total} (${pct}%) – ${job.mode||''}` : (job.error? ('Esito: '+job.error) : '');
  const diag = (job && running && (job.regex_hits!=null)) ? ` • src regex:${job.regex_hits}|map:${job.map_hits}|search:${job.search_hits} • upd:${job.updated}, skip:${job.skipped}` : '';
  pNum.textContent = base + diag;
}
setScanButtonsDisabled(running);
if(stop) stop.style.visibility = running ? 'visible' : 'hidden';
// Non disabilitare il bottone Clear: consenti sempre la richiesta al backend,
// che risponderà 409 se è in corso uno scan
if(clearBtn) clearBtn.disabled = false;
if(clearSel) clearSel.disabled = false;
if(running){ setTimeout(poll, 1200); } }catch(e){ /* ignore */ } }
async function startScan(missing_only, media_type){
  if(pBar) pBar.style.width='0%';
  if(pNum) pNum.textContent='avvio...';
  await jpost('/admin/tmdb/refresh', { missing_only, media_type });
  poll();
}
if(btnAllFull){ btnAllFull.onclick = ()=> startScan(false, 'all'); }
if(btnAllMissing){ btnAllMissing.onclick = ()=> startScan(true, 'all'); }
if(btnInc){ btnInc.onclick = async ()=>{ if(pBar){ pBar.style.width='0%'; } if(pNum){ pNum.textContent='avvio...'; } await jpost('/admin/tmdb/refresh', { mode: 'incremental' }); poll(); }; }
if(btnMovieFull){ btnMovieFull.onclick = ()=> startScan(false, 'movie'); }
if(btnMovieMissing){ btnMovieMissing.onclick = ()=> startScan(true, 'movie'); }
if(btnSeriesFull){ btnSeriesFull.onclick = ()=> startScan(false, 'series'); }
if(btnSeriesMissing){ btnSeriesMissing.onclick = ()=> startScan(true, 'series'); }
if(stop){ stop.style.visibility='hidden'; stop.onclick = async ()=>{ if(pNum) pNum.textContent='stop in corso...'; await jpost('/admin/tmdb/stop', {}); setTimeout(poll, 600); }; }
if(cleanupBtn){ cleanupBtn.onclick = async ()=>{
  try{
    if(pNum) pNum.textContent='pulizia orfani in corso...';
    const res = await jpost('/admin/tmdb/cleanup_orphans', {});
    const msg = `Pulizia completata. Rimossi: ${res.deleted||0} / Totale: ${res.total||0}. Rimasti: ${res.remaining||0}`;
    alert(msg);
    if(pNum) pNum.textContent = msg;
  }catch(e){ alert('Errore pulizia orfani: ' + e.message); }
}; }
async function triggerTmdbClear(force){
  try{
      const v = (clearSel?.value || 'all');
      let what = null;
      if(v === 'episodes') what = ['episodes'];
      else if(v === 'series') what = ['series'];
      else if(v === 'movies') what = ['movies'];
      else if(v === 'map') what = ['map'];
      else if(v === 'series+episodes') what = ['episodes','series'];
      const msg = what ? ('Confermi la cancellazione: ' + what.join(', ') + '?') : 'Confermi la cancellazione di tutti i dati TMDB? (map, film, serie, episodi, stagioni, collezioni)';
      const confirmed = !!force ? true : confirm(msg);
      if(!confirmed) return;
      if(clearBtn) clearBtn.disabled = true;
      // small visual feedback
      if(pNum) pNum.textContent = 'cancellazione in corso...';
      const res = await jpost('/admin/tmdb/clear', what ? { what } : {});
      const d = (res && res.deleted) || {};
      const rem = (res && res.remaining) || {};
      alert('Cancellazione completata.'+
        '\nEliminati → map='+(d.map||0)+', movies='+(d.movies||0)+', series='+(d.series||0)+', seasons='+(d.seasons||0)+', episodes='+(d.episodes||0)+', collections='+(d.collections||0)+
        '\nRimasti → map='+(rem.map||0)+', movies='+(rem.movies||0)+', series='+(rem.series||0)+', seasons='+(rem.seasons||0)+', episodes='+(rem.episodes||0)+', collections='+(rem.collections||0)
      );
  }catch(e){
      console.error('tmdb clear failed', e);
      alert('Errore nella cancellazione: ' + e.message);
  }finally{
      if(clearBtn) clearBtn.disabled = false;
  }
}
// Espone globalmente: l'HTML usa onclick="window.__tmdbClear()"
window.__tmdbClear = () => triggerTmdbClear(false);
// Evita doppio binding: non assegnare anche clearBtn.onclick perché l'attributo inline già richiama la funzione
// Usa una delega solo come fallback se il bottone non è presente (es. markup custom)
if(!clearBtn){
  document.addEventListener('click', (e)=>{
    const t = e.target && (e.target.id === 'btnTmdbClear' ? e.target : (e.target.closest && e.target.closest('#btnTmdbClear')));
    if(t){ e.preventDefault(); triggerTmdbClear(); }
  });
}
// Load existing TMDB regex rules and wire Add button
initTmdbRulesUI();
// initial poll to reflect running job
poll();
// Preset TMDB (NFO/Xtream)
const S = (id,v)=>{ const el=byId(id); if(el) el.checked = !!v; };
function tmdb_preset_clear(){ const ids = [ 'tmf_name','tmf_original_title','tmf_overview','tmf_poster','tmf_backdrop','tmf_logo','tmf_rating','tmf_year','tmf_release_date','tmf_duration','tmf_imdb','tmf_genres','tmf_production_countries','tmf_cast','tmf_director','tmf_writers','tmf_tagline','tmf_collection','tmf_youtube_trailer','tmf_production_companies','tmf_certification', 'ms_name','ms_original_name','ms_overview','ms_poster','ms_backdrop','ms_logo','ms_rating','ms_first_air_date','ms_year','ms_duration','ms_imdb','ms_genres','ms_cast','ms_created_by','ms_networks','ms_status','ms_tagline','ms_youtube_trailer','ms_seasons', 'tms_name','tms_season_number','tms_first_air_date','tms_episode_count','tms_overview','tms_poster','tms_backdrop','tms_tmdb', 'tme_name','tme_overview','tme_air_date','tme_still','tme_duration','tme_rating','tme_guests','tme_crew','tme_imdb' ];
ids.forEach(id=> S(id,false)); }
function tmdb_preset_nfo_full(){ tmdb_preset_clear(); // Film
['tmf_name','tmf_original_title','tmf_overview','tmf_poster','tmf_backdrop','tmf_logo','tmf_rating','tmf_year','tmf_release_date','tmf_duration','tmf_imdb','tmf_genres','tmf_production_countries','tmf_cast','tmf_director','tmf_writers','tmf_tagline','tmf_collection','tmf_youtube_trailer','tmf_production_companies','tmf_certification'].forEach(id=> S(id,true)); // Serie
['ms_name','ms_original_name','ms_overview','ms_poster','ms_backdrop','ms_logo','ms_rating','ms_first_air_date','ms_year','ms_duration','ms_imdb','ms_genres','ms_cast','ms_created_by','ms_networks','ms_status','ms_tagline','ms_youtube_trailer','ms_seasons'].forEach(id=> S(id,true)); // Stagione
['tms_name','tms_season_number','tms_first_air_date','tms_episode_count','tms_overview','tms_poster','tms_backdrop','tms_tmdb'].forEach(id=> S(id,true)); // Episodio
['tme_name','tme_overview','tme_air_date','tme_still','tme_duration','tme_rating','tme_guests','tme_crew','tme_imdb'].forEach(id=> S(id,true)); }
function tmdb_preset_nfo_min(){ tmdb_preset_clear();
['tmf_name','tmf_original_title','tmf_overview','tmf_poster','tmf_year','tmf_release_date','tmf_duration','tmf_rating','tmf_imdb','tmf_genres','tmf_director','tmf_cast','tmf_production_companies'].forEach(id=> S(id,true));
['ms_name','ms_original_name','ms_overview','ms_poster','ms_rating','ms_first_air_date','ms_year','ms_duration','ms_imdb','ms_genres','ms_created_by','ms_networks'].forEach(id=> S(id,true));
['tms_name','tms_overview','tms_poster','tms_first_air_date','tms_episode_count'].forEach(id=> S(id,true));
['tme_name','tme_overview','tme_air_date','tme_still','tme_duration','tme_rating','tme_crew'].forEach(id=> S(id,true)); }
function tmdb_preset_xt_full(){ tmdb_preset_clear();
['tmf_overview','tmf_poster','tmf_backdrop','tmf_rating','tmf_year','tmf_duration','tmf_imdb','tmf_genres','tmf_cast','tmf_director','tmf_youtube_trailer'].forEach(id=> S(id,true));
['ms_overview','ms_poster','ms_backdrop','ms_rating','ms_year','ms_duration','ms_imdb','ms_genres','ms_cast','ms_seasons'].forEach(id=> S(id,true));
['tms_overview','tms_poster','tms_backdrop'].forEach(id=> S(id,true));
['tme_name','tme_overview','tme_air_date','tme_still','tme_duration','tme_guests'].forEach(id=> S(id,true)); }
function tmdb_preset_xt_min(){ tmdb_preset_clear();
['tmf_poster','tmf_backdrop','tmf_rating','tmf_year'].forEach(id=> S(id,true));
['ms_poster','ms_backdrop','ms_rating','ms_year'].forEach(id=> S(id,true));
['tms_poster','tms_backdrop'].forEach(id=> S(id,true));
['tme_name','tme_duration','tme_still'].forEach(id=> S(id,true)); }
byId('tmdb_preset_nfo_full')?.addEventListener('click', tmdb_preset_nfo_full);
byId('tmdb_preset_nfo_min')?.addEventListener('click', tmdb_preset_nfo_min);
byId('tmdb_preset_xt_full')?.addEventListener('click', tmdb_preset_xt_full);
byId('tmdb_preset_xt_min')?.addEventListener('click', tmdb_preset_xt_min);
byId('tmdb_preset_clear')?.addEventListener('click', tmdb_preset_clear); }); // Settings presets state
// ---------------- DB Browser ----------------
let _db_tables_loaded = false;
async function loadDbTables(){
  const box = byId('db-tables');
  if(!box) return;
  box.textContent = 'carico...';
  try{
    const res = await jget('/admin/db/tables');
    box.textContent = '';
    if(!res || res.ok === false){ box.textContent = 'Errore nel caricare le tabelle'; return; }
    const tables = res.tables || [];
    if(!tables.length){ box.textContent = 'Nessuna tabella'; return; }
    for(const name of tables){
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = name;
      a.style.display = 'inline-block';
      a.style.marginRight = '12px';
      a.onclick = (e)=>{ e.preventDefault(); loadDbTableContent(name, 1); };
      box.appendChild(a);
    }
    _db_tables_loaded = true;
  }catch(e){ box.textContent = 'Errore nel caricare le tabelle'; }
}

async function loadDbTableContent(name, page){
  const title = byId('db-table-name');
  const cont = byId('db-table-content');
  const pag = byId('db-pagination');
  if(title) title.textContent = name || '';
  if(cont) cont.textContent = 'carico...';
  if(pag) pag.textContent = '';
  try{
    const res = await jget(`/admin/db/tables/${encodeURIComponent(name)}?page=${page||1}&page_size=20`);
    if(!res || res.ok === false){ if(cont) cont.textContent = 'Errore nel caricare la tabella'; return; }
    const rows = res.rows || [];
    // Render as a simple table
    if(cont){
      cont.textContent = '';
      if(rows.length === 0){ cont.textContent = 'Nessun record'; }
      else{
        const table = document.createElement('table');
        table.className = 'grid-table';
        const thead = document.createElement('thead');
        const thtr = document.createElement('tr');
        const cols = Object.keys(rows[0]);
        for(const c of cols){ const th=document.createElement('th'); th.textContent=c; thtr.appendChild(th); }
        thead.appendChild(thtr);
        table.appendChild(thead);
        const tbody = document.createElement('tbody');
        for(const r of rows){ const tr=document.createElement('tr'); for(const c of cols){ const td=document.createElement('td'); let v=r[c]; if(v==null) v=''; if(typeof v==='object') v=JSON.stringify(v); td.textContent=String(v); tr.appendChild(td);} tbody.appendChild(tr);} 
        table.appendChild(tbody);
        cont.appendChild(table);
      }
    }
    // Pagination
    if(pag){
      const p = res.pagination || {}; const cur=p.page||1; const totalPages=p.total_pages||1;
      const mkBtn = (t, to)=>{ const b=document.createElement('button'); b.textContent=t; b.disabled = (to<1 || to>totalPages || to===cur); b.onclick=()=> loadDbTableContent(name, to); return b; };
      pag.textContent = '';
      pag.appendChild(mkBtn('«', 1));
      pag.appendChild(mkBtn('‹', cur-1));
      const span = document.createElement('span'); span.className='muted'; span.style.margin='0 8px'; span.textContent = `Pagina ${cur}/${totalPages}`; pag.appendChild(span);
      pag.appendChild(mkBtn('›', cur+1));
      pag.appendChild(mkBtn('»', totalPages));
    }
  }catch(e){ if(cont) cont.textContent = 'Errore nel caricare la tabella'; }
}

// --- TMDB Regex Rules UI ---
async function loadTmdbRules(){
  const list = byId('tmdb_rules_list');
  if(!list) return;
  list.textContent = 'carico...';
  try{
    const items = await jget('/admin/tmdb/rules');
    list.textContent = '';
    if(!items || items.length===0){
      const p = document.createElement('p');
      p.className = 'muted';
      p.textContent = 'Nessuna regola definita';
      list.appendChild(p);
      return;
    }
    for(const r of items){
      const row = document.createElement('div');
      row.className = 'row';
      const main = document.createElement('div');
      main.className = 'row-main';
      const title = document.createElement('div');
      const b = document.createElement('b');
      b.textContent = `${r.name || 'Rule'} [${r.media_type}]`;
      title.appendChild(b);
      main.appendChild(title);
      const info = document.createElement('div');
      info.className = 'muted';
      info.textContent = `prio=${r.priority} • dominio=/${r.domain_regex}/ • estrazione=/${r.extraction_regex}/`;
      main.appendChild(info);
      const ops = document.createElement('div');
      ops.className = 'row-ops';
      const del = document.createElement('button');
      del.className = 'small danger';
      del.textContent = 'Elimina';
      del.onclick = async ()=>{ if(!confirm('Eliminare questa regola?')) return; await jdel(`/admin/tmdb/rules/${r.id}`); await loadTmdbRules(); };
      ops.appendChild(del);
      row.appendChild(main);
      row.appendChild(ops);
      list.appendChild(row);
    }
  }catch(e){
    list.textContent = 'Errore nel caricare le regole';
  }
}

function clearTmdbRuleForm(){
  const def = (id,v)=>{ const el=byId(id); if(el) el.value = v; };
  def('tmdb_rule_name','');
  def('tmdb_rule_priority','100');
  def('tmdb_rule_domain','');
  def('tmdb_rule_extraction','');
  def('tmdb_rule_media_type','movie');
}

function initTmdbRulesUI(){
  const addBtn = byId('btnAddTmdbRule');
  if(addBtn){
    addBtn.onclick = async ()=>{
      const name = (byId('tmdb_rule_name')?.value || '').trim() || 'Rule';
      const prio = parseInt(byId('tmdb_rule_priority')?.value || '100', 10) || 100;
      const domain_regex = (byId('tmdb_rule_domain')?.value || '').trim();
      const extraction_regex = (byId('tmdb_rule_extraction')?.value || '').trim();
      const media_type = (byId('tmdb_rule_media_type')?.value || 'movie');
      if(!domain_regex){ alert('Inserisci la Regex Dominio'); return; }
      if(!extraction_regex){ alert('Inserisci la Regex Estrazione'); return; }
      // Soft validation: encourage one capture group
      if(!/[()]/.test(extraction_regex)){
        if(!confirm('La regex di estrazione dovrebbe avere un gruppo di cattura ( ... ). Continuare?')) return;
      }
      try{
        await jpost('/admin/tmdb/rules', { name, priority: prio, domain_regex, extraction_regex, media_type });
        clearTmdbRuleForm();
        await loadTmdbRules();
      }catch(e){ alert('Errore salvataggio regola: ' + e.message); }
    };
  }
  // Create a lightweight tester UI if not present
  const list = byId('tmdb_rules_list');
  if(list && !byId('tmdb_rule_test_wrap')){
    const wrap = document.createElement('div');
    wrap.id = 'tmdb_rule_test_wrap';
    wrap.style.cssText = 'margin-top:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;';
    const lbl = document.createElement('label');
    lbl.textContent = 'Prova URL:';
    const inp = document.createElement('input');
    inp.id = 'tmdb_rule_test_url';
    inp.placeholder = 'Incolla un URL da testare';
    inp.style.minWidth = '360px';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Prova estrazione';
    const out = document.createElement('span');
    out.id = 'tmdb_rule_test_out';
    out.className = 'muted';
    out.style.minHeight = '20px';
    out.style.marginLeft = '8px';
    wrap.append(lbl, inp, btn, out);
    list.parentNode.insertBefore(wrap, list);
    btn.onclick = async ()=>{
      const url = (inp.value||'').trim();
      if(!url){ out.textContent = 'Inserisci un URL'; return; }
      out.textContent = 'test...';
      try{
        const res = await jpost('/admin/tmdb/rules/test', { url });
        if(res && res.matched){
          out.textContent = `Match: tmdb_id=${res.tmdb_id} • tipo=${res.media_type} • regola=${res.rule?.name||res.rule?.id||''}`;
        }else{
          out.textContent = 'Nessuna corrispondenza';
        }
      }catch(e){
        out.textContent = 'Errore test: ' + e.message;
      }
    };
  }
  loadTmdbRules();
}
let _sr = [];
let _mf = [];
let _dbps = [];
let _activeDb = 'default';
function buildResolverOptionsHtml(selectedUrl){ const opts = [];
const sel = (v)=> (v && selectedUrl && v===selectedUrl) ? ' selected' : '';
if(!selectedUrl){ opts.push('<option value="">Seleziona…</option>'); }
let hasSelected = false;
for(const it of _sr){ const url = (it.url||'').trim();
const name = (it.name||url||'endpoint');
const s = sel(url);
if(s) hasSelected = true;
opts.push(`<option value="${url.replace(/"/g, '&quot;')}"${s}>${name}</option>`); }
if(selectedUrl && !hasSelected){ const safe = selectedUrl.replace(/"/g, '&quot;');
opts.push(`<option value="${safe}" selected>(personalizzato) ${safe}</option>`); }
return opts.join(''); }
function populateResolverDropdowns(){ const convSel = byId('conv_resolver');
const plSel = byId('pl_resolver');
if(convSel){ convSel.innerHTML = buildResolverOptionsHtml(''); }
if(plSel){ plSel.innerHTML = buildResolverOptionsHtml(''); } }
function buildMFOptionsHtml(selectedName){ const opts = [];
const sel = (n)=> (n && selectedName && n===selectedName) ? ' selected' : '';
if(!selectedName){ opts.push('<option value="">Seleziona…</option>'); }
let hasSelected = false;
for(const it of _mf){ const name = (it.name||'').trim() || '(senza nome)';
const s = sel(name);
if(s) hasSelected = true;
opts.push(`<option value="${name.replace(/"/g, '&quot;')}"${s}>${name}</option>`); }
if(selectedName && !hasSelected){ const safe = selectedName.replace(/"/g, '&quot;');
opts.push(`<option value="${safe}" selected>(personalizzato) ${safe}</option>`); }
return opts.join(''); }
function populateMFDropdown(selectedName){ const sel = byId('mf_preset');
if(sel){ sel.innerHTML = buildMFOptionsHtml(selectedName||''); } }
function buildResolverOptionsHtmlWithDefault(selectedUrl){ const opts = [];
const base = canonicalServerBase();
const safeBase = base.replace(/"/g, '&quot;');
opts.push(`<option value="">Predefinito: ${safeBase}</option>`);
for(const it of _sr){ const url = (it.url||'').trim();
const name = (it.name||url||'endpoint');
const selected = selectedUrl && selectedUrl === url ? ' selected' : '';
opts.push(`<option value="${url.replace(/"/g, '&quot;')}"${selected}>${name}</option>`); }
return opts.join(''); }
function renderSRList(){ const box = byId('sr_list');
if(!box) return;
if(!_sr.length){ box.textContent='Nessun endpoint configurato'; return; }
box.textContent='';
_sr.forEach((it,idx)=>{ const row=document.createElement('div');
row.className='row';
const main=document.createElement('div');
main.className='row-main';
row.appendChild(main); // Name line with pencil
const nameLine = document.createElement('div');
nameLine.className='line';
const nameVal = document.createElement('b');
nameVal.textContent = it.name || `endpoint ${idx+1}`;
nameLine.appendChild(nameVal);
const nameEdit = document.createElement('button');
nameEdit.className='icon';
nameEdit.title='Modifica nome';
nameEdit.setAttribute('aria-label','Modifica nome');
nameEdit.textContent='✎';
nameEdit.onclick = ()=>{ startInlineEdit(nameLine, { value: it.name || `endpoint ${idx+1}`, validator: (v)=>{ if(!v){ alert('Il nome non può essere vuoto'); return false; } return true; }, onSave: async (v)=>{ _sr[idx] = { ...it, name: v }; renderSRList(); await saveSettings(); } }); };
nameLine.appendChild(nameEdit);
main.appendChild(nameLine); // URL line with pencil
const urlLine = document.createElement('div');
urlLine.className='line muted';
const urlVal = document.createElement('span');
urlVal.textContent = it.url || '';
urlLine.appendChild(urlVal);
const urlEdit = document.createElement('button');
urlEdit.className='icon';
urlEdit.title='Modifica URL';
urlEdit.setAttribute('aria-label','Modifica URL');
urlEdit.textContent='✎';
urlEdit.onclick = ()=>{ startInlineEdit(urlLine, { value: it.url || '', placeholder: 'host:porta oppure https://... ', validator: (v)=>{ if(!v){ alert('Compila URL'); return false; } if(!isValidHostPortOrHttp(v)) { alert('URL non valido. Inserisci "host:porta" oppure un URL http(s) valido.'); return false; } return true; }, normalizer: (v)=>{ let norm = v.trim(); if(!/^https?:\/\//i.test(norm)) norm = 'http://' + norm; return norm.replace(/\/+$/, ''); }, onSave: async (v)=>{ _sr[idx] = { ...it, url: v }; renderSRList(); await saveSettings(); } }); };
urlLine.appendChild(urlEdit);
main.appendChild(urlLine);
const ops=document.createElement('div');
ops.className='row-ops';
row.appendChild(ops);
const del=document.createElement('button');
del.className='small danger';
del.textContent='Rimuovi';
del.onclick=async()=>{ _sr.splice(idx,1); renderSRList(); await saveSettings(); };
ops.append(del);
box.appendChild(row); });
populateResolverDropdowns();
populateMFDropdown(); }
function renderMFList(){ const box = byId('mf_list');
if(!box) return;
if(!_mf.length){ box.textContent='Nessun MediaFlow configurato'; return; }
box.textContent='';
_mf.forEach((it,idx)=>{ const row=document.createElement('div');
row.className='row';
const main=document.createElement('div');
main.className='row-main';
row.appendChild(main); // Name
const nameLine=document.createElement('div');
nameLine.className='line';
const b=document.createElement('b');
b.textContent=it.name||`mediaflow ${idx+1}`;
nameLine.appendChild(b);
const nameEdit=document.createElement('button');
nameEdit.className='icon';
nameEdit.title='Modifica nome';
nameEdit.setAttribute('aria-label','Modifica nome');
nameEdit.textContent='✎';
nameEdit.onclick=()=>{ startInlineEdit(nameLine, { value: it.name || `mediaflow ${idx+1}`, validator: (v)=>{ if(!v){ alert('Il nome non può essere vuoto'); return false; } return true; }, onSave: async (v)=>{ _mf[idx] = { ...it, name: v }; renderMFList(); await saveSettings(); } }); };
nameLine.appendChild(nameEdit);
main.appendChild(nameLine); // URL
const urlLine=document.createElement('div');
urlLine.className='line muted';
const urlSpan=document.createElement('span');
urlSpan.textContent=it.url||'';
urlLine.appendChild(urlSpan);
const urlEdit=document.createElement('button');
urlEdit.className='icon';
urlEdit.title='Modifica URL';
urlEdit.setAttribute('aria-label','Modifica URL');
urlEdit.textContent='✎';
urlEdit.onclick=()=>{ startInlineEdit(urlLine, { value: it.url || '', placeholder: 'https://... ', validator: (v)=>{ if(!v){ alert('Compila URL'); return false; } if(!isValidAbsoluteHttpUrl(v)){ alert('URL non valido. Inserisci un URL http(s) valido, es. https://host[:porta]'); return false; } return true; }, normalizer: (v)=> v.trim().replace(/\/+$/, ''), onSave: async (v)=>{ _mf[idx] = { ...it, url: v }; renderMFList(); await saveSettings(); } }); };
urlLine.appendChild(urlEdit);
main.appendChild(urlLine); // Password
const pwdLine=document.createElement('div');
pwdLine.className='line muted';
const pwdSpan=document.createElement('span');
pwdSpan.textContent = it.api_password ? '********' : '(password non impostata)';
pwdLine.appendChild(pwdSpan);
const pwdEdit=document.createElement('button');
pwdEdit.className='icon';
pwdEdit.title='Modifica password';
pwdEdit.setAttribute('aria-label','Modifica password');
pwdEdit.textContent='✎';
pwdEdit.onclick=()=>{ startInlineEdit(pwdLine, { value: it.api_password || '', type: 'password', placeholder: 'api_password', validator: (v)=>{ /* può essere vuota */ return true; }, onSave: async (v)=>{ _mf[idx] = { ...it, api_password: v }; renderMFList(); await saveSettings(); } }); };
pwdLine.appendChild(pwdEdit);
main.appendChild(pwdLine);
const ops=document.createElement('div');
ops.className='row-ops';
row.appendChild(ops);
const del=document.createElement('button');
del.className='small danger';
del.textContent='Rimuovi';
del.onclick=async()=>{ _mf.splice(idx,1); renderMFList(); await saveSettings(); };
ops.append(del);
box.appendChild(row); });
populateMFDropdown(); }
byId('btnAddSR')?.addEventListener('click', async ()=>{ const name=byId('sr_name').value.trim();
const url=byId('sr_url').value.trim();
if(!name||!url){ alert('Compila nome e URL'); return; }
if(!isValidHostPortOrHttp(url)){ alert('URL non valido. Inserisci "host:porta" oppure un URL http(s) valido.'); return; } // normalizza come fa il backend (ensure_http + rimozione trailing slash)
let norm = url.trim();
if(!/^https?:\/\//i.test(norm)) norm = 'http://' + norm;
norm = norm.replace(/\/+$/, '');
_sr.push({ name, url: norm });
byId('sr_name').value='';
byId('sr_url').value='';
renderSRList();
await saveSettings(); });
byId('btnAddMF')?.addEventListener('click', async ()=>{ const name=byId('mf_name').value.trim();
const url=byId('mf_url').value.trim();
const api_password=byId('mf_pwd').value;
if(!name||!url){ alert('Compila nome e URL'); return; }
if(!isValidAbsoluteHttpUrl(url)){ alert('URL non valido. Inserisci un URL http(s) valido, es. https://host[:porta]'); return; } // normalizza come fa il backend (rimozione trailing slash)
let norm = url.trim().replace(/\/+$/, '');
_mf.push({ name, url: norm, api_password });
byId('mf_name').value='';
byId('mf_url').value='';
byId('mf_pwd').value='';
renderMFList();
await saveSettings(); });
// ---------------- Converti una-tantum ----------------
async function convertOnce(){ const url = byId("conv_url").value.trim();
const mode = byId("conv_mode").value;
const resolver_url = (byId('conv_resolver')?.value || '').trim();
if(!isValidAbsoluteHttpUrl(url)){ alert("Inserisci un URL playlist valido (http/https)"); return; }
if(_sr.length>0 && !resolver_url){ alert('Seleziona un Endpoint resolver'); return; }
let r = await fetch("/admin/convert", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ url, mode, resolver_url }) });
if(!r.ok){ const t = await r.text(); alert("Errore: " + t); return; }
const blob = await r.blob();
const a = document.createElement("a");
a.href = URL.createObjectURL(blob);
a.download = "playlist_convertita.m3u";
document.body.appendChild(a);
a.click();
a.remove(); }
// ---------------- Liste salvate ----------------
async function loadLists(){ const box = byId("lists");
box.textContent = "carico...";
try{ const { items } = await jget("/admin/playlists.json");
_lists = items || [];
if(!items || !items.length){ box.textContent = "";
const p = document.createElement("p");
p.className = "muted";
p.textContent = "Nessuna lista salvata";
box.appendChild(p);
await populateXtreamSelects();
return; }
box.textContent = "";
// Hint for reorder capability
const _hint = document.createElement('p');
_hint.className = 'muted';
_hint.textContent = 'Suggerimento: trascina le righe o usa ↑/↓ per riordinare.';
box.appendChild(_hint);
for(const it of items){ const row = document.createElement("div");
row.className = "row";
row.dataset.id = it.id;
row.draggable = true;
row.addEventListener('dragstart', onPlDragStart);
row.addEventListener('dragenter', onPlDragEnter);
row.addEventListener('dragleave', onPlDragLeave);
row.addEventListener('dragover', onPlDragOver);
row.addEventListener('drop', onPlDrop);
const rowMain = document.createElement("div");
rowMain.className = "row-main";
row.appendChild(rowMain); // Helpers
const path = `/lists/${it.id}.m3u`;
const base = (it.resolver_url && it.resolver_url.trim()) ? it.resolver_url.trim().replace(/\/+$/, '') : canonicalServerBase();
const fullLink = base.replace(/\/$/, '') + path; // 1) Titolo: Nome lista [✎] – Ultimo refresh
const titleLine = document.createElement('div');
titleLine.className = 'line';
// Drag handle indicator
const dragHandle = document.createElement('span');
dragHandle.textContent = '☰';
dragHandle.title = 'Trascina per riordinare';
dragHandle.style.cursor = 'grab';
dragHandle.style.marginRight = '8px';
titleLine.appendChild(dragHandle);
const nameB = document.createElement('b');
nameB.textContent = `${(it.order_num||0) > 0 ? ('#'+it.order_num+' ') : ''}${it.name}`;
titleLine.appendChild(nameB);
const nameEdit = document.createElement('button');
nameEdit.className='icon';
nameEdit.title='Modifica nome';
nameEdit.textContent='✎';
nameEdit.onclick = ()=>{ startInlineEdit(titleLine, { value: it.name || '', validator: (v)=>{ if(!v){ alert('Il nome non può essere vuoto'); return false; } return true; }, onSave: async (v)=>{ await jpost(`/admin/playlists/${it.id}/update`, { name: v }); await loadLists(); } }); };
titleLine.appendChild(nameEdit);
const lastSpan = document.createElement('span');
lastSpan.className='muted';
lastSpan.textContent = ` – Ultimo refresh: ${it.last_refresh ? new Date(it.last_refresh*1000).toLocaleString() : 'mai'}`;
titleLine.appendChild(lastSpan);
rowMain.appendChild(titleLine); // 2) (rimosso link di esposizione: import only)
// 3) Tipo di lista: [✎] • Aggiorna ogni N ore
const typeLine = document.createElement('div');
typeLine.className='line';
const tLabel = document.createElement('span');
tLabel.textContent='Tipo di lista: ';
typeLine.appendChild(tLabel);
const cmode = (it.mode||'').toLowerCase();
const modeLabel = cmode==='live' || cmode==='tv' ? 'Live' : (cmode==='film' || cmode==='video' ? 'Film' : (cmode==='series' ? 'Serie' : 'Misto'));
const modeB = document.createElement('b');
modeB.textContent = modeLabel;
typeLine.appendChild(modeB);
const modeEdit = document.createElement('button');
modeEdit.className='icon';
modeEdit.title='Modifica tipo';
modeEdit.textContent='✎';
modeEdit.onclick = ()=>{ const current = (it.mode||'').toLowerCase();
const sel = (v)=> (current===v ? ' selected' : '');
const opts = `<option value="live"${sel('live')}>Live</option><option value="film"${sel('film')}>Film</option><option value="series"${sel('series')}>Serie</option><option value="mixed"${sel('mixed')}>Misto</option>`;
startInlineEdit(typeLine, { kind: 'select', value: current, optionsHtml: opts, onSave: async (v)=>{ await jpost(`/admin/playlists/${it.id}/update`, { mode: v }); await loadLists(); } }); };
typeLine.appendChild(modeEdit);
const sep = document.createElement('span');
sep.textContent = ' \u00A0•\u00A0 Aggiorna ogni ';
typeLine.appendChild(sep);
const hrsInput = document.createElement('input');
hrsInput.className='hrs';
hrsInput.type='number';
hrsInput.min='1';
hrsInput.value = it.every_hours;
typeLine.appendChild(hrsInput);
const oreLbl = document.createElement('span');
oreLbl.textContent = ' ore';
typeLine.appendChild(oreLbl);
rowMain.appendChild(typeLine); // 4) Link origine: [✎]
const srcLine = document.createElement('div');
srcLine.className = 'line';
const sLabel = document.createElement('span');
sLabel.textContent='Link origine: ';
srcLine.appendChild(sLabel);
const srcSpan = document.createElement('span');
srcSpan.className='muted break';
srcSpan.textContent = it.url;
srcLine.appendChild(srcSpan);
const srcEdit = document.createElement('button');
srcEdit.className='icon';
srcEdit.title='Modifica URL originale';
srcEdit.textContent='✎';
srcEdit.onclick = ()=>{ startInlineEdit(srcLine, { value: it.url || '', placeholder: 'https://...' ,validator: (v)=>{ if(!v){ alert('URL obbligatorio'); return false; } if(!isValidAbsoluteHttpUrl(v)){ alert('Inserisci un URL playlist valido (http/https)'); return false; } return true; }, onSave: async (v)=>{ await jpost(`/admin/playlists/${it.id}/update`, { url: v }); await loadLists(); } }); };
srcLine.appendChild(srcEdit);
rowMain.appendChild(srcLine);
const opsDiv = document.createElement("div");
opsDiv.className = "row-ops";
const btn = (txt, act, extra)=>{ const b = document.createElement("button"); b.className = "small" + (extra ? " " + extra : ""); b.textContent = txt; b.dataset.act = act; return b; };
const refreshBtn = btn("Importa/Refresh", "refresh");
const upBtn = btn("↑", "up");
const downBtn = btn("↓", "down");
const delBtn = btn("Elimina", "del", "danger");
opsDiv.append(refreshBtn, upBtn, downBtn, delBtn);
row.appendChild(opsDiv);
refreshBtn.onclick = async ()=>{ const hrs = parseInt(hrsInput.value,10)||12; await jpost(`/admin/playlists/${it.id}/update`, { every_hours: hrs, refresh: true }); await loadLists(); await populateXtreamSelects(); };
delBtn.onclick = async ()=>{ if(!confirm("Eliminare questa lista?")) return; await jdel(`/admin/playlists/${it.id}`); await loadLists(); await populateXtreamSelects(); }; // (rimosso copia link)
upBtn.onclick = async ()=>{ movePlaylist(it.id, -1); };
downBtn.onclick = async ()=>{ movePlaylist(it.id, +1); };
box.appendChild(row); }
await populateXtreamSelects(); }catch(e){ console.error(e); box.textContent = "";
const p = document.createElement("p");
p.className = "muted";
p.textContent = "Errore nel caricare le liste";
box.appendChild(p); } }

// --- Drag&Drop reorder playlists ---
let _dragPlId = null;
function _plContainer(){ return byId('lists'); }
function onPlDragStart(e){ _dragPlId = e.currentTarget?.dataset?.id || null; }
function onPlDragEnter(e){ e.currentTarget.classList.add('drag-over'); }
function onPlDragLeave(e){ e.currentTarget.classList.remove('drag-over'); }
function onPlDragOver(e){ e.preventDefault(); const target = e.currentTarget; const container = _plContainer();
  if(!_dragPlId || !container || !target) return;
  const dragEl = [...container.children].find(n=>n.dataset && n.dataset.id===_dragPlId);
  if(!dragEl || dragEl===target) return;
  const rect = target.getBoundingClientRect();
  const before = (e.clientY - rect.top) < (rect.height/2);
  if(before){ container.insertBefore(dragEl, target); } else { container.insertBefore(dragEl, target.nextSibling); }
}
async function onPlDrop(e){ e.preventDefault(); e.currentTarget.classList.remove('drag-over'); const container = _plContainer(); if(!container) return; await _persistPlaylistOrder(container); }
async function _persistPlaylistOrder(container){ const order = [...container.children].map(n=>n.dataset && n.dataset.id).filter(Boolean);
  try{ await jpost('/admin/playlists/reorder', { order }); await loadLists(); await populateXtreamSelects(); }catch(e){ console.error('Errore salvataggio ordine:', e); }
}
async function movePlaylist(id, delta){ const container = _plContainer(); if(!container) return; const nodes = [...container.children].filter(n=>n.dataset && n.dataset.id);
  const idx = nodes.findIndex(n=>n.dataset.id===id); if(idx<0) return; const newIdx = Math.max(0, Math.min(nodes.length-1, idx+delta)); if(newIdx===idx) return;
  const node = nodes[idx]; const ref = nodes[newIdx]; if(newIdx>idx){ container.insertBefore(node, ref.nextSibling); } else { container.insertBefore(node, ref); }
  await _persistPlaylistOrder(container);
}
async function addList(){ const name = byId("pl_name").value.trim();
const url = byId("pl_url").value.trim();
const mode = byId("pl_mode").value;
const every_hours = parseInt(byId("pl_every").value,10) || 12;
if(!name || !url){ alert("Compila nome e URL"); return; }
if(!isValidAbsoluteHttpUrl(url)){ alert("Inserisci un URL playlist valido (http/https)"); return; }
try{ await jpost("/admin/playlists", { name, url, mode, every_hours });
byId("pl_name").value = "";
byId("pl_url").value = "";
await loadLists(); }catch(e){ console.error(e); alert("Errore nel creare la lista"); } }
// ---------------- Xtream: helpers UI ----------------
function canonicalServerBase(){ let base = '';
try{ if(Array.isArray(_sr) && _sr.length){ base = (_sr[0].url || '').trim(); } }catch(e){ base = ''; }
if(!base) base = location.origin;
if(!/^https?:\/\//i.test(base)) base = "http://" + base;
return base.replace(/\/$/, ""); }
function optsForSelect(arr){ return arr.map(o=>`<option value="${o.id}">${o.name}</option>`).join(""); }
async function populateXtreamSelects(){ const live = _lists.filter(x=>{ const m=(x.mode||'').toLowerCase(); return m==='live' || m==='tv'; });
const vod = _lists.filter(x=>{ const m=(x.mode||'').toLowerCase(); return m==='film' || m==='video'; });
const series = _lists.filter(x=>{ const m=(x.mode||'').toLowerCase(); return m==='series'; });
const mix = _lists.filter(x=>{ const m=(x.mode||'').toLowerCase(); return m==='mixed'; });
const selLive = byId("xt_live");
const selMovies = byId("xt_movies");
const selSeries = byId("xt_series");
const selMixed = byId("xt_mixed");
if(selLive) selLive.innerHTML = optsForSelect(live);
if(selMovies) selMovies.innerHTML = optsForSelect(vod);
if(selSeries) selSeries.innerHTML = optsForSelect(series);
if(selMixed) selMixed.innerHTML = optsForSelect(mix); }
function valuesFromSelect(sel){ return Array.from(sel.selectedOptions).map(o=>o.value); }
function setSelectValues(sel, values){ const vals = values || [];
for(const o of sel.options){ o.selected = vals.includes(o.value); } }
function enableMultiSelectToggle(sel){ if(!sel) return;
sel.addEventListener('mousedown', (e)=>{ const target = e.target;
if(target && target.tagName && target.tagName.toLowerCase() === 'option'){ e.preventDefault();
const opt = target;
opt.selected = !opt.selected; } }); }
function buildServerUrl(x){ const base = (x && x.resolver_url) ? (x.resolver_url || '').trim().replace(/\/$/, '') : canonicalServerBase();
return base + "/xtream/" + x.id; }
function buildFullM3UUrl(x){ return ( buildServerUrl(x) + "/get.php?username=" + encodeURIComponent(x.username) + "&password=" + encodeURIComponent(x.password) + "&playlist_type=m3u&output=ts" ); }
// ---------------- Xtream: CRUD ----------------
async function saveXtream(){ const name = byId("xt_name").value.trim();
const username = byId("xt_user").value.trim();
const password = byId("xt_pass").value;
const every_hours = parseInt(byId("xt_every").value,10) || 12;
const resolver_url = (byId('xt_resolver')?.value || '').trim();
 const dedupe_policy = (byId('xt_dedupe')?.value || 'm3u_order');
const live_list_ids = valuesFromSelect(byId("xt_live"));
const movie_list_ids = valuesFromSelect(byId("xt_movies"));
const series_list_ids = valuesFromSelect(byId("xt_series"));
const mixed_list_ids = valuesFromSelect(byId("xt_mixed")); // Export fields selections
const ck = (id)=> !!byId(id)?.checked;
const export_live_fields = ['stream_icon','epg_channel_id','category_name','category_id','stream_type','rating','rating_5based','added','tv_archive','tv_archive_duration','direct_source','custom_sid'] .filter(f=> ck('xlf_'+(f==='rating_5based'?'rating5':f)) ); // Film: optional root + info keys (obbligatori sono sempre inclusi)
const export_movie_fields = [ // root extras
'stream_icon','added','category_ids','num', // info extras
'tmdb_id','imdb_id','year','releasedate','movie_image','backdrop_path','plot','duration','duration_secs','genre','rating','director','cast','country','production_countries','youtube_trailer' ].filter(f=> ck('xmf_'+( f )) ); // Serie: optional root + info keys
const export_series_fields = [ // root extras
'cover','cover_big','category_ids','last_modified','num', // info extras
'tmdb_id','imdb_id','releaseDate','backdrop_path','plot','genre','rating','director','cast','origin_country','youtube_trailer','network','status' ].filter(f=> ck('xsf_'+( f )) ); // Stagioni (seasons) – info keys
const export_season_fields = [ 'name','overview','cover','poster_path','air_date','id','backdrop_path','vote_average' ].filter(f=> ck('xss_'+f) ); // Episodi – optional keys
const export_episode_fields = [ 'tmdb_id','imdb_id','releaseDate','backdrop_path','plot','duration','duration_secs','rating','added' ].filter(f=> ck('xef_'+( f )) );
if(!name || !username || !password){ alert("Compila nome, username e password"); return; }
const payload = { name, username, password, every_hours, resolver_url, dedupe_policy, live_list_ids, movie_list_ids, series_list_ids, mixed_list_ids, export_live_fields, export_movie_fields, export_series_fields, export_season_fields, export_episode_fields };
try{ if(_editingXt){ await jpost(`/admin/xtreams/${_editingXt}/update`, payload); }else{ await jpost("/admin/xtreams", payload); }
resetXtreamForm();
await loadXtreams(); }catch(e){ alert("Errore: " + e.message); } }
function resetXtreamForm(){ byId("xt_name").value = "";
byId("xt_user").value = "";
byId("xt_pass").value = "";
byId("xt_every").value = "12";
 if(byId('xt_dedupe')) byId('xt_dedupe').value = 'm3u_order';
setSelectValues(byId("xt_live"), []);
setSelectValues(byId("xt_movies"), []);
setSelectValues(byId("xt_series"), []);
setSelectValues(byId("xt_mixed"), []); // reset export fields
const off = [ // live
'xlf_stream_icon','xlf_epg_channel_id','xlf_category_name','xlf_category_id','xlf_stream_type','xlf_rating','xlf_rating5','xlf_added','xlf_tv_archive','xlf_tv_archive_duration','xlf_direct_source','xlf_custom_sid', // film (root)
'xmf_stream_icon','xmf_added','xmf_category_ids','xmf_num', // film (info)
'xmf_tmdb_id','xmf_imdb_id','xmf_year','xmf_releasedate','xmf_movie_image','xmf_backdrop_path','xmf_plot','xmf_duration','xmf_duration_secs','xmf_genre','xmf_rating','xmf_director','xmf_cast','xmf_country','xmf_production_countries','xmf_youtube_trailer', // serie (root)
'xsf_cover','xsf_cover_big','xsf_category_ids','xsf_last_modified','xsf_num', // serie (info)
'xsf_tmdb_id','xsf_imdb_id','xsf_releaseDate','xsf_backdrop_path','xsf_plot','xsf_genre','xsf_rating','xsf_director','xsf_cast','xsf_origin_country','xsf_youtube_trailer','xsf_network','xsf_status', // stagioni (info)
'xss_name','xss_overview','xss_cover','xss_poster_path','xss_air_date','xss_id','xss_backdrop_path','xss_vote_average', // episodi (root/info)
'xef_tmdb_id','xef_imdb_id','xef_releaseDate','xef_backdrop_path','xef_plot','xef_duration','xef_duration_secs','xef_rating','xef_added' ];
off.forEach(id=>{ const el=byId(id); if(el) el.checked=false; });
_editingXt = null;
const btn = byId("btnSaveXtream");
if(btn) btn.textContent = "Crea Xtream";
const cancelBtn = byId("btnCancelXtream");
if(cancelBtn) cancelBtn.style.display = 'none';
const hint = byId('xt_editing_hint');
if(hint) hint.textContent = '';
const adv = byId('xt_adv');
if(adv) adv.open = false; }
function startEditXtream(x){ _editingXt = x.id;
byId("xt_name").value = x.name || "";
byId("xt_user").value = x.username || "";
byId("xt_pass").value = x.password || "";
byId("xt_every").value = x.every_hours || 12;
populateResolverDropdowns();
if(byId('xt_resolver')){ byId('xt_resolver').innerHTML = buildResolverOptionsHtml(x.resolver_url || ''); }
if(byId('xt_dedupe')){ byId('xt_dedupe').value = (x.dedupe_policy || 'm3u_order'); }
setSelectValues(byId("xt_live"), x.live_list_ids || []);
setSelectValues(byId("xt_movies"), x.movie_list_ids || []);
setSelectValues(byId("xt_series"), x.series_list_ids || []);
setSelectValues(byId("xt_mixed"), x.mixed_list_ids || []); // populate export field checkboxes
const has = (arr, key)=> Array.isArray(arr) && arr.includes(key);
const lf = x.export_live_fields || [];
const mf = x.export_movie_fields || [];
const sf = x.export_series_fields || [];
const ss = x.export_season_fields || [];
const ef = x.export_episode_fields || [];
const setCk = (id, arr, key)=>{ const el = byId(id); if(el) el.checked = has(arr, key); };
setCk('xlf_stream_icon', lf, 'stream_icon');
setCk('xlf_epg_channel_id', lf, 'epg_channel_id');
setCk('xlf_category_name', lf, 'category_name');
setCk('xlf_category_id', lf, 'category_id');
setCk('xlf_stream_type', lf, 'stream_type');
setCk('xlf_rating', lf, 'rating');
setCk('xlf_rating5', lf, 'rating_5based');
setCk('xlf_added', lf, 'added');
setCk('xlf_tv_archive', lf, 'tv_archive');
setCk('xlf_tv_archive_duration', lf, 'tv_archive_duration');
setCk('xlf_direct_source', lf, 'direct_source');
setCk('xlf_custom_sid', lf, 'custom_sid'); // Film
setCk('xmf_stream_icon', mf, 'stream_icon');
setCk('xmf_added', mf, 'added');
setCk('xmf_category_ids', mf, 'category_ids');
setCk('xmf_num', mf, 'num');
setCk('xmf_tmdb_id', mf, 'tmdb_id');
setCk('xmf_imdb_id', mf, 'imdb_id');
setCk('xmf_year', mf, 'year');
setCk('xmf_releasedate', mf, 'releasedate');
setCk('xmf_movie_image', mf, 'movie_image');
setCk('xmf_backdrop_path', mf, 'backdrop_path');
setCk('xmf_plot', mf, 'plot');
setCk('xmf_duration', mf, 'duration');
setCk('xmf_duration_secs', mf, 'duration_secs');
setCk('xmf_genre', mf, 'genre');
setCk('xmf_rating', mf, 'rating');
setCk('xmf_director', mf, 'director');
setCk('xmf_cast', mf, 'cast');
setCk('xmf_country', mf, 'country');
setCk('xmf_production_countries', mf, 'production_countries');
setCk('xmf_youtube_trailer', mf, 'youtube_trailer'); // Serie
setCk('xsf_cover', sf, 'cover');
setCk('xsf_cover_big', sf, 'cover_big');
setCk('xsf_category_ids', sf, 'category_ids');
setCk('xsf_last_modified', sf, 'last_modified');
setCk('xsf_num', sf, 'num');
setCk('xsf_tmdb_id', sf, 'tmdb_id');
setCk('xsf_imdb_id', sf, 'imdb_id');
setCk('xsf_releaseDate', sf, 'releaseDate');
setCk('xsf_backdrop_path', sf, 'backdrop_path');
setCk('xsf_plot', sf, 'plot');
setCk('xsf_genre', sf, 'genre');
setCk('xsf_rating', sf, 'rating');
setCk('xsf_director', sf, 'director');
setCk('xsf_cast', sf, 'cast');
setCk('xsf_origin_country', sf, 'origin_country');
setCk('xsf_youtube_trailer', sf, 'youtube_trailer');
setCk('xsf_network', sf, 'network');
setCk('xsf_status', sf, 'status'); // Stagioni
setCk('xss_name', ss, 'name');
setCk('xss_overview', ss, 'overview');
setCk('xss_cover', ss, 'cover');
setCk('xss_poster_path', ss, 'poster_path');
setCk('xss_air_date', ss, 'air_date');
setCk('xss_id', ss, 'id');
setCk('xss_backdrop_path', ss, 'backdrop_path');
setCk('xss_vote_average', ss, 'vote_average'); // Episodi
setCk('xef_tmdb_id', ef, 'tmdb_id');
setCk('xef_imdb_id', ef, 'imdb_id');
setCk('xef_releaseDate', ef, 'releaseDate');
setCk('xef_backdrop_path', ef, 'backdrop_path');
setCk('xef_plot', ef, 'plot');
setCk('xef_duration', ef, 'duration');
setCk('xef_duration_secs', ef, 'duration_secs');
setCk('xef_rating', ef, 'rating');
setCk('xef_added', ef, 'added');
const btn = byId("btnSaveXtream");
if(btn) btn.textContent = "Salva Modifiche";
const cancelBtn = byId("btnCancelXtream");
if(cancelBtn) cancelBtn.style.display = '';
const hint = byId('xt_editing_hint');
if(hint) hint.textContent = ` – Modifica di "${x.name || ''}"`;
window.scrollTo({ top: 0, behavior: 'smooth' }); // Open advanced section if any export field is selected
try{ const tot = (x.export_live_fields||[]).length+(x.export_movie_fields||[]).length+(x.export_series_fields||[]).length+(x.export_season_fields||[]).length+(x.export_episode_fields||[]).length;
const adv = byId('xt_adv');
if(adv) adv.open = tot>0; }catch(_){ /* ignore */ } }
async function loadXtreams(){ const box = byId("xtreams");
if(!box){ return; }
box.textContent = "carico...";
try{ const { items } = await jget("/admin/xtreams.json");
if(!items || !items.length){ box.textContent = "";
const p = document.createElement("p");
p.className = "muted";
p.textContent = "Nessun xtream salvato";
box.appendChild(p);
return; }
const autoRefreshNote = document.createElement("p");
autoRefreshNote.className = "muted";
autoRefreshNote.style.textAlign = "center";
autoRefreshNote.style.marginBottom = "1em";
autoRefreshNote.innerHTML = "ℹ️ La cache viene rigenerata automaticamente in background quando scade.";
box.appendChild(autoRefreshNote); // costruisce mappa id -> nome per le playlist
const listNameById = {};
for(const l of _lists){ listNameById[l.id] = l.name; }
const names = ids => (ids || []).map(id => listNameById[id] || id).join(", ");
const catNode = (label, ids) => { const div = document.createElement("div");
div.className = "xt-cat";
const b = document.createElement("b");
b.textContent = label + ":";
div.appendChild(b);
div.appendChild(document.createTextNode(" "));
if(ids && ids.length){ div.appendChild(document.createTextNode(names(ids))); }else{ const span = document.createElement("span");
span.className = "muted";
span.textContent = "Nessuna";
div.appendChild(span); }
return div; };
box.textContent = "";
for(const x of items){ const row = document.createElement("div");
row.className = "row";
const serverUrl = buildServerUrl(x);
const fullUrl = buildFullM3UUrl(x);
const rowMain = document.createElement("div");
rowMain.className = "row-main";
row.appendChild(rowMain);
const nameDiv = document.createElement("div");
const nameB = document.createElement("b");
nameB.textContent = x.name;
nameDiv.appendChild(nameB);
rowMain.appendChild(nameDiv);
const serverDiv = document.createElement("div");
serverDiv.append("Server: ");
const code = document.createElement("code");
code.textContent = serverUrl;
serverDiv.appendChild(code);
rowMain.appendChild(serverDiv);
const infoDiv = document.createElement("div");
infoDiv.className = "muted";
infoDiv.append("Utente: ");
const userB = document.createElement("b");
userB.textContent = x.username;
infoDiv.appendChild(userB);
infoDiv.append(" • Password: ");
const passB = document.createElement("b");
passB.textContent = x.password;
infoDiv.appendChild(passB);
infoDiv.append(" • Aggiorna ogni ");
const hrsInput = document.createElement("input");
hrsInput.className = "hrs";
hrsInput.type = "number";
hrsInput.min = "1";
hrsInput.value = x.every_hours;
infoDiv.appendChild(hrsInput);
infoDiv.append(" ore");
rowMain.appendChild(infoDiv);
const lastDiv = document.createElement("div");
lastDiv.className = "muted";
lastDiv.textContent = `Ultimo refresh: ${x.last_refresh ? new Date(x.last_refresh*1000).toLocaleString() : "mai"}`;
rowMain.appendChild(lastDiv);
const statusDiv = document.createElement("div");
const state = (x.cache_status || 'sconosciuto');
statusDiv.className = "xt-status status-" + state.replace(/\s+/g, '-');
const statusLabel = document.createElement("span");
statusLabel.textContent = "Stato cache: ";
const badge = document.createElement("span");
badge.className = "badge " + state.replace(/\s+/g, '-');
badge.textContent = state;
statusDiv.append(statusLabel, badge);
rowMain.appendChild(statusDiv);
const details = document.createElement("details");
details.className = "xt-details";
const summary = document.createElement("summary");
summary.textContent = "Mostra dettagli";
details.appendChild(summary);
details.appendChild(catNode("Live", x.live_list_ids));
details.appendChild(catNode("Film", x.movie_list_ids));
details.appendChild(catNode("Serie", x.series_list_ids));
details.appendChild(catNode("Miste", x.mixed_list_ids));
rowMain.appendChild(details);
const opsDiv = document.createElement("div");
opsDiv.className = "row-ops";
const btn = (txt, act, extra)=>{ const b = document.createElement("button"); b.className = "small" + (extra ? " " + extra : ""); b.textContent = txt; b.dataset.act = act; return b; };
const editBtn = btn("Modifica nel form", "edit");
const refreshBtn = btn("Aggiorna", "refresh");
const clearCacheBtn = btn("Pulisci Cache", "clear-cache", "warning");
const copyServerBtn = btn("Copia URL server", "copy-server");
const copyFullBtn = btn("Copia URL completa", "copy-full");
const delBtn = btn("Elimina", "del", "danger");
opsDiv.append(editBtn, refreshBtn, clearCacheBtn, copyServerBtn, copyFullBtn, delBtn);
row.appendChild(opsDiv);
editBtn.onclick = ()=>{ startEditXtream(x); };
refreshBtn.onclick = async ()=>{ const hrs = parseInt(hrsInput.value,10)||12; // salva eventuale nuova cadenza (non blocca in caso di errore)
try { await jpost(`/admin/xtreams/${x.id}/update`, { every_hours: hrs }); } catch(e){} // avvia refresh asincrono e attiva polling dello stato
try { await jpost(`/admin/xtreams/${x.id}/refresh`, {}); } catch(e){ console.error(e); }
await loadXtreams();
startXtreamPolling(x.id); };
clearCacheBtn.onclick = async ()=>{ if(!confirm("Sei sicuro di voler pulire la cache per questo account?\\nIl file verrà rimosso e lo stato tornerà 'scaduta'.")) return;
await jpost(`/admin/xtreams/${x.id}/clear_cache`);
await loadXtreams(); };
delBtn.onclick = async ()=>{ if(!confirm("Eliminare questo xtream?")) return;
await jdel(`/admin/xtreams/${x.id}`);
await loadXtreams(); };
copyServerBtn.onclick = async ()=>{ const s = serverUrl; try{ await navigator.clipboard.writeText(s); alert("Copiato: " + s); } catch(e){ const ta = document.createElement("textarea"); ta.value=s; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); alert("Copiato (fallback): " + s); } };
copyFullBtn.onclick = async ()=>{ const s = fullUrl; try{ await navigator.clipboard.writeText(s); alert("Copiato: " + s); } catch(e){ const ta = document.createElement("textarea"); ta.value=s; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); alert("Copiato (fallback): " + s); } };
box.appendChild(row); } }catch(e){ console.error(e); box.textContent = "";
const p = document.createElement("p");
p.className = "muted";
p.textContent = "Errore nel caricare gli xtream";
box.appendChild(p); } }
// --- Polling stato cache Xtream ---
const _xtPolls = new Map(); // xt_id -> intervalId
function startXtreamPolling(xtId){ if(_xtPolls.has(xtId)) return;
let attempts = 0;
const maxAttempts = 90; // ~3 minuti a 2s
const iv = setInterval(async ()=>{ attempts++;
try{ const { items } = await jget('/admin/xtreams.json');
const it = (items||[]).find(i=>i.id===xtId);
const st = (it && it.cache_status) || ''; // aggiorna la lista per riflettere badge/stato aggiornati
await loadXtreams();
if(st === 'pronta' || attempts >= maxAttempts){ clearInterval(iv);
_xtPolls.delete(xtId); } }catch(e){ /* ignora errori transienti */ } }, 2000);
_xtPolls.set(xtId, iv); }
function addCustomCss() { const style = document.createElement('style');
style.textContent = `
  .status-pronta b { color: #28a745; }
  .status-scaduta b { color: #fd7e14; }
  .status-in-costruzione b { color: #007bff; }
  button.small.warning { background-color: #ffc107; border-color: #ffc107; color: #212529; }
  button.small.warning:hover { background-color: #e0a800; border-color: #d39e00; }
  /* Drag & drop playlists */
  #lists .row { transition: background-color .12s ease; }
  #lists .row.drag-over { outline: 2px dashed #0a7; background-color: rgba(0,170,119,0.06); }
`;
document.head.appendChild(style); }
// ---------------- Boot ----------------
document.addEventListener("DOMContentLoaded", ()=>{ const btnSaveEl = byId("btnSave");
if(btnSaveEl) btnSaveEl.onclick = saveSettings; // sezione convert rimossa: nessun binding
byId("btnAdd").onclick = addList;
const btnSaveXt = byId("btnSaveXtream");
if(btnSaveXt) btnSaveXt.onclick = saveXtream;
const btnCancelXt = byId("btnCancelXtream");
if(btnCancelXt) btnCancelXt.onclick = resetXtreamForm; // Prepara select endpoint per Xtream
if(byId('xt_resolver')){ byId('xt_resolver').innerHTML = buildResolverOptionsHtml(''); }
// Multi-select toggling by click (no Ctrl required)
enableMultiSelectToggle(byId('xt_live'));
enableMultiSelectToggle(byId('xt_movies'));
enableMultiSelectToggle(byId('xt_series'));
enableMultiSelectToggle(byId('xt_mixed')); // Resolvers UI bindings
const btnSavePol = byId("btnSavePolicy");
if(btnSavePol) btnSavePol.onclick = savePolicy;
const btnTestPol = byId("btnTestPolicy");
if(btnTestPol) btnTestPol.onclick = testPolicy;
const btnUpload = byId("btnUploadResolver");
if(btnUpload) btnUpload.onclick = uploadResolver;
const btnSaveOrder = byId("btnSaveOrder");
if(btnSaveOrder) btnSaveOrder.onclick = savePoliciesOrder;
const btnDecode = byId("btnDecode");
if(btnDecode) btnDecode.onclick = decodeUrl;
// Link Groups bindings
const btnLgReload = byId('btnLgReload');
if(btnLgReload) btnLgReload.onclick = loadLinkRoots;
const btnLgApply = byId('btnLgApply');
if(btnLgApply) btnLgApply.onclick = applyLinkGroups;
const flowSel = byId('pol_flow');
if(flowSel) flowSel.onchange = updateFlowUI; // Abilita/disabilita Step 3 quando cambia "Step successivo" del Resolver
const nextAfterSel = byId('pol_next_after_resolver');
if(nextAfterSel) nextAfterSel.onchange = updateFlowUI;
const proxType = byId('mf_proxy_type');
if(proxType) proxType.onchange = updateMfProxyUI;
const mfEndpoint = byId('mf_endpoint_main');
if(mfEndpoint){ mfEndpoint.onchange = ()=>{ updateMfProxyUI(); }; }
updateFlowUI();
const btnExVavoo = byId('btnExampleVavoo');
if(btnExVavoo) btnExVavoo.onclick = exampleVavoo;
const btnExVix = byId('btnExampleVix');
if(btnExVix) btnExVix.onclick = exampleVix;
initTabs();
resetXtreamForm();
addCustomCss();
loadSettings().then(async ()=>{ await loadLists();
await loadXtreams();
await loadPolicies();
await loadResolverFiles();
try{ await loadLinkRoots(); }catch(_){ }
}); // Preset bottoni per Campi export Xtream
// Bind per-field DB toggles
function _bindDbToggle(inputId, chkId){
  const inp = byId(inputId); const ck = byId(chkId);
  if(!inp || !ck) return;
  const apply = ()=>{ inp.disabled = !!ck.checked; if(ck.checked){ inp.classList.add('disabled'); } else { inp.classList.remove('disabled'); } };
  ck.addEventListener('change', apply);
  apply();
}
_bindDbToggle('hdr_referer','hdr_referer_use_db');
_bindDbToggle('hdr_origin','hdr_origin_use_db');
_bindDbToggle('hdr_useragent','hdr_useragent_use_db');
_bindDbToggle('ck_kid','ck_kid_use_db');
_bindDbToggle('ck_key','ck_key_use_db');
const set = (id, v)=>{ const el = byId(id);
if(el) el.checked = !!v; };
function preset_clear(){ const ids = [ // live
'xlf_stream_icon','xlf_epg_channel_id','xlf_category_name','xlf_category_id','xlf_stream_type','xlf_rating','xlf_rating5','xlf_added','xlf_tv_archive','xlf_tv_archive_duration','xlf_direct_source','xlf_custom_sid', // film
'xmf_stream_icon','xmf_added','xmf_category_ids','xmf_num','xmf_tmdb_id','xmf_imdb_id','xmf_year','xmf_releasedate','xmf_movie_image','xmf_backdrop_path','xmf_plot','xmf_duration','xmf_duration_secs','xmf_genre','xmf_rating','xmf_director','xmf_cast','xmf_country','xmf_production_countries','xmf_youtube_trailer', // serie
'xsf_cover','xsf_cover_big','xsf_category_ids','xsf_last_modified','xsf_num','xsf_tmdb_id','xsf_imdb_id','xsf_releaseDate','xsf_backdrop_path','xsf_plot','xsf_genre','xsf_rating','xsf_director','xsf_cast','xsf_origin_country','xsf_youtube_trailer','xsf_network','xsf_status', // stagioni
'xss_name','xss_overview','xss_cover','xss_poster_path','xss_air_date','xss_id','xss_backdrop_path','xss_vote_average', // episodi
'xef_tmdb_id','xef_imdb_id','xef_releaseDate','xef_backdrop_path','xef_plot','xef_duration','xef_duration_secs','xef_rating','xef_added' ];
ids.forEach(id=> set(id, false)); }
function preset_tivimate(){ preset_clear(); // Live: logo + EPG id
set('xlf_stream_icon', true);
set('xlf_epg_channel_id', true); // Movies: image/backdrop/plot/rating/year
['xmf_movie_image','xmf_backdrop_path','xmf_plot','xmf_rating','xmf_year'].forEach(id=> set(id, true)); // Series: cover/backdrop/plot/rating/releaseDate
['xsf_cover','xsf_backdrop_path','xsf_plot','xsf_rating','xsf_releaseDate'].forEach(id=> set(id, true)); // Seasons: light extras
['xss_name','xss_overview','xss_poster_path','xss_air_date'].forEach(id=> set(id, true)); // Episodes: plot/duration/releaseDate/backdrop
['xef_plot','xef_duration','xef_releaseDate','xef_backdrop_path'].forEach(id=> set(id, true)); }
function preset_full(){ preset_clear(); // Live: all
['xlf_stream_icon','xlf_epg_channel_id','xlf_category_name','xlf_category_id','xlf_stream_type','xlf_rating','xlf_rating5','xlf_added','xlf_tv_archive','xlf_tv_archive_duration','xlf_direct_source','xlf_custom_sid'].forEach(id=> set(id, true)); // Movies: all in UI
['xmf_stream_icon','xmf_added','xmf_category_ids','xmf_num','xmf_tmdb_id','xmf_imdb_id','xmf_year','xmf_releasedate','xmf_movie_image','xmf_backdrop_path','xmf_plot','xmf_duration','xmf_duration_secs','xmf_genre','xmf_rating','xmf_director','xmf_cast','xmf_country','xmf_production_countries','xmf_youtube_trailer'].forEach(id=> set(id, true)); // Series: all in UI
['xsf_cover','xsf_cover_big','xsf_category_ids','xsf_last_modified','xsf_num','xsf_tmdb_id','xsf_imdb_id','xsf_releaseDate','xsf_backdrop_path','xsf_plot','xsf_genre','xsf_rating','xsf_director','xsf_cast','xsf_origin_country','xsf_youtube_trailer','xsf_network','xsf_status'].forEach(id=> set(id, true)); // Seasons: all in UI
['xss_name','xss_overview','xss_cover','xss_poster_path','xss_air_date','xss_id','xss_backdrop_path','xss_vote_average'].forEach(id=> set(id, true)); // Episodes: all in UI
['xef_tmdb_id','xef_imdb_id','xef_releaseDate','xef_backdrop_path','xef_plot','xef_duration','xef_duration_secs','xef_rating','xef_added'].forEach(id=> set(id, true)); }
function preset_min(){ // Only mandatory kept (all checkboxes off)
preset_clear(); }
const pSafe = byId('xpreset_safe');
if(pSafe) pSafe.onclick = ()=> preset_tivimate();
const pFull = byId('xpreset_full');
if(pFull) pFull.onclick = ()=> preset_full();
const pMin = byId('xpreset_min');
if(pMin) pMin.onclick = ()=> preset_min();
const pClr = byId('xpreset_clear');
if(pClr) pClr.onclick = ()=> preset_clear();
const addDbp = byId('btnAddDbp');
if(addDbp){ addDbp.onclick = ()=>{ const n = (byId('dbp_new_name')?.value || '').trim();
const u = (byId('dbp_new_url')?.value || '').trim();
if(!n || !u){ alert('Inserisci nome e DATABASE_URL'); return; }
if(_dbps.find(p=>p.name===n)){ alert('Esiste già un profilo con lo stesso nome'); return; }
_dbps.push({ name: n, url: u });
const actSel = byId('dbp_active');
if(actSel){ actSel.value = n; }
_activeDb = n;
const inp = byId('cfg_dburl');
if(inp) inp.value = u;
byId('dbp_new_name').value='';
byId('dbp_new_url').value='';
renderDbProfiles(); }; }
});
// ---------------- Resolvers (policies) ----------------
async function loadPolicies(){ const box = byId("policies");
if(!box) return;
box.textContent = "carico...";
try{ const { items } = await jget('/admin/resolvers/policies.json');
box.textContent = "";
if(!items || !items.length){ const p = document.createElement('p');
p.className='muted';
p.textContent='Nessuna regola definita';
box.appendChild(p);
return; }
for(const p of items){ const row = document.createElement('div');
row.className='row';
row.draggable = true;
row.dataset.id = p.id;
row.addEventListener('dragstart', onPolDragStart);
row.addEventListener('dragover', onPolDragOver);
row.addEventListener('drop', onPolDrop);
const main = document.createElement('div');
main.className='row-main';
row.appendChild(main);
const title = document.createElement('div');
const b = document.createElement('b');
b.textContent = `${p.match} [${p.match_type}]`;
title.appendChild(b);
main.appendChild(title);
const info = document.createElement('div');
info.className='muted';
info.textContent = `kind=${p.kind} • local=${p.local_mode} • remote=${p.remote_mode} • priority=${p.priority} • enabled=${p.enabled}`;
main.appendChild(info);
const ops = document.createElement('div');
ops.className='row-ops';
row.appendChild(ops);
const btn = (t, cls)=>{ const el=document.createElement('button');
el.className='small'+(cls?(' '+cls):'');
el.textContent=t;
return el; };
const edit = btn('Modifica');
const del = btn('Elimina','danger');
edit.onclick = ()=> editPolicy(p);
del.onclick = async ()=>{ if(!confirm('Eliminare questa regola?')) return;
await jdel(`/admin/resolvers/policies/${p.id}`);
await loadPolicies(); };
ops.append(edit, del);
box.appendChild(row); } }catch(e){ box.textContent='';
const p=document.createElement('p');
p.className='muted';
p.textContent='Errore nel caricare le policy';
box.appendChild(p); } }
// --- Tabs ---
function initTabs(){ const nav = document.querySelector('.tab-nav');
const btns = document.querySelectorAll('.tab-btn'); // expose global handler to be extra-robust (can also be used inline)
window.showTab = function(target){ const panels = document.querySelectorAll('.tab-panel');
btns.forEach(b=>b.classList.toggle('active', b.getAttribute('data-target')===target));
panels.forEach(p=>{ const on = p.id === target;
p.classList.toggle('active', on);
p.style.display = on ? 'block' : 'none'; });
try{ const name = target.replace(/^tab-/, '');
const sp = new URLSearchParams(window.location.hash.slice(1));
sp.set('tab', name);
window.location.hash = sp.toString(); }catch(e){} 
 // Hook: when switching to DB browser tab, lazy-load tables
 if(target === 'tab-browse-db'){ try{ if(!_db_tables_loaded) loadDbTables(); }catch(_){} }
}; // initialize from hash or default
const hash = new URLSearchParams(window.location.hash.slice(1)).get('tab');
const initial = hash ? `tab-${hash}` : (document.querySelector('.tab-btn.active')?.getAttribute('data-target') || 'tab-settings');
window.showTab(initial);
if(nav){ nav.addEventListener('click', (e)=>{ const btn = e.target.closest('.tab-btn');
if(!btn) return;
e.preventDefault();
const target = btn.getAttribute('data-target');
if(target) window.showTab(target); }); } }
function editPolicy(p){ byId('pol_id').value = p.id || '';
byId('pol_match').value = p.match || '';
byId('pol_match_type').value = p.match_type || 'substr';
byId('pol_kind').value = p.kind || 'any';
byId('pol_local_mode').value = p.local_mode || 'direct';
byId('pol_remote_mode').value = p.remote_mode || 'direct';
const internal = p.internal || {};
const mf = p.mediaflow || {};
byId('pol_internal').value = internal.path ? `path:"${internal.path}"` : (internal.tag ? `tag:"${internal.tag}""` : '');
byId('pol_mf_host').value = mf.host || '';
byId('pol_mf_redirect').value = (mf.redirect_stream ? 'true' : 'false');
populateMFDropdown(mf.preset || '');
// no global use_db toggle anymore (per-field instead)
byId('pol_proxy').value = (p.proxy ? 'true' : 'false');
byId('pol_priority').value = p.priority || 100;
byId('pol_enabled').value = (p.enabled ? 'true' : 'false'); }
function _parseInternalField(v){ v = (v||'').trim();
if(!v) return {}; // supporta formati semplici: tag:"name" oppure path:"/abs/path.py"
const mTag = v.match(/tag\s*:\s*"([^"]+)"/i);
if(mTag) return { tag: mTag[1] };
const mPath = v.match(/path\s*:\s*"([^"]+)"/i);
if(mPath) return { path: mPath[1] }; // fallback: se sembra un path
if(v.endsWith('.py')) return { path: v };
return {}; }
async function savePolicy(){ const id = byId('pol_id').value.trim();
const payload = { match: byId('pol_match').value.trim(), match_type: byId('pol_match_type').value, kind: byId('pol_kind').value, local_mode: byId('pol_local_mode').value, remote_mode: byId('pol_remote_mode').value, internal: _parseInternalField(byId('pol_internal').value), mediaflow: { host: byId('pol_mf_host').value.trim(), redirect_stream: (byId('pol_mf_redirect').value==='true') }, proxy: (byId('pol_proxy').value==='true'), priority: parseInt(byId('pol_priority').value,10)||100, enabled: (byId('pol_enabled').value==='true'), };
try{ if(id){ await jpost(`/admin/resolvers/policies/${id}`, payload); } else{ await jpost('/admin/resolvers/policies', payload); }
byId('pol_id').value='';
await loadPolicies(); }catch(e){ alert('Errore salvataggio policy: ' + e.message); } }
async function testPolicy(){ const url = byId('ptest_url').value.trim();
const kind = byId('ptest_kind').value;
const execute = (byId('ptest_exec').value==='true');
const out = byId('ptest_out');
out.textContent = 'eseguo...';
try{ const res = await jpost('/admin/resolvers/test', { url, kind, execute });
out.textContent = JSON.stringify(res, null, 2); }catch(e){ out.textContent = 'Errore: ' + e.message; } }
// --- Step 1: decode base64 ---
function decodeUrl(){ const inp = byId('rule_url');
const out = byId('decode_out');
const v = (inp.value||'').trim();
if(!v){ out.textContent=''; return; } // prova a decodificare base64 (grezzo)
try{ // estrai la parte base64 se contiene solo URL-safe chars
const m = v.match(/[A-Za-z0-9+/=_%-]{12,}/);
let src = v;
if(m) src = m[0];
const decoded = atob(src.replace(/_/g,'/').replace(/-/g,'+'));
out.textContent = 'Decodificato: ' + decoded; // se contiene dominio, proponi il match
try{ const u = new URL(decoded);
const host = u.hostname.replace(/\./g,'\\.');
byId('pol_match').value = host; }catch(e){} }catch(e){ out.textContent = 'Non sembra base64 valido'; } }
// --- Step 2: lista resolver installati ---
async function loadResolverFiles(){ const sel = byId('rz_list');
if(!sel) return;
try{ const { items } = await jget('/admin/resolvers/list_files');
sel.innerHTML = (items||[]).map(it=>`<option value="${it.path}">${it.name}</option>`).join(''); }catch(e){ sel.innerHTML=''; } }
// --- Step toggles ---
function updateFlowUI(){ const flow = byId('pol_flow')?.value;
const stepRes = byId('step_resolver');
const stepMF = byId('step_mediaflow');
const nextSel = byId('pol_next_after_resolver');
const desc = byId('flow_desc');
const setFsDisabled = (fs, on)=>{ if(!fs) return;
fs.disabled = !!on;
if(on){ fs.setAttribute('disabled',''); } else { fs.removeAttribute('disabled'); } };
if(flow==='direct'){ setFsDisabled(stepRes, true);
setFsDisabled(stepMF, true);
if(desc) desc.textContent = 'Diretto – restituisce il link originale al client.'; }else if(flow==='internal'){ setFsDisabled(stepRes, false);
const disableMF = (nextSel ? nextSel.value==='return' : true);
setFsDisabled(stepMF, disableMF);
if(desc) desc.textContent = 'Resolver – usa uno script per risolvere il link; opzionalmente poi invia a Mediaflow.'; }else if(flow==='mediaflow'){ setFsDisabled(stepRes, true);
setFsDisabled(stepMF, false);
if(desc) desc.textContent = 'Mediaflow – invia direttamente a MediaFlow-proxy con i parametri configurati.'; }else if(flow==='direct_remote_mf'){ setFsDisabled(stepRes, true);
setFsDisabled(stepMF, false);
if(desc) desc.textContent = 'Diretto – Mediaflow da remoto – diretto in LAN, Mediaflow se il client è remoto.'; } // sincronizza tipologia extractor con selezione tipologia principale
const ek = byId('mf_extractor_kind');
if(ek){ ek.value = byId('pol_kind').value; } }
 // Per-field DB toggles handled separately; no global auto-toggle
function updateMfProxyUI(){ const t = byId('mf_proxy_type').value;
const sub = byId('mf_proxy_sub');
if(t==='hls'){ sub.innerHTML = '<option value="manifest.m3u8">manifest.m3u8</option><option value="segment">segment</option>'; }else if(t==='dash'){ sub.innerHTML = '<option value="segment">segment</option>'; }else if(t==='stream'){ sub.innerHTML = '<option value=":filename">(nessuno)</option><option value="{filename}">{filename}</option>'; }else if(t==='mpd'){ sub.innerHTML = '<option value="manifest.m3u8">manifest.m3u8 (DASH→HLS)</option><option value="segment.mp4">segment.mp4</option>'; } }
// --- Costruzione payload policy dagli step ---
function buildPolicyPayloadFromSteps(){ const match = byId('pol_match').value.trim();
const kind = (byId('pol_kind').value||'video').toLowerCase();
const flow = byId('pol_flow').value; // map flow to modes
let local_mode='direct', remote_mode='direct';
if(flow==='direct'){ local_mode='direct';
remote_mode='direct'; } else if(flow==='internal'){ local_mode='internal';
remote_mode = (byId('pol_next_after_resolver').value==='return') ? 'internal' : 'mediaflow'; } else if(flow==='mediaflow'){ local_mode='mediaflow';
remote_mode='mediaflow'; } else if(flow==='direct_remote_mf'){ local_mode='direct';
remote_mode='mediaflow'; }
const internal = {};
if(local_mode==='internal' || remote_mode==='internal'){ const p = byId('rz_list').value;
if(p) internal.path = p; }
const mf = {};
const em = byId('mf_endpoint_main').value;
if(local_mode==='mediaflow' || remote_mode==='mediaflow' || byId('pol_next_after_resolver').value!=='return'){ const presetName = (byId('mf_preset')?.value || '').trim();
if(presetName) mf.preset = presetName;
if(em==='proxy'){ const typ = byId('mf_proxy_type').value;
let sub = byId('mf_proxy_sub').value;
let path = typ;
if(sub){ if(typ==='stream' && sub===':filename') path = 'stream';
else path += '/' + sub; }
mf.endpoint = 'proxy';
mf.path = path; // es. hls/manifest.m3u8
// headers/opzioni avanzate
const h = {};
if(!byId('hdr_referer_use_db')?.checked){ const ref = byId('hdr_referer').value.trim(); if(ref) h['h_referer']=ref; }
if(!byId('hdr_origin_use_db')?.checked){ const ori = byId('hdr_origin').value.trim(); if(ori) h['h_origin']=ori; }
if(!byId('hdr_useragent_use_db')?.checked){ const ua = byId('hdr_useragent').value.trim(); if(ua) h['h_user-agent']=ua; }
mf.headers = h;
const fpp = byId('opt_force_playlist_proxy').value==='true';
if(fpp) mf.force_playlist_proxy = true;
const kid = byId('ck_kid').value.trim();
const key = byId('ck_key').value.trim();
if(!(byId('ck_kid_use_db')?.checked || byId('ck_key_use_db')?.checked)){
  if(kid && key){ mf.clearkey = { key_id: kid, key: key } }
}
 }else{ // extractor/video
mf.endpoint = 'extractor_video';
mf.kind = byId('mf_extractor_kind').value;
mf.host = byId('pol_mf_host').value.trim();
mf.redirect_stream = (byId('pol_mf_redirect').value==='true'); } }
 // Usa metadati per-item da DB (toggle UI)
 // Per-field DB flags
 try{
   const dbf = {};
   if(byId('hdr_referer_use_db')?.checked) dbf['h_referer'] = true;
   if(byId('hdr_origin_use_db')?.checked) dbf['h_origin'] = true;
   if(byId('hdr_useragent_use_db')?.checked) dbf['h_user-agent'] = true;
   if(byId('ck_kid_use_db')?.checked) dbf['key_id'] = true;
   if(byId('ck_key_use_db')?.checked) dbf['key'] = true;
   if(Object.keys(dbf).length) mf.db_fields = dbf;
 }catch(_){ }
return { match, match_type:'regex', kind, local_mode, remote_mode, internal, mediaflow: mf, proxy: false, priority: 100, enabled: true, }; }
async function savePolicy(){ const id = (byId('pol_id').value||'').trim();
const payload = buildPolicyPayloadFromSteps(); // Require MF preset selection when flow uses MediaFlow and presets exist
const flow = byId('pol_flow').value;
const needMF = (flow==='mediaflow') || (flow==='direct_remote_mf') || (flow==='internal' && byId('pol_next_after_resolver').value!=='return');
if(needMF && _mf.length>0){ const chosen = (byId('mf_preset')?.value || '').trim();
if(!chosen){ alert('Seleziona un MediaFlow proxy'); return; } }
try{ if(id){ await jpost(`/admin/resolvers/policies/${id}`, payload); } else{ await jpost('/admin/resolvers/policies', payload); }
byId('pol_id').value='';
await loadPolicies(); }catch(e){ alert('Errore salvataggio policy: ' + e.message); } }
// --- Esempi precompilati ---
async function exampleVavoo(){ byId('pol_match').value = 'vavoo\\.to';
byId('pol_kind').value = 'tv';
byId('pol_flow').value = 'internal';
updateFlowUI(); // tenta di selezionare il resolver sample
await loadResolverFiles();
const sel = byId('rz_list');
const opts = [...(sel?.options||[])];
const sample = (opts.find(o=>/vavoo_resolver\\.py$/i.test(o.value)) || opts[0]);
if(sample) sel.value = sample.value;
byId('pol_next_after_resolver').value = 'mediaflow_remote'; // riflette immediatamente l'attivazione del 3° step
updateFlowUI(); // pre-seleziona il primo MediaFlow disponibile
populateMFDropdown();
const mfSel = byId('mf_preset');
if(mfSel && mfSel.options.length>1) mfSel.selectedIndex = 1;
alert('Esempio Vavoo (TV) caricato. Ricorda di salvare la regola.'); }
async function exampleVix(){ byId('pol_match').value = '(vixsrc\\.to|vixsrl\\.to)';
byId('pol_kind').value = 'video';
byId('pol_flow').value = 'mediaflow';
updateFlowUI();
byId('mf_endpoint_main').value = 'extractor_video';
byId('mf_extractor_kind').value = 'video';
byId('pol_mf_host').value = 'VixCloud';
byId('pol_mf_redirect').value = 'true';
populateMFDropdown();
const mfSel2 = byId('mf_preset');
if(mfSel2 && mfSel2.options.length>1) mfSel2.selectedIndex = 1;
alert('Esempio VixSrc (Video) caricato. Ricorda di salvare la regola.'); }
// --- Upload Resolver (.py) ---
let _rz_lastFile = null;
function initDropArea(){ const drop = byId('rz_drop');
const inp = byId('rz_file');
if(!drop || !inp) return;
drop.addEventListener('dragover', e=>{ e.preventDefault();
drop.style.borderColor='#0a7'; });
drop.addEventListener('dragleave', e=>{ drop.style.borderColor='#ccc'; });
drop.addEventListener('drop', e=>{ e.preventDefault();
drop.style.borderColor='#ccc';
const f=e.dataTransfer.files[0];
if(f) { _rz_lastFile=f;
byId('rz_status').textContent = `Selezionato: ${f.name}`; }});
inp.addEventListener('change', e=>{ const f=inp.files[0];
if(f){ _rz_lastFile=f;
byId('rz_status').textContent = `Selezionato: ${f.name}`; }}); }
initDropArea();
async function uploadResolver(){ const st = byId('rz_status');
if(!_rz_lastFile){ st.textContent='Seleziona un file .py'; return; }
if(!_rz_lastFile.name.toLowerCase().endsWith('.py')){ st.textContent='Solo file .py'; return; }
if(_rz_lastFile.size > 512*1024){ st.textContent='File troppo grande (>512KiB)'; return; }
const fd = new FormData();
fd.append('file', _rz_lastFile);
try{ const r = await fetch('/admin/resolvers/upload', { method:'POST', body: fd });
if(!r.ok){ st.textContent='Errore upload'; return; }
const js = await r.json();
if(js.path){ st.textContent = `Caricato in: ${js.path}`;
const polInternal = byId('pol_internal');
if(polInternal) polInternal.value = `path:"${js.path}"`; } }catch(e){ st.textContent='Errore: ' + e.message; } }
// --- Drag&Drop reorder policies ---
let _dragPolId = null;
function onPolDragStart(e){ _dragPolId = e.currentTarget.dataset.id; }
function onPolDragOver(e){ e.preventDefault(); }
function onPolDrop(e){ e.preventDefault();
const target = e.currentTarget;
const container = byId('policies');
if(!_dragPolId||!container) return;
const dragEl = [...container.children].find(n=>n.dataset && n.dataset.id===_dragPolId);
if(!dragEl) return;
if(dragEl===target) return; // insert before target
container.insertBefore(dragEl, target); }
async function savePoliciesOrder(){ const container = byId('policies');
if(!container) return;
const order = [...container.children].map(n=>n.dataset && n.dataset.id).filter(Boolean);
try{ await jpost('/admin/resolvers/policies/reorder', { order });
await loadPolicies(); }catch(e){ alert('Errore salvataggio ordine: '+e.message); } }
// removed misplaced handlers (moved into loadLists loop)
function renderDbProfiles(){ const sel = document.getElementById('dbp_active');
const inp = document.getElementById('cfg_dburl');
if(!sel) return;
sel.innerHTML = (_dbps&&_dbps.length? _dbps: [{name:'default', url: (inp?.value||'')}]).map(p=>`<option value="${p.name}">${p.name}</option>`).join('');
sel.value = _activeDb || (sel.options[0]?.value || 'default'); // sync input with active profile if exists
const cur = (_dbps||[]).find(p=>p.name===sel.value);
if(cur && inp){ inp.value = cur.url; }
sel.onchange = ()=>{ _activeDb = sel.value;
const cur2 = (_dbps||[]).find(p=>p.name===_activeDb);
if(cur2 && inp){ inp.value = cur2.url; } }; }

// Per-field DB toggle: disable input when checked
function _bindDbToggle(inputId, chkId){
  const inp = byId(inputId); const ck = byId(chkId);
  if(!inp || !ck) return;
  const apply = ()=>{ inp.disabled = !!ck.checked; if(ck.checked){ inp.classList.add('disabled'); } else { inp.classList.remove('disabled'); } };
  ck.addEventListener('change', apply);
  apply();
}

// --- Link Groups helpers ---
function _optHtml(list, valueKey, labelKey){ return (list||[]).map(it=>`<option value="${String(it[valueKey]||'')}">${it[labelKey]}${it.count!=null?` (${it.count})`:''}</option>`).join(''); }
async function loadLinkRoots(){
  try{
    const res = await jget('/admin/links/roots');
    const lp = byId('lg_live_prot');
    const ln = byId('lg_live_plain');
    const vd = byId('lg_vod');
    if(lp) lp.innerHTML = _optHtml(res.live_protected||[], 'host', 'host');
    if(ln) ln.innerHTML = _optHtml(res.live_plain||[], 'host', 'host');
    if(vd) vd.innerHTML = _optHtml(res.vod||[], 'host', 'host');
  }catch(e){
    console.error('loadLinkRoots failed', e);
  }
}
function _selectedValues(sel){ return Array.from((sel?.selectedOptions)||[]).map(o=>o.value).filter(Boolean); }
function _currentMfConfig(forceUseDb){
  const mf = {};
  const presetName = (byId('mf_preset')?.value || '').trim();
  if(presetName) mf.preset = presetName;
  const em = byId('mf_endpoint_main')?.value || 'proxy';
  if(em==='proxy'){
    const typ = byId('mf_proxy_type')?.value || 'hls';
    let sub = byId('mf_proxy_sub')?.value || 'manifest.m3u8';
    let path = typ;
    if(sub){ if(typ==='stream' && sub===':filename') path='stream'; else path += '/' + sub; }
    mf.endpoint = 'proxy';
    mf.path = path;
    const h = {};
    const ref = byId('hdr_referer')?.value.trim(); if(ref) h['h_referer']=ref;
    const ori = byId('hdr_origin')?.value.trim(); if(ori) h['h_origin']=ori;
    const ua = byId('hdr_useragent')?.value.trim(); if(ua) h['h_user-agent']=ua;
    if(Object.keys(h).length) mf.headers = h;
    const fpp = byId('opt_force_playlist_proxy')?.value==='true'; if(fpp) mf.force_playlist_proxy = true;
  }else{
    mf.endpoint = 'extractor_video';
    mf.kind = byId('mf_extractor_kind')?.value || 'video';
    mf.host = byId('pol_mf_host')?.value.trim() || '';
    mf.redirect_stream = (byId('pol_mf_redirect')?.value==='true');
  }
  if(forceUseDb){ mf.use_db_metadata = true; }
  return mf;
}
async function applyLinkGroups(){
  const st = byId('lgStatus'); if(st) st.textContent = 'creo...';
  try{
    const lpSel = byId('lg_live_prot');
    const lnSel = byId('lg_live_plain');
    const vdSel = byId('lg_vod');
    const liveProt = _selectedValues(lpSel);
    const livePlain = _selectedValues(lnSel);
    const vod = _selectedValues(vdSel);
    // Live protetti -> mediaflow + use_db_metadata
    for(const host of liveProt){
      const payload = {
        match: host, match_type: 'substr', kind: 'tv',
        local_mode: 'mediaflow', remote_mode: 'mediaflow',
        internal: {}, mediaflow: _currentMfConfig(true), proxy: false,
        priority: 100, enabled: true,
      };
      await jpost('/admin/resolvers/policies', payload);
    }
    // Live plain -> direct
    for(const host of livePlain){
      const payload = {
        match: host, match_type: 'substr', kind: 'tv',
        local_mode: 'direct', remote_mode: 'direct',
        internal: {}, mediaflow: {}, proxy: false,
        priority: 100, enabled: true,
      };
      await jpost('/admin/resolvers/policies', payload);
    }
    // VOD -> mediaflow extractor (no DB metadata)
    for(const host of vod){
      const mf = _currentMfConfig(false);
      // ensure extractor_video
      if(mf.endpoint !== 'proxy'){
        // ok, already extractor
      }else{
        // force extractor/video minimal
        mf.endpoint = 'extractor_video';
        mf.kind = byId('mf_extractor_kind')?.value || 'video';
        mf.host = byId('pol_mf_host')?.value.trim() || '';
        mf.redirect_stream = (byId('pol_mf_redirect')?.value==='true');
        delete mf.path; delete mf.headers; delete mf.force_playlist_proxy; delete mf.use_db_metadata;
      }
      const payload = {
        match: host, match_type: 'substr', kind: 'video',
        local_mode: 'mediaflow', remote_mode: 'mediaflow',
        internal: {}, mediaflow: mf, proxy: false,
        priority: 100, enabled: true,
      };
      await jpost('/admin/resolvers/policies', payload);
    }
    if(st) st.textContent = 'ok'; setTimeout(()=>{ if(st) st.textContent=''; }, 1200);
    await loadPolicies();
  }catch(e){ console.error('applyLinkGroups failed', e); if(st) st.textContent = 'errore'; }
}
