async function jget(url) {
  const r = await fetch(url, { credentials: "omit" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body || {})
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function jdel(url) {
  const r = await fetch(url, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function byId(id){ return document.getElementById(id); }

let _lists = []; // per popolare le select Xtream
let _editingXt = null; // id xtream in modifica

// ---------------- Settings ----------------
async function loadSettings(){
  try{
    const { settings } = await jget("/admin/settings.json");
    byId("mediaflow_url").value = settings.mediaflow_url || "";
    byId("api_password").value = settings.api_password || "";
    byId("stream_resolver_url").value = settings.stream_resolver_url || "";
  }catch(e){ console.error(e); }
}
async function saveSettings(){
  const payload = {
    mediaflow_url: byId("mediaflow_url").value.trim(),
    api_password: byId("api_password").value,
    stream_resolver_url: byId("stream_resolver_url").value.trim()
  };
  const status = byId("saveStatus");
  status.textContent = "salvataggio...";
  try{
    await jpost("/admin/settings.json", payload);
    status.textContent = "ok";
    setTimeout(()=> status.textContent="", 1500);
  }catch(e){
    console.error(e);
    status.textContent = "errore";
  }
}

// ---------------- Converti una-tantum ----------------
async function convertOnce(){
  const url = byId("conv_url").value.trim();
  const mode = byId("conv_mode").value;
  if(!url){ alert("Inserisci URL"); return; }
  let r = await fetch("/admin/convert", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ url, mode })
  });
  if(!r.ok){
    const t = await r.text();
    alert("Errore: " + t);
    return;
  }
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "playlist_convertita.m3u";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---------------- Liste salvate ----------------
async function loadLists(){
  const box = byId("lists");
  box.textContent = "carico...";
  try{
    const { items } = await jget("/admin/playlists.json");
    _lists = items || [];
    if(!items || !items.length){
      box.textContent = "";
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "Nessuna lista salvata";
      box.appendChild(p);
      await populateXtreamSelects();
      return;
    }
    box.textContent = "";
    for(const it of items){
      const row = document.createElement("div");
      row.className = "row";

      const rowMain = document.createElement("div");
      rowMain.className = "row-main";
      row.appendChild(rowMain);

      const nameDiv = document.createElement("div");
      const nameB = document.createElement("b");
      nameB.textContent = it.name;
      nameDiv.appendChild(nameB);
      rowMain.appendChild(nameDiv);

      const urlDiv = document.createElement("div");
      urlDiv.className = "muted";
      urlDiv.textContent = it.url;
      rowMain.appendChild(urlDiv);

      const link = new URL(`./lists/${it.id}.m3u`, location.href).href;
      const linkDiv = document.createElement("div");
      linkDiv.className = "muted";
      linkDiv.textContent = link;
      rowMain.appendChild(linkDiv);

      const typeDiv = document.createElement("div");
      typeDiv.append("Tipo: ");
      const modeB = document.createElement("b");
      modeB.textContent = it.mode;
      typeDiv.appendChild(modeB);
      typeDiv.append(" \u00A0•\u00A0 Aggiorna ogni ");
      const hrsInput = document.createElement("input");
      hrsInput.className = "hrs";
      hrsInput.type = "number";
      hrsInput.min = "1";
      hrsInput.value = it.every_hours;
      typeDiv.appendChild(hrsInput);
      typeDiv.append(" ore");
      rowMain.appendChild(typeDiv);

      const resolverDiv = document.createElement("div");
      resolverDiv.textContent = "Resolver: ";
      const resolverInput = document.createElement("input");
      resolverInput.className = "resolver";
      resolverInput.value = it.resolver_url || "";
      resolverInput.placeholder = "default";
      resolverDiv.appendChild(resolverInput);
      rowMain.appendChild(resolverDiv);

      const lastDiv = document.createElement("div");
      lastDiv.className = "muted";
      lastDiv.textContent = `Ultimo refresh: ${it.last_refresh ? new Date(it.last_refresh*1000).toLocaleString() : "mai"}`;
      rowMain.appendChild(lastDiv);

      const opsDiv = document.createElement("div");
      opsDiv.className = "row-ops";
      const btn = (txt, act, extra)=>{
        const b = document.createElement("button");
        b.className = "small" + (extra ? " " + extra : "");
        b.textContent = txt;
        b.dataset.act = act;
        return b;
      };
      const saveBtn = btn("Aggiorna", "save");
      const refreshBtn = btn("Refresh", "refresh");
      const copyBtn = btn("Copia link", "copy");
      const delBtn = btn("Elimina", "del", "danger");
      opsDiv.append(saveBtn, refreshBtn, copyBtn, delBtn);
      row.appendChild(opsDiv);

      saveBtn.onclick = async ()=>{
        const hrs = parseInt(hrsInput.value,10)||12;
        const resolver = resolverInput.value.trim();
        await jpost(`/admin/playlists/${it.id}/update`, { every_hours: hrs, resolver_url: resolver });
        await loadLists();
        await populateXtreamSelects();
      };
      refreshBtn.onclick = async ()=>{
        const hrs = parseInt(hrsInput.value,10)||12;
        const resolver = resolverInput.value.trim();
        await jpost(`/admin/playlists/${it.id}/update`, { every_hours: hrs, resolver_url: resolver, refresh: true });
        await loadLists();
        await populateXtreamSelects();
      };
      delBtn.onclick = async ()=>{
        if(!confirm("Eliminare questa lista?")) return;
        await jdel(`/admin/playlists/${it.id}`);
        await loadLists();
        await populateXtreamSelects();
      };
      copyBtn.onclick = async ()=>{
        try{
          await navigator.clipboard.writeText(link);
          alert("Link copiato:\n" + link);
        }catch(e){
          const ta = document.createElement("textarea");
          ta.value = link;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
          alert("Link copiato (fallback):\n" + link);
        }
      };

      box.appendChild(row);
    }
    await populateXtreamSelects();
  }catch(e){
    console.error(e);
    box.textContent = "";
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Errore nel caricare le liste";
    box.appendChild(p);
  }
}

async function addList(){
  const name = byId("pl_name").value.trim();
  const url = byId("pl_url").value.trim();
  const mode = byId("pl_mode").value;
  const every_hours = parseInt(byId("pl_every").value,10) || 12;
  if(!name || !url){ alert("Compila nome e url"); return; }
  try{
    await jpost("/admin/playlists", { name, url, mode, every_hours });
    byId("pl_name").value = "";
    byId("pl_url").value = "";
    await loadLists();
  }catch(e){
    console.error(e);
    alert("Errore nel creare la lista");
  }
}

// ---------------- Xtream: helpers UI ----------------
function canonicalServerBase(){
  let base = (byId("stream_resolver_url").value || "").trim();
  if(!base) base = location.origin;
  if(!/^https?:\/\//i.test(base)) base = "http://" + base;
  return base.replace(/\/$/, "");
}
function optsForSelect(arr){
  return arr.map(o=>`<option value="${o.id}">${o.name}</option>`).join("");
}
async function populateXtreamSelects(){
  const live = _lists.filter(x=>x.mode==="tv");
  const vod  = _lists.filter(x=>x.mode==="video");
  const selLive   = byId("xt_live");
  const selMovies = byId("xt_movies");
  const selSeries = byId("xt_series");
  const selMixed  = byId("xt_mixed");
  if(selLive)   selLive.innerHTML   = optsForSelect(live);
  if(selMovies) selMovies.innerHTML = optsForSelect(vod);
  if(selSeries) selSeries.innerHTML = optsForSelect(vod);
  if(selMixed)  selMixed.innerHTML  = optsForSelect(vod); // miste: in genere sono 'video'
}
function valuesFromSelect(sel){
  return Array.from(sel.selectedOptions).map(o=>o.value);
}
function setSelectValues(sel, values){
  const vals = values || [];
  for(const o of sel.options){
    o.selected = vals.includes(o.value);
  }
}
function buildServerUrl(x){
  const base = canonicalServerBase();
  return base + "/xtream/" + x.id;
}
function buildFullM3UUrl(x){
  return (
    buildServerUrl(x) +
    "/get.php?username=" + encodeURIComponent(x.username) +
    "&password=" + encodeURIComponent(x.password) +
    "&playlist_type=m3u&output=ts"
  );
}

// ---------------- Xtream: CRUD ----------------
async function saveXtream(){
  const name = byId("xt_name").value.trim();
  const username = byId("xt_user").value.trim();
  const password = byId("xt_pass").value;
  const every_hours = parseInt(byId("xt_every").value,10) || 12;
  const live_list_ids   = valuesFromSelect(byId("xt_live"));
  const movie_list_ids  = valuesFromSelect(byId("xt_movies"));
  const series_list_ids = valuesFromSelect(byId("xt_series"));
  const mixed_list_ids  = valuesFromSelect(byId("xt_mixed"));
  if(!name || !username || !password){ alert("Compila nome, username e password"); return; }
  const payload = { name, username, password, every_hours, live_list_ids, movie_list_ids, series_list_ids, mixed_list_ids };
  try{
    if(_editingXt){
      await jpost(`/admin/xtreams/${_editingXt}/update`, payload);
    }else{
      await jpost("/admin/xtreams", payload);
    }
    resetXtreamForm();
    await loadXtreams();
  }catch(e){
    alert("Errore: " + e.message);
  }
}

function resetXtreamForm(){
  byId("xt_name").value = "";
  byId("xt_user").value = "";
  byId("xt_pass").value = "";
  byId("xt_every").value = "12";
  setSelectValues(byId("xt_live"), []);
  setSelectValues(byId("xt_movies"), []);
  setSelectValues(byId("xt_series"), []);
  setSelectValues(byId("xt_mixed"), []);
  _editingXt = null;
  const btn = byId("btnSaveXtream");
  if(btn) btn.textContent = "Crea Xtream";
}

function startEditXtream(x){
  _editingXt = x.id;
  byId("xt_name").value = x.name || "";
  byId("xt_user").value = x.username || "";
  byId("xt_pass").value = x.password || "";
  byId("xt_every").value = x.every_hours || 12;
  setSelectValues(byId("xt_live"), x.live_list_ids || []);
  setSelectValues(byId("xt_movies"), x.movie_list_ids || []);
  setSelectValues(byId("xt_series"), x.series_list_ids || []);
  setSelectValues(byId("xt_mixed"), x.mixed_list_ids || []);
  const btn = byId("btnSaveXtream");
  if(btn) btn.textContent = "Salva Modifiche";
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadXtreams(){
  const box = byId("xtreams");
  if(!box){ return; }
  box.textContent = "carico...";
  try{
    const { items } = await jget("/admin/xtreams.json");
    if(!items || !items.length){
      box.textContent = "";
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "Nessun xtream salvato";
      box.appendChild(p);
      return;
    }

    // costruisce mappa id -> nome per le playlist
    const listNameById = {};
    for(const l of _lists){ listNameById[l.id] = l.name; }
    const names = ids => (ids || []).map(id => listNameById[id] || id).join(", ");
    const catNode = (label, ids) => {
      const div = document.createElement("div");
      div.className = "xt-cat";
      const b = document.createElement("b");
      b.textContent = label + ":";
      div.appendChild(b);
      div.appendChild(document.createTextNode(" "));
      if(ids && ids.length){
        div.appendChild(document.createTextNode(names(ids)));
      }else{
        const span = document.createElement("span");
        span.className = "muted";
        span.textContent = "Nessuna";
        div.appendChild(span);
      }
      return div;
    };

    box.textContent = "";
    for(const x of items){
      const row = document.createElement("div");
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
      const btn = (txt, act, extra)=>{
        const b = document.createElement("button");
        b.className = "small" + (extra ? " " + extra : "");
        b.textContent = txt;
        b.dataset.act = act;
        return b;
      };
      const editBtn = btn("Modifica", "edit");
      const refreshBtn = btn("Aggiorna", "refresh");
      const copyServerBtn = btn("Copia URL server", "copy-server");
      const copyFullBtn = btn("Copia URL completa", "copy-full");
      const delBtn = btn("Elimina", "del", "danger");
      opsDiv.append(editBtn, refreshBtn, copyServerBtn, copyFullBtn, delBtn);
      row.appendChild(opsDiv);

      editBtn.onclick = ()=>{ startEditXtream(x); };
      refreshBtn.onclick = async ()=>{
        const hrs = parseInt(hrsInput.value,10)||12;
        await jpost(`/admin/xtreams/${x.id}/update`, { every_hours: hrs, refresh: true });
        await loadXtreams();
      };
      delBtn.onclick = async ()=>{
        if(!confirm("Eliminare questo xtream?")) return;
        await jdel(`/admin/xtreams/${x.id}`);
        await loadXtreams();
      };
      copyServerBtn.onclick = async ()=>{
        const s = serverUrl;
        try{ await navigator.clipboard.writeText(s); alert("Copiato: " + s); }
        catch(e){
          const ta = document.createElement("textarea"); ta.value=s; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); alert("Copiato (fallback): " + s);
        }
      };
      copyFullBtn.onclick = async ()=>{
        const s = fullUrl;
        try{ await navigator.clipboard.writeText(s); alert("Copiato: " + s); }
        catch(e){
          const ta = document.createElement("textarea"); ta.value=s; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); alert("Copiato (fallback): " + s);
        }
      };

      box.appendChild(row);
    }
  }catch(e){
    console.error(e);
    box.textContent = "";
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Errore nel caricare gli xtream";
    box.appendChild(p);
  }
}

// ---------------- Boot ----------------
document.addEventListener("DOMContentLoaded", ()=>{
  byId("btnSave").onclick = saveSettings;
  byId("btnConvert").onclick = convertOnce;
  byId("btnAdd").onclick = addList;
  const btnSaveXt = byId("btnSaveXtream");
  if(btnSaveXt) btnSaveXt.onclick = saveXtream;
  resetXtreamForm();
  loadSettings().then(async ()=>{
    await loadLists();
    await loadXtreams();
  });
});
